#!/usr/bin/env python3
"""
FY2025（2025-04-01～2026-03-31）功能使用年度总结（多图版）。

输出 HTML：仓库根「图表/FY2025_功能使用年度总结.html」（仅产物；Chart 与样式来自本 skill）。

缓存：「.cursor/skills/trend-chart/cache/fy25_usage_raw.json」（联网拉数写入；--offline 仅读该文件渲染）。
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


FY_START, FY_END = dt.date(2025, 4, 1), dt.date(2026, 3, 31)
FY_LABEL = "FY2025（2025-04-01～2026-03-31）"


def _repo_root() -> Path:
    root = Path(__file__).resolve().parent.parent
    if (root / "查询指标").is_dir():
        return root
    for anc in Path(__file__).resolve().parents:
        if (anc / "查询指标").is_dir():
            return anc
    return root


ROOT = _repo_root()
SKILL_ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / ".cursor/skills/weekly-core-metrics/scripts/config.json"
OUT_DIR = ROOT / "图表"
FY_CACHE_PATH = SKILL_ROOT / "cache" / "fy25_usage_raw.json"


def months_in_fy() -> List[str]:
    months: List[str] = []
    y, m = 2025, 4
    for _ in range(12):
        months.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y += 1
            m = 1
    return months


MONTHS = months_in_fy()
XLABELS = [f"{x[2:4]}/{x[5:]}" for x in MONTHS]


def ym_to_range(ym: str) -> Tuple[dt.date, dt.date]:
    y, m = int(ym[:4]), int(ym[5:7])
    last = calendar.monthrange(y, m)[1]
    return dt.date(y, m, 1), dt.date(y, m, last)


def load_cfg() -> dict:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def post_sql(cfg: dict, instance_name: str, tb_name: str, sql: str, limit: str = "8000") -> dict:
    auth = cfg["auth"]
    csrf, sid = auth["csrftoken"], auth["sessionid"]
    data = {
        "instance_name": instance_name,
        "db_name": cfg.get("db_name", "liteman"),
        "schema_name": cfg.get("schema_name", "public"),
        "tb_name": tb_name,
        "sql_content": sql.strip(),
        "limit_num": limit,
    }
    req = urllib.request.Request(
        cfg["archery_url"],
        data=urllib.parse.urlencode(data).encode("utf-8"),
        method="POST",
    )
    req.add_header("content-type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("x-csrftoken", csrf)
    req.add_header("cookie", f"csrftoken={csrf}; sessionid={sid}")
    req.add_header("x-requested-with", "XMLHttpRequest")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rows(payload: dict) -> Tuple[List[str], List[list]]:
    d = payload.get("data") or {}
    return d.get("column_list") or [], d.get("rows") or []


def scalar(payload: dict, key: str) -> float:
    cols, r = rows(payload)
    if not cols or not r:
        return 0.0
    return float(r[0][cols.index(key)] or 0)


def sr_scalar(cfg: dict, sql: str, key: str) -> float:
    p = post_sql(cfg, "小工单_阿里云_prod_starrocks", "trace_log_dp", sql, limit="100")
    if p.get("status") != 0:
        raise RuntimeError(p.get("msg"))
    return scalar(p, key)


def sr_monthly_pageview(cfg: dict, url_like: str) -> Dict[str, Dict[str, float]]:
    """
    StarRocks 月度：覆盖（>=1天）、活跃（>=2天）、PV、PV/覆盖、留存（上月覆盖→本月仍覆盖）。
    """
    out: Dict[str, Dict[str, float]] = {m: {"cov": 0, "act": 0, "pv": 0, "pv_per_cov": 0, "ret": None} for m in MONTHS}

    for ym in MONTHS:
        ms, me = ym_to_range(ym)
        s, e = ms.isoformat(), me.isoformat()

        sql_cov = f"""
SELECT COUNT(DISTINCT orgId) AS c
FROM trace_log_dp
WHERE dat BETWEEN DATE '{s}' AND DATE '{e}'
  AND event='PageView'
  AND get_json_string(eventValues,'$.url') LIKE '{url_like}'
""".strip()
        sql_act = f"""
SELECT COUNT(1) AS c FROM (
  SELECT orgId
  FROM trace_log_dp
  WHERE dat BETWEEN DATE '{s}' AND DATE '{e}'
    AND event='PageView'
    AND get_json_string(eventValues,'$.url') LIKE '{url_like}'
  GROUP BY orgId
  HAVING COUNT(DISTINCT dat) >= 2
) t
""".strip()
        sql_pv = f"""
SELECT COUNT(1) AS c
FROM trace_log_dp
WHERE dat BETWEEN DATE '{s}' AND DATE '{e}'
  AND event='PageView'
  AND get_json_string(eventValues,'$.url') LIKE '{url_like}'
""".strip()

        cov = sr_scalar(cfg, sql_cov, "c")
        act = sr_scalar(cfg, sql_act, "c")
        pv = sr_scalar(cfg, sql_pv, "c")

        out[ym]["cov"] = cov
        out[ym]["act"] = act
        out[ym]["pv"] = pv
        out[ym]["pv_per_cov"] = (pv / cov) if cov else 0

    # 月留存：prev_cov -> cur_cov（都至少一次 PageView）
    for i in range(1, len(MONTHS)):
        prev_ym, cur_ym = MONTHS[i - 1], MONTHS[i]
        ps, pe = ym_to_range(prev_ym)
        cs, ce = ym_to_range(cur_ym)
        # Archery/StarRocks 侧对部分 CTE/USING 语法可能有限制，改为无 CTE 的子查询写法。
        p_sub = f"""
SELECT DISTINCT orgId AS org_id
FROM trace_log_dp
WHERE dat BETWEEN DATE '{ps.isoformat()}' AND DATE '{pe.isoformat()}'
  AND event='PageView'
  AND get_json_string(eventValues,'$.url') LIKE '{url_like}'
""".strip()
        c_sub = f"""
SELECT DISTINCT orgId AS org_id
FROM trace_log_dp
WHERE dat BETWEEN DATE '{cs.isoformat()}' AND DATE '{ce.isoformat()}'
  AND event='PageView'
  AND get_json_string(eventValues,'$.url') LIKE '{url_like}'
""".strip()

        sql_prev = f"SELECT COUNT(1) AS c FROM ({p_sub}) p"
        sql_retained = f"SELECT COUNT(1) AS c FROM ({p_sub}) p JOIN ({c_sub}) c ON p.org_id = c.org_id"

        prev_cnt = sr_scalar(cfg, sql_prev, "c")
        retained_cnt = sr_scalar(cfg, sql_retained, "c")
        out[cur_ym]["ret"] = (retained_cnt / prev_cnt) if prev_cnt else None

    return out


def sr_monthly_tv(cfg: dict) -> Dict[str, Dict[str, float]]:
    """TV 月度：覆盖（>=1天）、活跃（>=2天）、事件量、平均活跃天数/厂。"""
    out: Dict[str, Dict[str, float]] = {m: {"cov": 0, "act": 0, "events": 0, "avg_days": 0} for m in MONTHS}
    for ym in MONTHS:
        ms, me = ym_to_range(ym)
        s, e = ms.isoformat(), me.isoformat()
        sql_cov = f"""
SELECT COUNT(DISTINCT orgId) AS c
FROM trace_log_dp
WHERE dat BETWEEN DATE '{s}' AND DATE '{e}'
  AND event='tv-device-info'
""".strip()
        sql_act = f"""
SELECT COUNT(1) AS c FROM (
  SELECT orgId
  FROM trace_log_dp
  WHERE dat BETWEEN DATE '{s}' AND DATE '{e}'
    AND event='tv-device-info'
  GROUP BY orgId
  HAVING COUNT(DISTINCT dat) >= 2
) t
""".strip()
        sql_events = f"""
SELECT COUNT(1) AS c
FROM trace_log_dp
WHERE dat BETWEEN DATE '{s}' AND DATE '{e}'
  AND event='tv-device-info'
""".strip()
        sql_avg_days = f"""
SELECT AVG(d) AS avg_d FROM (
  SELECT orgId, COUNT(DISTINCT dat) AS d
  FROM trace_log_dp
  WHERE dat BETWEEN DATE '{s}' AND DATE '{e}'
    AND event='tv-device-info'
  GROUP BY orgId
) t
""".strip()
        out[ym]["cov"] = sr_scalar(cfg, sql_cov, "c")
        out[ym]["act"] = sr_scalar(cfg, sql_act, "c")
        out[ym]["events"] = sr_scalar(cfg, sql_events, "c")
        out[ym]["avg_days"] = sr_scalar(cfg, sql_avg_days, "avg_d")
    return out


def adb_fetch_org_sets(cfg: dict, tb: str, ym: str, where_extra: str, two_day: bool = False) -> Set[str]:
    ms, me = ym_to_range(ym)
    s, e = ms.isoformat(), me.isoformat()
    if two_day:
        sql = f"""
SELECT org_id FROM (
  SELECT org_id, COUNT(DISTINCT created_at::date) AS d
  FROM {tb}
  WHERE created_at::date BETWEEN DATE '{s}' AND DATE '{e}' AND ({where_extra})
  GROUP BY org_id
) t WHERE d >= 2
""".strip()
    else:
        sql = f"""
SELECT DISTINCT org_id
FROM {tb}
WHERE created_at::date BETWEEN DATE '{s}' AND DATE '{e}' AND ({where_extra})
""".strip()

    merged: Set[str] = set()
    for inst in cfg["instances"]:
        p = post_sql(cfg, inst, tb, sql, limit="500000")
        if p.get("status") != 0:
            raise RuntimeError(f"{inst}: {p.get('msg')}")
        cols, r = rows(p)
        if not cols:
            continue
        idx = cols.index("org_id")
        for row in r:
            if row[idx] is None:
                continue
            merged.add(str(int(row[idx])) if not isinstance(row[idx], str) else row[idx])
    return merged


def adb_scalar_sum(cfg: dict, tb: str, ym: str, where_extra: str, expr: str, key: str) -> float:
    ms, me = ym_to_range(ym)
    s, e = ms.isoformat(), me.isoformat()
    sql = f"""
SELECT {expr} AS {key}
FROM {tb}
WHERE created_at::date BETWEEN DATE '{s}' AND DATE '{e}' AND ({where_extra})
""".strip()
    acc = 0.0
    for inst in cfg["instances"]:
        p = post_sql(cfg, inst, tb, sql, limit="100")
        if p.get("status") != 0:
            raise RuntimeError(f"{inst}: {p.get('msg')}")
        acc += scalar(p, key)
    return acc


def adb_monthly_collab(cfg: dict) -> Dict[str, Dict[str, float]]:
    """
    协同任务（月度）：
    - 覆盖：>=1天创建任务的工厂（跨分片并集去重）
    - 活跃：>=2天创建任务的工厂（跨分片并集去重）
    - 任务量：创建任务条数（分片相加）
    - 关联比例：associate_id 非空占比（分片相加）
    - 月留存：上月活跃（>=2天）→本月仍活跃
    """
    out: Dict[str, Dict[str, float]] = {m: {"cov": 0, "act": 0, "tasks": 0, "assoc": 0, "ret": None} for m in MONTHS}
    cov_sets: Dict[str, Set[str]] = {}
    act_sets: Dict[str, Set[str]] = {}

    for ym in MONTHS:
        cov = adb_fetch_org_sets(cfg, "dt_collaborative_task", ym, "TRUE", two_day=False)
        act = adb_fetch_org_sets(cfg, "dt_collaborative_task", ym, "TRUE", two_day=True)
        tasks = adb_scalar_sum(cfg, "dt_collaborative_task", ym, "TRUE", "COUNT(1)", "c")
        # Archery/ADB 侧可能不支持 FILTER 语法，改为 CASE WHEN
        assoc = adb_scalar_sum(
            cfg,
            "dt_collaborative_task",
            ym,
            "TRUE",
            "SUM(CASE WHEN associate_id IS NOT NULL THEN 1 ELSE 0 END)",
            "c",
        )

        cov_sets[ym] = cov
        act_sets[ym] = act
        out[ym]["cov"] = len(cov)
        out[ym]["act"] = len(act)
        out[ym]["tasks"] = tasks
        out[ym]["assoc"] = (assoc / tasks) if tasks else 0

    for i in range(1, len(MONTHS)):
        prev_ym, cur_ym = MONTHS[i - 1], MONTHS[i]
        prev = act_sets[prev_ym]
        cur = act_sets[cur_ym]
        out[cur_ym]["ret"] = (len(prev & cur) / len(prev)) if prev else None

    return out


def adb_monthly_outsource(cfg: dict) -> Dict[str, Dict[str, float]]:
    """
    委外管理（月度）：
    - 订单客户：dt_outsource_order
    - 收货客户：dt_outsource_post post_type_name=收货、未删
    - 覆盖：订单∩收货
    - 转化：覆盖/订单
    - 月留存：上月覆盖→本月仍覆盖
    """
    out: Dict[str, Dict[str, float]] = {
        m: {"orders": 0, "posts": 0, "covered": 0, "convert": 0, "ret": None} for m in MONTHS
    }
    covered_sets: Dict[str, Set[str]] = {}

    for ym in MONTHS:
        orders = adb_fetch_org_sets(cfg, "dt_outsource_order", ym, "TRUE", two_day=False)
        posts = adb_fetch_org_sets(
            cfg,
            "dt_outsource_post",
            ym,
            "post_type_name='收货' AND COALESCE(deleted_at,0)=0",
            two_day=False,
        )
        covered = orders & posts
        covered_sets[ym] = covered
        out[ym]["orders"] = len(orders)
        out[ym]["posts"] = len(posts)
        out[ym]["covered"] = len(covered)
        out[ym]["convert"] = (len(covered) / len(orders)) if orders else 0

    for i in range(1, len(MONTHS)):
        prev_ym, cur_ym = MONTHS[i - 1], MONTHS[i]
        prev = covered_sets[prev_ym]
        cur = covered_sets[cur_ym]
        out[cur_ym]["ret"] = (len(prev & cur) / len(prev)) if prev else None

    return out


def series(bundle: Dict[str, Dict[str, float]], key: str) -> List[Optional[float]]:
    return [bundle[m].get(key) for m in MONTHS]


def fmt_int(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return str(int(round(v)))


def fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"{v * 100:.1f}%"


def wow(cur: Optional[float], pre: Optional[float]) -> Optional[float]:
    if cur is None or pre is None or pre == 0:
        return None
    return (cur - pre) / pre


def insight_monthly(values: List[Optional[float]], labels: List[str], kind: str) -> str:
    """更偏年度总结：峰值、低谷、末月 vs 起始、近3个月趋势。"""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    pts = [(i, v) for i, v in pts if isinstance(v, (int, float))]
    if not pts or all((v == 0 for _, v in pts)):
        return "该指标在当前可查数据窗口内为 0 或缺失；多为埋点保留/启用时间限制，建议结合上线节奏解读。"

    nonzero = [(i, v) for i, v in pts if v != 0]
    first_i, first_v = nonzero[0] if nonzero else pts[0]
    last_i, last_v = nonzero[-1] if nonzero else pts[-1]
    mx_i, mx_v = max(nonzero or pts, key=lambda x: x[1])
    mn_i, mn_v = min(nonzero or pts, key=lambda x: x[1])

    # 近3个月趋势（最后3个点）
    tail = [v for _, v in pts[-3:]]
    tail_trend = ""
    if len(tail) == 3 and tail[0] != 0:
        tail_chg = (tail[-1] - tail[0]) / tail[0]
        if abs(tail_chg) >= 0.1:
            tail_trend = f"近三月{'上行' if tail_chg > 0 else '下行'}约 {abs(tail_chg) * 100:.0f}%；"

    if kind == "pct":
        return (
            f"区间峰值 **{fmt_pct(mx_v)}**（{labels[mx_i]}），低谷 **{fmt_pct(mn_v)}**（{labels[mn_i]}）；"
            f"{tail_trend}末月为 **{fmt_pct(last_v)}**。"
        )
    if kind == "float1":
        return (
            f"区间峰值 **{mx_v:.1f}**（{labels[mx_i]}），低谷 **{mn_v:.1f}**（{labels[mn_i]}）；"
            f"{tail_trend}末月为 **{last_v:.1f}**。"
        )
    return (
        f"区间峰值 **{fmt_int(mx_v)}**（{labels[mx_i]}），低谷 **{fmt_int(mn_v)}**（{labels[mn_i]}）；"
        f"{tail_trend}末月为 **{fmt_int(last_v)}**。"
    )


def js_arr(vals: Iterable[Optional[float]], is_pct: bool = False, digits: int = 2) -> str:
    xs: List[str] = []
    for v in vals:
        if v is None:
            xs.append("null")
        else:
            if is_pct:
                xs.append(f"{v * 100:.{digits}f}")
            else:
                xs.append(f"{float(v):.{digits}f}")
    return "[" + ", ".join(xs) + "]"


def build_html(data: dict) -> str:
    labels = json.dumps(XLABELS, ensure_ascii=False)
    report_css = (SKILL_ROOT / "templates" / "chart-report-light.css").read_text(encoding="utf-8")

    # bundles
    custom = data["custom"]
    multi = data["multi"]
    tv = data["tv"]
    collab = data["collab"]
    outsource = data["outsource"]

    custom_cov = series(custom, "cov")
    custom_act = series(custom, "act")
    custom_pv = series(custom, "pv")
    custom_pv_per = series(custom, "pv_per_cov")
    custom_ret = series(custom, "ret")

    multi_cov = series(multi, "cov")
    multi_act = series(multi, "act")
    multi_pv = series(multi, "pv")
    multi_pv_per = series(multi, "pv_per_cov")
    multi_ret = series(multi, "ret")

    tv_cov = series(tv, "cov")
    tv_act = series(tv, "act")
    tv_events = series(tv, "events")
    tv_avg_days = series(tv, "avg_days")

    col_cov = series(collab, "cov")
    col_act = series(collab, "act")
    col_tasks = series(collab, "tasks")
    col_assoc = series(collab, "assoc")
    col_ret = series(collab, "ret")
    col_tasks_per = [
        (col_tasks[i] / col_cov[i]) if col_cov[i] else 0 for i in range(len(MONTHS))
    ]

    out_orders = series(outsource, "orders")
    out_posts = series(outsource, "posts")
    out_cov = series(outsource, "covered")
    out_convert = series(outsource, "convert")
    out_ret = series(outsource, "ret")

    # KPI（末月 vs 上月）
    def badge(cur: Optional[float], pre: Optional[float], is_pct: bool = False) -> str:
        w = wow(cur, pre)
        if w is None:
            return ""
        cls = "up" if w >= 0 else "down"
        sym = "▲" if w >= 0 else "▼"
        return f'<span class="badge {cls}">{sym} {abs(w) * 100:.1f}%</span>'

    last_i = len(MONTHS) - 1
    prev_i = len(MONTHS) - 2

    # 洞察
    ins = {
        # 自定义
        "custom_cov": insight_monthly(custom_cov, XLABELS, "int"),
        "custom_act": insight_monthly(custom_act, XLABELS, "int"),
        "custom_ret": insight_monthly(custom_ret, XLABELS, "pct"),
        "custom_pv": insight_monthly(custom_pv, XLABELS, "int"),
        "custom_pv_per": insight_monthly(custom_pv_per, XLABELS, "float1"),
        # 多维
        "multi_cov": insight_monthly(multi_cov, XLABELS, "int"),
        "multi_act": insight_monthly(multi_act, XLABELS, "int"),
        "multi_ret": insight_monthly(multi_ret, XLABELS, "pct"),
        "multi_pv": insight_monthly(multi_pv, XLABELS, "int"),
        "multi_pv_per": insight_monthly(multi_pv_per, XLABELS, "float1"),
        # TV
        "tv_cov": insight_monthly(tv_cov, XLABELS, "int"),
        "tv_act": insight_monthly(tv_act, XLABELS, "int"),
        "tv_events": insight_monthly(tv_events, XLABELS, "int"),
        "tv_avg_days": insight_monthly(tv_avg_days, XLABELS, "float1"),
        # 协同
        "col_cov": insight_monthly(col_cov, XLABELS, "int"),
        "col_act": insight_monthly(col_act, XLABELS, "int"),
        "col_ret": insight_monthly(col_ret, XLABELS, "pct"),
        "col_tasks": insight_monthly(col_tasks, XLABELS, "int"),
        "col_assoc": insight_monthly(col_assoc, XLABELS, "pct"),
        "col_tasks_per": insight_monthly(col_tasks_per, XLABELS, "float1"),
        # 委外
        "out_cov": insight_monthly(out_cov, XLABELS, "int"),
        "out_ret": insight_monthly(out_ret, XLABELS, "pct"),
        "out_convert": insight_monthly(out_convert, XLABELS, "pct"),
        "out_orders": insight_monthly(out_orders, XLABELS, "int"),
        "out_posts": insight_monthly(out_posts, XLABELS, "int"),
    }

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{FY_LABEL} · 功能使用年度总结</title>
<!-- 依赖：Chart.js UMD 内联（skill/vendor，避免 file:// 相对路径失败） -->
<script>__CHART_UMD_PLACEHOLDER__</script>
<!-- 样式：与通用业务图表共用 skill/templates/chart-report-light.css -->
<style>
{report_css}
</style>
</head>
<body>

<!-- ========= 页头与说明 ========= -->
<h1>{FY_LABEL} · 功能使用年度总结</h1>
<p class="subtitle">
时间粒度：自然月（25/04～26/03）。<br>
说明：自定义报表 / 多维进销存 / TV 来自 <code>trace_log_dp</code>，受保留期与埋点启用时间影响；早期为 0 不等于业务无使用。
</p>

<!-- ========= KPI：末月 vs 上月 ========= -->
<div class="summary-row">
  <div class="kpi">
    <div class="title">多维进销存 · 月覆盖工厂（末月）</div>
    <div class="val">{fmt_int(multi_cov[last_i])}{badge(multi_cov[last_i], multi_cov[prev_i])}</div>
    <div class="sub">上月 {fmt_int(multi_cov[prev_i])}</div>
  </div>
  <div class="kpi">
    <div class="title">TV 版 · 月覆盖工厂（末月）</div>
    <div class="val">{fmt_int(tv_cov[last_i])}{badge(tv_cov[last_i], tv_cov[prev_i])}</div>
    <div class="sub">上月 {fmt_int(tv_cov[prev_i])}</div>
  </div>
  <div class="kpi">
    <div class="title">协同任务 · 月活跃工厂（≥2天，末月）</div>
    <div class="val">{fmt_int(col_act[last_i])}{badge(col_act[last_i], col_act[prev_i])}</div>
    <div class="sub">上月 {fmt_int(col_act[prev_i])}</div>
  </div>
  <div class="kpi">
    <div class="title">委外管理 · 转化率（订单→覆盖，末月）</div>
    <div class="val">{fmt_pct(out_convert[last_i])}{badge(out_convert[last_i], out_convert[prev_i])}</div>
    <div class="sub">上月 {fmt_pct(out_convert[prev_i])}</div>
  </div>
</div>

<!-- ========= 模块：自定义报表 ========= -->
<div class="section">
  <div class="section-title teal">📊 自定义报表</div>
  <div class="chart-grid three">
    <div class="chart-card">
      <h3>覆盖/活跃（工厂）</h3>
      <div class="chart-body">
        <canvas id="c_custom_users"></canvas>
      </div>
      <div class="insight teal"><b>覆盖</b>：{ins['custom_cov']}<br><b>活跃（≥2天）</b>：{ins['custom_act']}</div>
    </div>
    <div class="chart-card">
      <h3>使用深度（PV & PV/厂）</h3>
      <div class="chart-body">
        <canvas id="c_custom_depth"></canvas>
      </div>
      <div class="insight teal"><b>PV</b>：{ins['custom_pv']}<br><b>PV/覆盖厂</b>：{ins['custom_pv_per']}</div>
    </div>
    <div class="chart-card">
      <h3>月留存（上月→本月）</h3>
      <div class="chart-body">
        <canvas id="c_custom_ret"></canvas>
      </div>
      <div class="insight teal">{ins['custom_ret']}</div>
    </div>
  </div>
</div>

<!-- ========= 模块：多维进销存 ========= -->
<div class="section">
  <div class="section-title">📦 多维进销存报表</div>
  <div class="chart-grid three">
    <div class="chart-card">
      <h3>覆盖/活跃（工厂）</h3>
      <div class="chart-body">
        <canvas id="c_multi_users"></canvas>
      </div>
      <div class="insight"><b>覆盖</b>：{ins['multi_cov']}<br><b>活跃（≥2天）</b>：{ins['multi_act']}</div>
    </div>
    <div class="chart-card">
      <h3>使用深度（PV & PV/厂）</h3>
      <div class="chart-body">
        <canvas id="c_multi_depth"></canvas>
      </div>
      <div class="insight"><b>PV</b>：{ins['multi_pv']}<br><b>PV/覆盖厂</b>：{ins['multi_pv_per']}</div>
    </div>
    <div class="chart-card">
      <h3>月留存（上月→本月）</h3>
      <div class="chart-body">
        <canvas id="c_multi_ret"></canvas>
      </div>
      <div class="insight">{ins['multi_ret']}</div>
    </div>
  </div>
</div>

<!-- ========= 模块：TV ========= -->
<div class="section">
  <div class="section-title orange">📺 TV 版</div>
  <div class="chart-grid three">
    <div class="chart-card">
      <h3>覆盖/活跃（工厂）</h3>
      <div class="chart-body">
        <canvas id="c_tv_users"></canvas>
      </div>
      <div class="insight orange"><b>覆盖</b>：{ins['tv_cov']}<br><b>活跃（≥2天）</b>：{ins['tv_act']}</div>
    </div>
    <div class="chart-card">
      <h3>使用强度（事件量）</h3>
      <div class="chart-body">
        <canvas id="c_tv_events"></canvas>
      </div>
      <div class="insight orange">{ins['tv_events']}</div>
    </div>
    <div class="chart-card">
      <h3>粘性（平均活跃天数/厂）</h3>
      <div class="chart-body">
        <canvas id="c_tv_days"></canvas>
      </div>
      <div class="insight orange">{ins['tv_avg_days']}</div>
    </div>
  </div>
</div>

<!-- ========= 模块：协同任务 ========= -->
<div class="section">
  <div class="section-title green">🤝 协同任务</div>
  <div class="chart-grid three">
    <div class="chart-card">
      <h3>覆盖/活跃（工厂）</h3>
      <div class="chart-body">
        <canvas id="c_col_users"></canvas>
      </div>
      <div class="insight green"><b>覆盖</b>：{ins['col_cov']}<br><b>活跃（≥2天）</b>：{ins['col_act']}</div>
    </div>
    <div class="chart-card">
      <h3>效率（任务量 & 任务/厂）</h3>
      <div class="chart-body">
        <canvas id="c_col_tasks"></canvas>
      </div>
      <div class="insight green"><b>任务量</b>：{ins['col_tasks']}<br><b>任务/覆盖厂</b>：{ins['col_tasks_per']}</div>
    </div>
    <div class="chart-card">
      <h3>治理（关联比例 & 月留存）</h3>
      <div class="chart-body">
        <canvas id="c_col_quality"></canvas>
      </div>
      <div class="insight green"><b>工单关联比例</b>：{ins['col_assoc']}<br><b>月留存</b>：{ins['col_ret']}</div>
    </div>
  </div>
</div>

<!-- ========= 模块：委外管理 ========= -->
<div class="section">
  <div class="section-title purple">🧾 委外管理</div>
  <div class="chart-grid three">
    <div class="chart-card">
      <h3>规模（订单/收货/覆盖）</h3>
      <div class="chart-body">
        <canvas id="c_out_scale"></canvas>
      </div>
      <div class="insight purple"><b>订单客户</b>：{ins['out_orders']}<br><b>收货客户</b>：{ins['out_posts']}<br><b>覆盖（订单∩收货）</b>：{ins['out_cov']}</div>
    </div>
    <div class="chart-card">
      <h3>转化率（覆盖/订单）</h3>
      <div class="chart-body">
        <canvas id="c_out_convert"></canvas>
      </div>
      <div class="insight purple">{ins['out_convert']}</div>
    </div>
    <div class="chart-card">
      <h3>月留存（上月覆盖→本月仍覆盖）</h3>
      <div class="chart-body">
        <canvas id="c_out_ret"></canvas>
      </div>
      <div class="insight purple">{ins['out_ret']}</div>
    </div>
  </div>
</div>

<p style="font-size:11px;color:#aaa;margin-top:10px;line-height:1.6">
数据缓存：<code>.cursor/skills/trend-chart/cache/fy25_usage_raw.json</code>。
联网刷新：<code>python3 .cursor/skills/trend-chart/scripts/generate_fy25_usage_report.py</code>；
离线渲染：<code>python3 .cursor/skills/trend-chart/scripts/generate_fy25_usage_report.py --offline</code>。
</p>

<!-- ========= Chart.js 初始化（与 chart-report-light.css 中 .chart-body 配合） ========= -->
<script>
const labels = {labels};

const BLUE='#4361ee', LBLUE='#7b8cde';
const GREEN='#2d9d78', LGREEN='#5dc8a0';
const PURPLE='#6f58ff', LPURPLE='#a08cff';
const ORANGE='#f77f00', YELLOW='#fcbf49';
const TEAL='#118ab2', LTEAL='#5dc8a0';

function mkLine(label, data, color, dash=[]) {{
  return {{
    type: 'line',
    label, data,
    borderColor: color, backgroundColor: color+'22',
    pointBackgroundColor: color, pointRadius: 4, pointHoverRadius: 6,
    borderWidth: 2.2, borderDash: dash, tension: 0.35, fill: false, spanGaps: true,
  }};
}}
function mkBar(label, data, color) {{
  return {{ type:'bar', label, data, backgroundColor: color+'aa', borderRadius: 6 }};
}}
const baseOpts = (yLabel) => ({{
  responsive: true,
  maintainAspectRatio: false,
  layout: {{ padding: {{ top: 10, right: 10, bottom: 6, left: 8 }} }},
  interaction: {{ mode:'index', intersect:false }},
  plugins: {{
    legend: {{ position:'top', labels:{{ font:{{size:12}}, padding:12 }} }},
    tooltip: {{ padding:10, cornerRadius:8 }},
  }},
  scales: {{
    x: {{ grid:{{color:'#f2f2f2'}}, ticks:{{font:{{size:12}}}} }},
    y: {{
      grid:{{color:'#f2f2f2'}},
      ticks:{{ font:{{size:12}}, padding: 6 }},
      title:{{display:!!yLabel,text:yLabel}},
      beginAtZero:true,
      grace: '8%',
    }},
  }},
}});
const pctOpts = (yLabel='%') => {{
  const o = baseOpts(yLabel);
  o.scales.y.min = 0; o.scales.y.max = 100; o.scales.y.grace = 0;
  o.scales.y.ticks.callback = v => v + '%';
  o.plugins.tooltip.callbacks = {{ label: ctx => ctx.dataset.label+': '+(ctx.parsed.y??'-')+'%' }};
  return o;
}};
const dualOpts = (yLeft, yRight) => ({{
  responsive: true,
  maintainAspectRatio: false,
  layout: {{ padding: {{ top: 10, right: 12, bottom: 6, left: 8 }} }},
  interaction: {{ mode:'index', intersect:false }},
  plugins: {{
    legend: {{ position:'top', labels:{{ font:{{size:12}}, padding:12 }} }},
    tooltip: {{ padding:10, cornerRadius:8 }},
  }},
  scales: {{
    x: {{ grid:{{color:'#f2f2f2'}}, ticks:{{font:{{size:12}}}} }},
    y: {{
      position:'left', beginAtZero:true, grace:'8%',
      title:{{display:true,text:yLeft}}, grid:{{color:'#f2f2f2'}},
      ticks:{{ font:{{size:12}}, padding: 6 }},
    }},
    y1: {{
      position:'right', beginAtZero:true, grace:'8%',
      title:{{display:true,text:yRight}}, grid:{{drawOnChartArea:false}},
      ticks:{{ font:{{size:12}}, padding: 6 }},
    }},
  }},
}});

// 自定义：覆盖/活跃
new Chart(document.getElementById('c_custom_users'), {{
  type:'line',
  data:{{ labels, datasets:[
    mkLine('覆盖工厂（≥1天）', {js_arr(custom_cov, False, 0)}, TEAL),
    mkLine('活跃工厂（≥2天）', {js_arr(custom_act, False, 0)}, LTEAL, [6,3]),
  ]}},
  options: baseOpts('工厂数')
}});
// 自定义深度：PV(柱) + PV/厂(线)
new Chart(document.getElementById('c_custom_depth'), {{
  type:'bar',
  data:{{ labels, datasets:[
    mkBar('PV', {js_arr(custom_pv, False, 0)}, TEAL),
    {{...mkLine('PV/覆盖厂', {js_arr(custom_pv_per, False, 2)}, '#111'), yAxisID:'y1'}},
  ]}},
  options: dualOpts('PV（次）','PV/厂')
}});
// 自定义留存
new Chart(document.getElementById('c_custom_ret'), {{
  type:'line',
  data:{{ labels, datasets:[ mkLine('月留存（上月→本月）', {js_arr(custom_ret, True, 2)}, TEAL) ]}},
  options: pctOpts('%')
}});

// 多维：覆盖/活跃
new Chart(document.getElementById('c_multi_users'), {{
  type:'line',
  data:{{ labels, datasets:[
    mkLine('覆盖工厂（≥1天）', {js_arr(multi_cov, False, 0)}, BLUE),
    mkLine('活跃工厂（≥2天）', {js_arr(multi_act, False, 0)}, LBLUE, [6,3]),
  ]}},
  options: baseOpts('工厂数')
}});
// 多维深度
new Chart(document.getElementById('c_multi_depth'), {{
  type:'bar',
  data:{{ labels, datasets:[
    mkBar('PV', {js_arr(multi_pv, False, 0)}, BLUE),
    {{...mkLine('PV/覆盖厂', {js_arr(multi_pv_per, False, 2)}, '#111'), yAxisID:'y1'}},
  ]}},
  options: dualOpts('PV（次）','PV/厂')
}});
// 多维留存
new Chart(document.getElementById('c_multi_ret'), {{
  type:'line',
  data:{{ labels, datasets:[ mkLine('月留存（上月→本月）', {js_arr(multi_ret, True, 2)}, BLUE) ]}},
  options: pctOpts('%')
}});

// TV 覆盖/活跃
new Chart(document.getElementById('c_tv_users'), {{
  type:'line',
  data:{{ labels, datasets:[
    mkLine('覆盖工厂（≥1天）', {js_arr(tv_cov, False, 0)}, ORANGE),
    mkLine('活跃工厂（≥2天）', {js_arr(tv_act, False, 0)}, YELLOW, [6,3]),
  ]}},
  options: baseOpts('工厂数')
}});
// TV 事件量
new Chart(document.getElementById('c_tv_events'), {{
  type:'line',
  data:{{ labels, datasets:[ mkLine('tv-device-info 事件量', {js_arr(tv_events, False, 0)}, ORANGE) ]}},
  options: baseOpts('次数')
}});
// TV 平均活跃天数
new Chart(document.getElementById('c_tv_days'), {{
  type:'line',
  data:{{ labels, datasets:[ mkLine('平均活跃天数/厂', {js_arr(tv_avg_days, False, 2)}, ORANGE) ]}},
  options: baseOpts('天')
}});

// 协同 覆盖/活跃
new Chart(document.getElementById('c_col_users'), {{
  type:'line',
  data:{{ labels, datasets:[
    mkLine('覆盖工厂（≥1天）', {js_arr(col_cov, False, 0)}, GREEN),
    mkLine('活跃工厂（≥2天）', {js_arr(col_act, False, 0)}, LGREEN, [6,3]),
  ]}},
  options: baseOpts('工厂数')
}});
// 协同 任务量(柱) + 任务/厂(线)
new Chart(document.getElementById('c_col_tasks'), {{
  type:'bar',
  data:{{ labels, datasets:[
    mkBar('任务量', {js_arr(col_tasks, False, 0)}, GREEN),
    {{...mkLine('任务/覆盖厂', {js_arr(col_tasks_per, False, 2)}, '#111'), yAxisID:'y1'}},
  ]}},
  options: dualOpts('任务（条）','条/厂')
}});
// 协同 关联比例 + 留存
new Chart(document.getElementById('c_col_quality'), {{
  type:'line',
  data:{{ labels, datasets:[
    mkLine('关联比例', {js_arr(col_assoc, True, 2)}, GREEN),
    mkLine('月留存（活跃≥2天）', {js_arr(col_ret, True, 2)}, '#f77f00', [4,3]),
  ]}},
  options: pctOpts('%')
}});

// 委外 规模
new Chart(document.getElementById('c_out_scale'), {{
  type:'line',
  data:{{ labels, datasets:[
    mkLine('订单客户数', {js_arr(out_orders, False, 0)}, PURPLE),
    mkLine('收货客户数', {js_arr(out_posts, False, 0)}, LPURPLE, [6,3]),
    mkLine('覆盖（订单∩收货）', {js_arr(out_cov, False, 0)}, '#111', [3,3]),
  ]}},
  options: baseOpts('工厂数')
}});
// 委外 转化率
new Chart(document.getElementById('c_out_convert'), {{
  type:'line',
  data:{{ labels, datasets:[ mkLine('转化率（覆盖/订单）', {js_arr(out_convert, True, 2)}, PURPLE) ]}},
  options: pctOpts('%')
}});
// 委外 留存
new Chart(document.getElementById('c_out_ret'), {{
  type:'line',
  data:{{ labels, datasets:[ mkLine('月留存（上月覆盖→本月仍覆盖）', {js_arr(out_ret, True, 2)}, PURPLE) ]}},
  options: pctOpts('%')
}});
</script>
</body>
</html>"""
    chart_path = SKILL_ROOT / "vendor" / "chart.umd.min.js"
    if not chart_path.is_file():
        raise FileNotFoundError(f"缺少 Chart.js 本地文件：{chart_path}（请先放入或重新下载）")
    chart_umd = chart_path.read_text(encoding="utf-8")
    html = html.replace("__CHART_UMD_PLACEHOLDER__", chart_umd)
    return html


def fetch_all(cfg: dict) -> dict:
    # 逐模块拉数，便于定位 Archery 的语法限制/超时点
    data = {"meta": {"fy": f"{FY_START.isoformat()}~{FY_END.isoformat()}", "label": FY_LABEL}}
    for k, fn in [
        ("custom", lambda: sr_monthly_pageview(cfg, "%/customDashboard/detail%")),
        ("multi", lambda: sr_monthly_pageview(cfg, "%multiInventoryReport%")),
        ("tv", lambda: sr_monthly_tv(cfg)),
        ("collab", lambda: adb_monthly_collab(cfg)),
        ("outsource", lambda: adb_monthly_outsource(cfg)),
    ]:
        try:
            print(f"[FY2025] fetching {k} ...", flush=True)
            data[k] = fn()
        except Exception as e:
            raise RuntimeError(f"{k} 拉数失败：{e}") from e
    return data


def load_offline(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    # 兼容旧结构：{months, fy, series:{...}}
    if "series" in raw:
        s = raw["series"] or {}

        def mk_monthly(defaults: dict, fill: Dict[str, dict]) -> Dict[str, dict]:
            out = {m: dict(defaults) for m in MONTHS}
            for ym, patch in fill.items():
                if ym in out:
                    out[ym].update(patch)
            return out

        # 旧缓存只有「覆盖工厂」与「PV」，没有 >=2天、留存等；离线模式下补 0/null 以便渲染。
        cd_cov = s.get("custom_dashboard") or {}
        cd_pv = s.get("custom_dashboard_pv") or {}
        mi_cov = s.get("multi_inv") or {}
        mi_pv = s.get("multi_inv_pv") or {}
        tv_cov = s.get("tv") or {}
        col_cov = s.get("collab") or {}
        out_cov = s.get("outsource") or {}

        custom = mk_monthly(
            {"cov": 0, "act": 0, "pv": 0, "pv_per_cov": 0, "ret": None},
            {m: {"cov": float(cd_cov.get(m, 0)), "pv": float(cd_pv.get(m, 0))} for m in MONTHS},
        )
        for m in MONTHS:
            custom[m]["pv_per_cov"] = (custom[m]["pv"] / custom[m]["cov"]) if custom[m]["cov"] else 0

        multi = mk_monthly(
            {"cov": 0, "act": 0, "pv": 0, "pv_per_cov": 0, "ret": None},
            {m: {"cov": float(mi_cov.get(m, 0)), "pv": float(mi_pv.get(m, 0))} for m in MONTHS},
        )
        for m in MONTHS:
            multi[m]["pv_per_cov"] = (multi[m]["pv"] / multi[m]["cov"]) if multi[m]["cov"] else 0

        tv = mk_monthly(
            {"cov": 0, "act": 0, "events": 0, "avg_days": 0},
            {m: {"cov": float(tv_cov.get(m, 0))} for m in MONTHS},
        )

        collab = mk_monthly(
            {"cov": 0, "act": 0, "tasks": 0, "assoc": 0, "ret": None},
            {m: {"cov": float(col_cov.get(m, 0))} for m in MONTHS},
        )

        outsource = mk_monthly(
            {"orders": 0, "posts": 0, "covered": 0, "convert": 0, "ret": None},
            {m: {"covered": float(out_cov.get(m, 0))} for m in MONTHS},
        )

        return {"meta": {"fy": raw.get("fy"), "label": FY_LABEL}, "custom": custom, "multi": multi, "tv": tv, "collab": collab, "outsource": outsource}
    return raw


def main() -> None:
    ap = argparse.ArgumentParser(description="FY2025 功能使用年度总结（多图版）")
    ap.add_argument("--offline", action="store_true", help="仅用 skill/cache/fy25_usage_raw.json 渲染 HTML，不请求 Archery")
    ap.add_argument("--output", default=str(OUT_DIR / "FY2025_功能使用年度总结.html"))
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if args.offline:
        if not FY_CACHE_PATH.is_file():
            raise RuntimeError(f"缺少缓存文件：{FY_CACHE_PATH}")
        data = load_offline(FY_CACHE_PATH)
    else:
        cfg = load_cfg()
        data = fetch_all(cfg)
        FY_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    html = build_html(data)
    out_path = Path(args.output)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

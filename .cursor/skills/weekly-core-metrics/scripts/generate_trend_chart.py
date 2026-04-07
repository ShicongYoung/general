#!/usr/bin/env python3
"""
批量查询指定日期范围内每周指标，生成趋势图表 HTML。
全部使用标量 COUNT SQL，不依赖 limit_num，与周报口径一致。

用法示例：
  python3 generate_trend_chart.py                          # 默认近4周
  python3 generate_trend_chart.py --start 2026-01-01       # 指定起始日（到今天）
  python3 generate_trend_chart.py --start 2026-01-01 --end 2026-06-30
  python3 generate_trend_chart.py --recent-weeks 12        # 近12周（约3个月）
  python3 generate_trend_chart.py --recent-months 6        # 近6个月
"""

import argparse
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

CONFIG_PATH = ".cursor/skills/weekly-core-metrics/scripts/config.json"


# ── 日期范围计算 ───────────────────────────────────────────────

def week_label(monday: dt.date) -> str:
    """把一周的周一转为中文标签，如 '03月第4周'"""
    # 找本周属于哪个月（取周一和周日的月份，以周一为准）
    month = monday.month
    # 当月内的第几周：从当月第一个周一算起
    first_day = monday.replace(day=1)
    first_monday = first_day + dt.timedelta(days=(7 - first_day.weekday()) % 7)
    if first_monday > monday:
        first_monday -= dt.timedelta(days=7)
    week_num = (monday - first_monday).days // 7 + 1
    return f"{month:02d}月第{week_num}周"


def build_weeks(start: dt.date, end: dt.date) -> List[Tuple[str, dt.date, dt.date]]:
    """返回 start ~ end 范围内所有完整周（周一~周日）"""
    # 对齐到周一
    first_monday = start - dt.timedelta(days=start.weekday())
    if first_monday < start:
        first_monday += dt.timedelta(days=7)
    weeks = []
    cur = first_monday
    while cur <= end:
        sunday = cur + dt.timedelta(days=6)
        if sunday > end:
            sunday = end
        label = week_label(cur)
        weeks.append((label, cur, sunday))
        cur += dt.timedelta(days=7)
    return weeks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成核心模块指标趋势图表")
    parser.add_argument("--config", default=CONFIG_PATH)
    parser.add_argument("--start",  default="", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end",    default="", help="截止日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--recent-weeks",  type=int, default=0,
                        help="近 N 周（与 --start/--end 互斥，优先级低于 start）")
    parser.add_argument("--recent-months", type=int, default=0,
                        help="近 N 个月（与 --start/--end 互斥）")
    parser.add_argument("--output", default="", help="输出 HTML 路径，默认自动生成")
    return parser.parse_args()


def resolve_date_range(args: argparse.Namespace) -> Tuple[dt.date, dt.date, str]:
    """返回 (start_date, end_date, title_suffix)"""
    today = dt.date.today()
    end = dt.date.fromisoformat(args.end) if args.end else today

    if args.start:
        start = dt.date.fromisoformat(args.start)
        title = f"{start} ~ {end}"
    elif args.recent_months > 0:
        n = args.recent_months
        # 往前推 n 个月
        m = end.month - n
        y = end.year + m // 12
        m = m % 12
        if m <= 0:
            m += 12
            y -= 1
        start = end.replace(year=y, month=m, day=1)
        title = f"近{n}个月（{start} ~ {end}）"
    elif args.recent_weeks > 0:
        n = args.recent_weeks
        start = end - dt.timedelta(weeks=n) + dt.timedelta(days=1)
        title = f"近{n}周（{start} ~ {end}）"
    else:
        # 默认近4周
        start = end - dt.timedelta(weeks=4) + dt.timedelta(days=1)
        title = f"近4周（{start} ~ {end}）"

    return start, end, title


# ── 基础工具 ──────────────────────────────────────────────────

def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def d(date_obj: dt.date) -> str:
    return date_obj.strftime("%Y-%m-%d")


def post_sql(config: dict, instance: str, sql: str) -> dict:
    auth = config.get("auth", {})
    csrf, sid = auth.get("csrftoken", ""), auth.get("sessionid", "")
    data = {
        "instance_name": instance,
        "db_name": config["db_name"],
        "schema_name": config["schema_name"],
        "tb_name": config.get("tb_name", "dt_outsource_post"),
        "sql_content": sql,
        "limit_num": str(config.get("limit_num", 100)),
    }
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(config["archery_url"], data=encoded, method="POST")
    req.add_header("accept", "application/json, text/javascript, */*; q=0.01")
    req.add_header("content-type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("x-requested-with", "XMLHttpRequest")
    req.add_header("x-csrftoken", csrf)
    req.add_header("cookie", f"csrftoken={csrf}; sessionid={sid}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_scalar(payload: dict, key: str) -> float:
    try:
        data = payload.get("data", {})
        rows, cols = data.get("rows", []), data.get("column_list", [])
        if rows and cols:
            return float(rows[0][cols.index(key)])
    except Exception:
        pass
    return 0.0


def fetch_sum(config: dict, sql: str, keys: List[str]) -> Dict[str, float]:
    acc = {k: 0.0 for k in keys}
    for inst in config["instances"]:
        payload = post_sql(config, inst, sql)
        for k in keys:
            acc[k] += parse_scalar(payload, k)
    return acc


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


# ── SQL 定义 ──────────────────────────────────────────────────

def sql_out_counts(s: str, e: str) -> str:
    return f"""
WITH orders AS (
    SELECT DISTINCT org_id FROM dt_outsource_order
    WHERE DATE(created_at) BETWEEN DATE '{s}' AND DATE '{e}'
),
posts AS (
    SELECT DISTINCT org_id FROM dt_outsource_post
    WHERE DATE(created_at) BETWEEN DATE '{s}' AND DATE '{e}'
)
SELECT
    (SELECT COUNT(*) FROM orders) AS order_customers,
    (SELECT COUNT(*) FROM orders o JOIN posts p USING(org_id)) AS covered_customers;""".strip()


def sql_out_retention(ls: str, le: str, ts: str, te: str) -> str:
    return f"""
WITH lw_orders AS (SELECT DISTINCT org_id FROM dt_outsource_order WHERE DATE(created_at) BETWEEN DATE '{ls}' AND DATE '{le}'),
lw_posts  AS (SELECT DISTINCT org_id FROM dt_outsource_post    WHERE DATE(created_at) BETWEEN DATE '{ls}' AND DATE '{le}'),
lw_active AS (SELECT o.org_id FROM lw_orders o JOIN lw_posts p USING(org_id)),
tw_orders AS (SELECT DISTINCT org_id FROM dt_outsource_order WHERE DATE(created_at) BETWEEN DATE '{ts}' AND DATE '{te}'),
tw_posts  AS (SELECT DISTINCT org_id FROM dt_outsource_post    WHERE DATE(created_at) BETWEEN DATE '{ts}' AND DATE '{te}'),
tw_active AS (SELECT o.org_id FROM tw_orders o JOIN tw_posts p USING(org_id)),
retained  AS (SELECT l.org_id FROM lw_active l JOIN tw_active t ON l.org_id = t.org_id)
SELECT
    (SELECT COUNT(*) FROM lw_active) AS last_week_customers,
    (SELECT COUNT(*) FROM retained)  AS retained_customers;""".strip()


def sql_col_counts(s: str, e: str) -> str:
    return f"""
WITH base AS (
    SELECT org_id, DATE(created_at) AS act_date, associate_id
    FROM dt_collaborative_task
    WHERE DATE(created_at) BETWEEN DATE '{s}' AND DATE '{e}'
),
per_org AS (SELECT org_id, COUNT(DISTINCT act_date) AS active_days FROM base GROUP BY org_id)
SELECT
    (SELECT COUNT(*) FROM per_org WHERE active_days >= 1) AS task_customers,
    (SELECT COUNT(*) FROM per_org WHERE active_days >= 2) AS covered_customers,
    (SELECT COUNT(*) FROM base)                          AS total_tasks,
    (SELECT COUNT(*) FROM base WHERE associate_id IS NOT NULL) AS associated_tasks;""".strip()


def sql_col_retention(ls: str, le: str, ts: str, te: str) -> str:
    return f"""
WITH lw_base   AS (SELECT org_id, DATE(created_at) AS act_date FROM dt_collaborative_task WHERE DATE(created_at) BETWEEN DATE '{ls}' AND DATE '{le}'),
lw_active AS (SELECT org_id FROM lw_base GROUP BY org_id HAVING COUNT(DISTINCT act_date) >= 2),
tw_base   AS (SELECT org_id, DATE(created_at) AS act_date FROM dt_collaborative_task WHERE DATE(created_at) BETWEEN DATE '{ts}' AND DATE '{te}'),
tw_active AS (SELECT org_id FROM tw_base GROUP BY org_id HAVING COUNT(DISTINCT act_date) >= 2),
retained  AS (SELECT l.org_id FROM lw_active l JOIN tw_active t ON l.org_id = t.org_id)
SELECT
    (SELECT COUNT(*) FROM lw_active) AS last_week_customers,
    (SELECT COUNT(*) FROM retained)  AS retained_customers;""".strip()


# ── 主查询 ────────────────────────────────────────────────────

def query_all_weeks(config: dict, weeks: List[Tuple[str, dt.date, dt.date]]) -> List[dict]:
    rows = []
    prev_label = None
    prev_ws = prev_we = None

    for label, ws, we in weeks:
        s, e = d(ws), d(we)
        print(f"  [{label}] {s} ~ {e} ...", end=" ", flush=True)

        out = fetch_sum(config, sql_out_counts(s, e), ["order_customers", "covered_customers"])
        col = fetch_sum(config, sql_col_counts(s, e), ["task_customers", "covered_customers", "total_tasks", "associated_tasks"])

        if prev_ws is not None:
            ps, pe = d(prev_ws), d(prev_we)
            out_ret = fetch_sum(config, sql_out_retention(ps, pe, s, e), ["last_week_customers", "retained_customers"])
            col_ret = fetch_sum(config, sql_col_retention(ps, pe, s, e), ["last_week_customers", "retained_customers"])
            out_retain_rate = safe_div(out_ret["retained_customers"], out_ret["last_week_customers"])
            col_retain_rate = safe_div(col_ret["retained_customers"], col_ret["last_week_customers"])
        else:
            out_retain_rate = None
            col_retain_rate = None

        row = {
            "label":            label,
            "out_covered":      int(out["covered_customers"]),
            "out_orders":       int(out["order_customers"]),
            "out_convert":      safe_div(out["covered_customers"], out["order_customers"]),
            "out_retain":       out_retain_rate,
            "col_active":       int(col["covered_customers"]),
            "col_task":         int(col["task_customers"]),
            "col_convert":      safe_div(col["covered_customers"], col["task_customers"]),
            "col_retain":       col_retain_rate,
            "col_assoc":        safe_div(col["associated_tasks"], col["total_tasks"]),
        }
        rows.append(row)
        prev_label, prev_ws, prev_we = label, ws, we
        print(f"委外覆盖={row['out_covered']} 协同活跃={row['col_active']}")

    return rows


# ── 洞察文本生成 ───────────────────────────────────────────────

def trend_desc(vals: List[Optional[float]], week_labels: List[str], is_rate: bool = False) -> str:
    """根据多周数据生成洞察文字。"""
    non_null = [(i, v) for i, v in enumerate(vals) if v is not None]
    if len(non_null) < 2:
        return ""

    latest_i, latest = non_null[-1]
    prev_i, prev = non_null[-2]
    wow = (latest - prev) / prev * 100 if prev else 0
    wow_str = f"+{wow:.1f}%" if wow >= 0 else f"{wow:.1f}%"

    # 整体趋势：前两个有效值 vs 后两个有效值
    early_avg = sum(v for _, v in non_null[:2]) / 2
    late_avg  = sum(v for _, v in non_null[-2:]) / 2
    diff_pct  = (late_avg - early_avg) / early_avg * 100 if early_avg else 0
    if diff_pct > 5:
        trend = f"整体上升约 {diff_pct:.0f}%"
    elif diff_pct < -5:
        trend = f"整体下降约 {abs(diff_pct):.0f}%"
    else:
        trend = "整体相对平稳"

    fmt = (lambda v: f"{v*100:.1f}%") if is_rate else (lambda v: str(int(v)))
    return f"最新值 <b>{fmt(latest)}</b>（{week_labels[latest_i]}），环比 <b>{wow_str}</b>；{trend}。"


def retention_insight(vals: List[Optional[float]], week_labels: List[str]) -> str:
    non_null = [(i, v) for i, v in enumerate(vals) if v is not None]
    if not non_null:
        return ""
    max_i, max_v = max(non_null, key=lambda x: x[1])
    min_i, min_v = min(non_null, key=lambda x: x[1])
    latest_i, latest_v = non_null[-1]
    prev_v = non_null[-2][1] if len(non_null) >= 2 else None
    wow = f"（环比 {(latest_v - prev_v) / prev_v * 100:+.1f}%）" if prev_v else ""
    return (f"区间最高 <b>{max_v*100:.1f}%</b>（{week_labels[max_i]}），"
            f"最低 <b>{min_v*100:.1f}%</b>（{week_labels[min_i]}）；"
            f"最新值 <b>{latest_v*100:.1f}%</b>{wow}。")


# ── HTML 生成 ─────────────────────────────────────────────────

def js_arr(vals: List, is_rate: bool = False) -> str:
    items = []
    for v in vals:
        if v is None:
            items.append("null")
        elif is_rate:
            items.append(f"{v*100:.2f}")
        else:
            items.append(str(int(v)))
    return "[" + ", ".join(items) + "]"


def build_html(rows: List[dict], title_suffix: str = "") -> str:
    wlabels = [r["label"] for r in rows]
    labels  = json.dumps(wlabels, ensure_ascii=False)

    # 提取数据列
    out_covered  = [r["out_covered"]  for r in rows]
    out_orders   = [r["out_orders"]   for r in rows]
    out_convert  = [r["out_convert"]  for r in rows]
    out_retain   = [r["out_retain"]   for r in rows]
    col_active   = [r["col_active"]   for r in rows]
    col_task     = [r["col_task"]     for r in rows]
    col_convert  = [r["col_convert"]  for r in rows]
    col_retain   = [r["col_retain"]   for r in rows]
    col_assoc    = [r["col_assoc"]    for r in rows]

    # 洞察文本
    ins = {
        "out_covered":  trend_desc(out_covered, wlabels),
        "out_orders":   trend_desc(out_orders, wlabels),
        "out_convert":  trend_desc(out_convert, wlabels, True),
        "out_retain":   retention_insight(out_retain, wlabels),
        "col_active":   trend_desc(col_active, wlabels),
        "col_task":     trend_desc(col_task, wlabels),
        "col_convert":  trend_desc(col_convert, wlabels, True),
        "col_retain":   retention_insight(col_retain, wlabels),
        "col_assoc":    trend_desc(col_assoc, wlabels, True),
    }

    # 摘要卡片数据（最新一周）
    lw = rows[-1]
    prev = rows[-2]
    def wow_badge(cur, pre, is_rate=False):
        if cur is None or pre is None:
            return ""
        pct = (cur - pre) / pre * 100 if pre else 0
        cls = "up" if pct >= 0 else "down"
        sym = "▲" if pct >= 0 else "▼"
        return f'<span class="badge {cls}">{sym} {abs(pct):.1f}%</span>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>核心模块指标趋势 · {title_suffix}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f0f2f5;color:#222;padding:28px 32px}}
h1{{font-size:22px;font-weight:700;color:#111;margin-bottom:4px}}
.subtitle{{font-size:13px;color:#888;margin-bottom:28px}}

/* 摘要卡片行 */
.summary-row{{display:flex;gap:12px;margin-bottom:28px;flex-wrap:wrap}}
.kpi{{background:#fff;border-radius:10px;padding:14px 18px;flex:1;min-width:140px;
      box-shadow:0 1px 6px rgba(0,0,0,.07)}}
.kpi .title{{font-size:11px;color:#999;margin-bottom:4px}}
.kpi .val{{font-size:22px;font-weight:700;color:#111}}
.kpi .sub{{font-size:12px;color:#aaa;margin-top:2px}}
.badge{{font-size:11px;font-weight:600;padding:2px 6px;border-radius:4px;margin-left:6px}}
.badge.up{{background:#e6f9f0;color:#10a060}}
.badge.down{{background:#fff0f0;color:#e04040}}

/* 分区 */
.section{{margin-bottom:36px}}
.section-title{{font-size:17px;font-weight:700;color:#fff;
                background:linear-gradient(90deg,#4361ee,#7b8cde);
                padding:10px 20px;border-radius:10px;margin-bottom:20px}}
.section-title.green{{background:linear-gradient(90deg,#2d9d78,#5dc8a0)}}

/* 图表网格 */
.chart-grid{{display:grid;gap:20px;grid-template-columns:1fr 1fr}}
.chart-grid.three{{grid-template-columns:1fr 1fr 1fr}}
.chart-card{{background:#fff;border-radius:12px;padding:22px 24px 18px;
             box-shadow:0 1px 8px rgba(0,0,0,.07)}}
.chart-card h3{{font-size:14px;font-weight:600;color:#444;margin-bottom:14px}}
canvas{{width:100%!important}}
.insight{{margin-top:12px;font-size:12.5px;color:#555;line-height:1.6;
          background:#f8f9fd;border-left:3px solid #4361ee;padding:8px 12px;border-radius:0 6px 6px 0}}
.insight.green{{border-left-color:#2d9d78}}

@media(max-width:900px){{
  .chart-grid,.chart-grid.three{{grid-template-columns:1fr}}
  .summary-row{{flex-direction:column}}
}}
</style>
</head>
<body>

<h1>核心模块指标趋势</h1>
<p class="subtitle">统计周期：{title_suffix}&nbsp;·&nbsp;共 {len(rows)} 周&nbsp;·&nbsp;最新数据周：{rows[-1]['label']}</p>

<!-- 摘要卡片 -->
<div class="summary-row">
  <div class="kpi">
    <div class="title">委外覆盖客户（最新周）</div>
    <div class="val">{lw['out_covered']}{wow_badge(lw['out_covered'], prev['out_covered'])}</div>
    <div class="sub">上周 {prev['out_covered']}</div>
  </div>
  <div class="kpi">
    <div class="title">委外客户留存率</div>
    <div class="val">{f"{lw['out_retain']*100:.1f}%" if lw['out_retain'] is not None else "-"}{wow_badge(lw['out_retain'], prev['out_retain'], True)}</div>
    <div class="sub">上周 {f"{prev['out_retain']*100:.1f}%" if prev['out_retain'] is not None else "-"}</div>
  </div>
  <div class="kpi">
    <div class="title">委外订单→收发货转化率</div>
    <div class="val">{lw['out_convert']*100:.1f}%{wow_badge(lw['out_convert'], prev['out_convert'], True)}</div>
    <div class="sub">上周 {prev['out_convert']*100:.1f}%</div>
  </div>
  <div class="kpi" style="border-left:3px solid #2d9d78">
    <div class="title">协同活跃客户（最新周）</div>
    <div class="val">{lw['col_active']}{wow_badge(lw['col_active'], prev['col_active'])}</div>
    <div class="sub">上周 {prev['col_active']}</div>
  </div>
  <div class="kpi" style="border-left:3px solid #2d9d78">
    <div class="title">协同客户留存率</div>
    <div class="val">{f"{lw['col_retain']*100:.1f}%" if lw['col_retain'] is not None else "-"}{wow_badge(lw['col_retain'], prev['col_retain'], True)}</div>
    <div class="sub">上周 {f"{prev['col_retain']*100:.1f}%" if prev['col_retain'] is not None else "-"}</div>
  </div>
  <div class="kpi" style="border-left:3px solid #2d9d78">
    <div class="title">协同活跃客户转换率</div>
    <div class="val">{lw['col_convert']*100:.1f}%{wow_badge(lw['col_convert'], prev['col_convert'], True)}</div>
    <div class="sub">上周 {prev['col_convert']*100:.1f}%</div>
  </div>
</div>

<!-- 委外管理 -->
<div class="section">
  <div class="section-title">📦 委外管理</div>
  <div class="chart-grid three">

    <div class="chart-card">
      <h3>客户规模趋势（人数）</h3>
      <canvas id="c_out_scale"></canvas>
      <div class="insight">{ins['out_covered']} 订单客户：{ins['out_orders']}</div>
    </div>

    <div class="chart-card">
      <h3>客户留存率趋势（%）<small style="color:#aaa;font-weight:400"> · 上周活跃→本周仍活跃</small></h3>
      <canvas id="c_out_retain"></canvas>
      <div class="insight">{ins['out_retain']}</div>
    </div>

    <div class="chart-card">
      <h3>订单 → 收发货转化率（%）</h3>
      <canvas id="c_out_convert"></canvas>
      <div class="insight">{ins['out_convert']}</div>
    </div>

  </div>
</div>

<!-- 协同任务 -->
<div class="section">
  <div class="section-title green">🤝 协同任务</div>
  <div class="chart-grid three">

    <div class="chart-card">
      <h3>客户规模趋势（人数）</h3>
      <canvas id="c_col_scale"></canvas>
      <div class="insight green">{ins['col_active']} 创建任务客户：{ins['col_task']}</div>
    </div>

    <div class="chart-card">
      <h3>客户留存率趋势（%）<small style="color:#aaa;font-weight:400"> · 上周活跃→本周仍活跃</small></h3>
      <canvas id="c_col_retain"></canvas>
      <div class="insight green">{ins['col_retain']}</div>
    </div>

    <div class="chart-card">
      <h3>活跃转换率 & 工单关联比例（%）</h3>
      <canvas id="c_col_rate"></canvas>
      <div class="insight green">活跃转换率：{ins['col_convert']} 工单关联：{ins['col_assoc']}</div>
    </div>

  </div>
</div>

<p style="font-size:11px;color:#bbb;margin-top:8px">
  * 覆盖客户 = 既有订单又有收发记录；协同活跃客户 = 一周内≥2天创建任务；留存率第1周无上周基准显示为空。<br>
  * 数据来源：Archery / 小工单生产库（ADB_01/02/03 三实例加总）
</p>

<script>
const labels = {labels};

// 颜色
const BLUE   = '#4361ee';
const LBLUE  = '#7b8cde';
const GREEN  = '#2d9d78';
const LGREEN = '#5dc8a0';
const ORANGE = '#f77f00';

function mkLine(label, data, color, dash=[]) {{
  return {{
    label, data,
    borderColor: color, backgroundColor: color+'22',
    pointBackgroundColor: color, pointRadius: 5, pointHoverRadius: 7,
    borderWidth: 2.5, borderDash: dash, tension: 0.35, fill: false, spanGaps: true,
  }};
}}

const baseOpts = (yLabel) => ({{
  responsive: true,
  interaction: {{ mode:'index', intersect:false }},
  plugins: {{
    legend: {{ position:'top', labels:{{ font:{{size:12}}, padding:14 }} }},
    tooltip: {{ padding:10, cornerRadius:8 }},
  }},
  scales: {{
    x: {{ grid:{{color:'#f2f2f2'}}, ticks:{{font:{{size:12}}}} }},
    y: {{ grid:{{color:'#f2f2f2'}}, ticks:{{font:{{size:12}}}}, title:{{display:!!yLabel,text:yLabel}}, beginAtZero:false }},
  }},
}});

const pctOpts = (yLabel) => {{
  const o = baseOpts(yLabel);
  o.scales.y.min = 0; o.scales.y.max = 100;
  o.scales.y.ticks.callback = v => v + '%';
  o.plugins.tooltip.callbacks = {{ label: ctx => ctx.dataset.label+': '+(ctx.parsed.y??'-')+'%' }};
  return o;
}};

// 委外规模
new Chart(document.getElementById('c_out_scale'), {{
  type:'line', data:{{ labels,
    datasets:[
      mkLine('覆盖客户数（订单+收发）', {js_arr(out_covered)}, BLUE),
      mkLine('委外订单客户数',          {js_arr(out_orders)}, LBLUE, [6,3]),
    ]
  }}, options: baseOpts('人数'),
}});

// 委外留存率
new Chart(document.getElementById('c_out_retain'), {{
  type:'line', data:{{ labels,
    datasets:[
      mkLine('委外客户留存率', {js_arr(out_retain, True)}, BLUE),
    ]
  }}, options: pctOpts('%'),
}});

// 委外转化率
new Chart(document.getElementById('c_out_convert'), {{
  type:'line', data:{{ labels,
    datasets:[
      mkLine('订单→收发货转化率', {js_arr(out_convert, True)}, BLUE),
    ]
  }}, options: pctOpts('%'),
}});

// 协同规模
new Chart(document.getElementById('c_col_scale'), {{
  type:'line', data:{{ labels,
    datasets:[
      mkLine('活跃客户数（≥2天任务）', {js_arr(col_active)}, GREEN),
      mkLine('创建任务客户数（≥1天）', {js_arr(col_task)},   LGREEN, [6,3]),
    ]
  }}, options: baseOpts('人数'),
}});

// 协同留存率
new Chart(document.getElementById('c_col_retain'), {{
  type:'line', data:{{ labels,
    datasets:[
      mkLine('协同客户留存率', {js_arr(col_retain, True)}, GREEN),
    ]
  }}, options: pctOpts('%'),
}});

// 协同转换率 & 工单关联
new Chart(document.getElementById('c_col_rate'), {{
  type:'line', data:{{ labels,
    datasets:[
      mkLine('活跃客户转换率（2天/全体）', {js_arr(col_convert, True)}, GREEN),
      mkLine('工单关联创建比例',           {js_arr(col_assoc, True)},   ORANGE, [4,3]),
    ]
  }}, options: pctOpts('%'),
}});
</script>
</body>
</html>"""
    return html


# ── 入口 ──────────────────────────────────────────────────────

def main():
    args = parse_args()
    start, end, title_suffix = resolve_date_range(args)
    config = load_config(args.config)

    weeks = build_weeks(start, end)
    if not weeks:
        print(f"❌ 日期范围 {start} ~ {end} 内没有完整的周，请调整参数。")
        return

    print(f"统计范围：{title_suffix}，共 {len(weeks)} 周\n")
    rows = query_all_weeks(config, weeks)

    # 自动生成输出路径
    if args.output:
        output_path = args.output
    else:
        os.makedirs("周报", exist_ok=True)
        safe_title = title_suffix.replace(" ", "").replace("~", "-").replace("（", "_").replace("）", "")
        output_path = f"周报/趋势图表-{safe_title[:30]}.html"

    print(f"\n生成 HTML 图表...")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(build_html(rows, title_suffix))
    print(f"✓ 已生成：{output_path}")

    # 打印汇总表
    print(f"\n{'周次':<10} {'委外覆盖':>8} {'委外订单':>8} {'委外留存':>9} {'委外转化':>9}"
          f" {'协同活跃':>8} {'协同创建':>8} {'协同留存':>9} {'协同转换':>9} {'工单关联':>9}")
    for r in rows:
        rr = lambda v: f"{v*100:.1f}%" if v is not None else "   -"
        print(f"{r['label']:<10} {r['out_covered']:>8} {r['out_orders']:>8}"
              f" {rr(r['out_retain']):>9} {rr(r['out_convert']):>9}"
              f" {r['col_active']:>8} {r['col_task']:>8}"
              f" {rr(r['col_retain']):>9} {rr(r['col_convert']):>9} {rr(r['col_assoc']):>9}")


if __name__ == "__main__":
    main()

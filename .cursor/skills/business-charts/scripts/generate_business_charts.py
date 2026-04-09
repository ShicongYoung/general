#!/usr/bin/env python3
"""
通用业务图表生成器（配置驱动）。

技能说明见：.cursor/skills/business-charts/SKILL.md（取数口径优先对齐 query-business-metrics）。

- HTML 样式由 templates/chart-report-light.css 等模板提供
- 数据源通过 Archery：StarRocks（trace_log_dp）与 ADB 分片（01/02/03）
- 输出到「图表/」，可选写入「查询指标/」一份 md 索引

配置示例：chart-config.example.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_CONFIG_PATH = ".cursor/skills/weekly-core-metrics/scripts/config.json"


def repo_root() -> Path:
    root = Path(__file__).resolve()
    for anc in root.parents:
        if (anc / "查询指标").is_dir():
            return anc
    return Path.cwd()


ROOT = repo_root()
CHART_REPORT_CSS = ROOT / ".cursor/skills/business-charts/templates/chart-report-light.css"

# 与 templates/chart-report-light.css 中 section-title / insight / chart-card.tone-* 一致
THEME_SECTION_CLASS: Dict[str, str] = {
    "blue": "",
    "green": "green",
    "purple": "purple",
    "orange": "orange",
    "teal": "teal",
    "coral": "coral",
    "rose": "rose",
    "slate": "slate",
    "indigo": "indigo",
    "amber": "amber",
    "mint": "mint",
    "crimson": "crimson",
}

THEME_PALETTE: Dict[str, Tuple[str, str, str]] = {
    "blue": ("#4361ee", "#7b8cde", "#f77f00"),
    "green": ("#2d9d78", "#5dc8a0", "#f59e0b"),
    "purple": ("#6f58ff", "#a08cff", "#14b8a6"),
    "orange": ("#ea580c", "#fbbf24", "#6366f1"),
    "teal": ("#0e7490", "#2dd4bf", "#e11d48"),
    "coral": ("#e85d75", "#f4a261", "#0891b2"),
    "rose": ("#be185d", "#f472b6", "#4f46e5"),
    "slate": ("#334155", "#94a3b8", "#d97706"),
    "indigo": ("#4338ca", "#818cf8", "#db2777"),
    "amber": ("#b45309", "#fbbf24", "#059669"),
    "mint": ("#047857", "#34d399", "#7c3aed"),
    "crimson": ("#9f1239", "#fb7185", "#2563eb"),
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def post_sql(cfg: dict, instance_name: str, tb_name: str, sql: str, limit: str = "8000", timeout: int = 180) -> dict:
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
    req.add_header("accept", "application/json, text/javascript, */*; q=0.01")
    req.add_header("content-type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("x-requested-with", "XMLHttpRequest")
    req.add_header("x-csrftoken", csrf)
    req.add_header("cookie", f"csrftoken={csrf}; sessionid={sid}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rows(payload: dict) -> Tuple[List[str], List[list]]:
    d = payload.get("data") or {}
    return d.get("column_list") or [], d.get("rows") or []


def scalar(payload: dict, key: str) -> float:
    cols, rs = rows(payload)
    if not cols or not rs:
        return 0.0
    try:
        v = rs[0][cols.index(key)]
        return float(v or 0)
    except Exception:
        return 0.0


def safe_filename(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", "-", s)
    s = re.sub(r"\\s+", "_", s).strip("_")
    return s[:120] or "chart"


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    start: dt.date
    end: dt.date


def build_month_periods(start: str, end: str) -> List[Period]:
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    cur = dt.date(s.year, s.month, 1)
    out: List[Period] = []
    while cur <= e:
        ny, nm = (cur.year + (cur.month // 12), (cur.month % 12) + 1)
        nxt = dt.date(ny, nm, 1)
        last = nxt - dt.timedelta(days=1)
        ps = cur if cur >= s else s
        pe = last if last <= e else e
        key = f"{cur.year}-{cur.month:02d}"
        label = f"{str(cur.year)[2:4]}/{cur.month:02d}"
        out.append(Period(key=key, label=label, start=ps, end=pe))
        cur = nxt
    return out


def build_week_periods(start: str, end: str, week_start: int = 0) -> List[Period]:
    """
    week_start: 0=周一..6=周日
    """
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    delta = (s.weekday() - week_start) % 7
    cur = s - dt.timedelta(days=delta)
    if cur < s:
        cur += dt.timedelta(days=7)
    out: List[Period] = []
    while cur <= e:
        ws = cur
        we = min(cur + dt.timedelta(days=6), e)
        key = ws.isoformat()
        label = f"{ws.strftime('%m') }月第{((ws.day - 1)//7)+1}周"
        out.append(Period(key=key, label=label, start=ws, end=we))
        cur += dt.timedelta(days=7)
    return out


def render_sql(template: str, p: Period) -> str:
    return (
        template.replace("{{start}}", p.start.isoformat())
        .replace("{{end}}", p.end.isoformat())
        .replace("{{period_key}}", p.key)
    )


def fetch_series(cfg: dict, series_def: dict, periods: Sequence[Period]) -> List[Optional[float]]:
    """
    series_def:
      - name: str
      - source: { kind: "starrocks"|"adb", instance/tb/instances? }
      - sql: sql template (must return scalar with alias key)
      - key: scalar alias name
      - null_when_zero: bool (optional)
    """
    src = series_def["source"]
    kind = src["kind"]
    tb = src.get("tb_name") or ("trace_log_dp" if kind == "starrocks" else "")
    key = series_def["key"]

    vals: List[Optional[float]] = []
    for p in periods:
        sql = render_sql(series_def["sql"], p)
        if kind == "starrocks":
            inst = src.get("instance_name", "小工单_阿里云_prod_starrocks")
            payload = post_sql(cfg, inst, tb, sql, limit="100")
            if payload.get("status") != 0:
                raise RuntimeError(payload.get("msg"))
            v = scalar(payload, key)
        elif kind == "adb":
            # 默认按分片求和（用于标量）；若要并集去重请在 SQL 内实现或改为 union 模式（后续可扩展）
            insts = src.get("instances") or cfg.get("instances") or []
            v = 0.0
            for inst in insts:
                payload = post_sql(cfg, inst, tb, sql, limit="100")
                if payload.get("status") != 0:
                    raise RuntimeError(f"{inst}: {payload.get('msg')}")
                v += scalar(payload, key)
        else:
            raise ValueError(f"unknown source kind: {kind}")

        if series_def.get("null_when_zero") and (v == 0):
            vals.append(None)
        else:
            vals.append(v)
    return vals


def insight_peak_trend(vals: Sequence[Optional[float]], labels: Sequence[str], fmt: str) -> str:
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if not pts:
        return "区间内无数据。"
    mx_i, mx_v = max(pts, key=lambda x: x[1])
    mn_i, mn_v = min(pts, key=lambda x: x[1])
    last_i, last_v = pts[-1]
    if fmt == "pct":
        f = lambda x: f"{x*100:.1f}%"
    elif fmt == "float1":
        f = lambda x: f"{x:.1f}"
    else:
        f = lambda x: str(int(round(x)))
    return f"峰值 <b>{f(mx_v)}</b>（{labels[mx_i]}），低谷 <b>{f(mn_v)}</b>（{labels[mn_i]}）；末期 <b>{f(last_v)}</b>。"


def js_arr(vals: Sequence[Optional[float]], kind: str) -> str:
    out: List[str] = []
    for v in vals:
        if v is None:
            out.append("null")
        elif kind == "pct":
            out.append(f"{v*100:.2f}")
        elif kind == "int":
            out.append(str(int(round(v))))
        else:
            out.append(f"{v:.2f}")
    return "[" + ", ".join(out) + "]"


def build_html(report: dict, periods: Sequence[Period], computed: dict) -> str:
    """
    report:
      - title, subtitle
      - sections: [{title, theme, charts:[...]}]
    computed:
      - chartId -> { labels, datasets, insightHtml }
    """
    labels = json.dumps([p.label for p in periods], ensure_ascii=False)
    css_text = (
        CHART_REPORT_CSS.read_text(encoding="utf-8")
        if CHART_REPORT_CSS.is_file()
        else "/* missing .cursor/skills/business-charts/templates/chart-report-light.css */"
    )

    sections_html = ""
    for sec in report["sections"]:
        theme = sec.get("theme", "blue")
        cls = THEME_SECTION_CLASS.get(theme, "")
        tone_theme = theme if theme in THEME_PALETTE else "blue"
        grid = sec.get("grid", "three")
        sections_html += f"""
<div class="section">
  <div class="section-title {cls}">{sec['title']}</div>
  <div class="chart-grid {grid}">
"""
        for ch in sec["charts"]:
            cid = ch["id"]
            ins_cls = THEME_SECTION_CLASS.get(theme, "")
            sections_html += f"""
    <div class="chart-card tone-{tone_theme}">
      <h3>{ch['title']}</h3>
      <div class="chart-body">
        <canvas id="{cid}"></canvas>
      </div>
      <div class="insight {ins_cls}">{computed[cid]['insightHtml']}</div>
    </div>
"""
        sections_html += """
  </div>
</div>
"""

    charts_js = ""
    for sec in report["sections"]:
        theme = sec.get("theme", "blue")
        palette = THEME_PALETTE.get(theme, THEME_PALETTE["blue"])
        for ch in sec["charts"]:
            cfg = computed[ch["id"]]
            charts_js += cfg["chartJs"].replace("{{C1}}", palette[0]).replace("{{C2}}", palette[1]).replace("{{C3}}", palette[2])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{report['title']}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
{css_text}
</style>
</head>
<body>
<h1>{report['title']}</h1>
<p class="subtitle">{report.get('subtitle','')}</p>
{sections_html}
<script>
const labels = {labels};
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
    x: {{ grid:{{ color:'rgba(15,23,42,0.06)' }}, ticks:{{font:{{size:12}}}} }},
    y: {{
      grid:{{ color:'rgba(15,23,42,0.06)' }},
      ticks:{{ font:{{size:12}}, padding: 6 }},
      title:{{ display:!!yLabel, text:yLabel }},
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
    x: {{ grid:{{ color:'rgba(15,23,42,0.06)' }}, ticks:{{font:{{size:12}}}} }},
    y: {{
      position:'left', beginAtZero:true, grace:'8%',
      title:{{display:true,text:yLeft}}, grid:{{color:'rgba(15,23,42,0.06)'}},
      ticks:{{ font:{{size:12}}, padding: 6 }},
    }},
    y1: {{
      position:'right', beginAtZero:true, grace:'8%',
      title:{{display:true,text:yRight}}, grid:{{drawOnChartArea:false}},
      ticks:{{ font:{{size:12}}, padding: 6 }},
    }},
  }},
}});

{charts_js}
</script>
</body>
</html>"""


def compile_chart(chart: dict, periods: Sequence[Period], series_data: Dict[str, List[Optional[float]]]) -> dict:
    """
    chart:
      - id, title
      - kind: line|bar|dual_bar_line|pct_line
      - datasets: [{series, label, axis?}]
      - insight: { type: peak_trend, fmt: int|pct|float1, series: name }
    """
    kind = chart["kind"]
    ds_defs = chart["datasets"]
    datasets_js = []
    for i, ds in enumerate(ds_defs):
        sname = ds["series"]
        vals = series_data[sname]
        color = "{{C1}}" if i == 0 else ("{{C2}}" if i == 1 else "{{C3}}")
        if kind == "dual_bar_line" and i == 0:
            datasets_js.append(f"mkBar('{ds['label']}', {js_arr(vals, ds.get('value_kind','int'))}, '{color}')")
        elif kind in ("bar",):
            datasets_js.append(f"mkBar('{ds['label']}', {js_arr(vals, ds.get('value_kind','int'))}, '{color}')")
        else:
            dash = "[6,3]" if i == 1 else "[]"
            axis = ds.get("axis", "y")
            datasets_js.append(f"{{...mkLine('{ds['label']}', {js_arr(vals, ds.get('value_kind','int'))}, '{color}', {dash}), yAxisID:'{axis}'}}")

    if kind == "dual_bar_line":
        opt = "dualOpts('左轴','右轴')"
        chart_js = f"""
new Chart(document.getElementById('{chart['id']}'), {{
  type: 'bar',
  data: {{ labels, datasets:[{", ".join(datasets_js)}] }},
  options: {opt}
}});
""".strip()
    elif kind == "pct_line":
        chart_js = f"""
new Chart(document.getElementById('{chart['id']}'), {{
  type:'line',
  data: {{ labels, datasets:[{", ".join(datasets_js)}] }},
  options: pctOpts('%')
}});
""".strip()
    else:
        chart_js = f"""
new Chart(document.getElementById('{chart['id']}'), {{
  type:'line',
  data: {{ labels, datasets:[{", ".join(datasets_js)}] }},
  options: baseOpts('{chart.get('y_label','')}')
}});
""".strip()

    ins = chart.get("insight") or {}
    if ins.get("type") == "peak_trend":
        sname = ins["series"]
        fmt = ins.get("fmt", "int")
        insight = insight_peak_trend(series_data[sname], [p.label for p in periods], fmt)
    else:
        insight = chart.get("insight_text", "")

    return {"chartJs": chart_js, "insightHtml": insight}


def main() -> None:
    ap = argparse.ArgumentParser(description="通用业务图表生成器（配置驱动）")
    ap.add_argument("--archery-config", default=DEFAULT_CONFIG_PATH)
    ap.add_argument("--config", required=True, help="图表配置 JSON 路径（相对仓库根）")
    ap.add_argument("--offline", action="store_true", help="不请求 Archery，使用 config.cache_file 生成 HTML")
    args = ap.parse_args()

    arch_cfg = load_json(ROOT / args.archery_config)
    conf_path = ROOT / args.config
    conf = load_json(conf_path)

    out_dir = ROOT / (conf.get("output_dir") or "图表")
    out_dir.mkdir(parents=True, exist_ok=True)

    gran = conf["periods"]["kind"]
    p_start, p_end = conf["periods"]["start"], conf["periods"]["end"]
    periods = build_month_periods(p_start, p_end) if gran == "month" else build_week_periods(p_start, p_end, conf["periods"].get("week_start", 0))

    raw_cache = conf.get("cache_file") or "_chart_cache.json"
    cr_path = Path(raw_cache)
    if cr_path.is_absolute():
        cache_file = cr_path
    elif cr_path.parts and cr_path.parts[0] == ".cursor":
        cache_file = ROOT.joinpath(*cr_path.parts)
    else:
        cache_file = out_dir / cr_path

    if args.offline:
        payload = load_json(cache_file)
        series_data = payload["series_data"]
    else:
        series_data: Dict[str, List[Optional[float]]] = {}
        for s in conf["series"]:
            name = s["name"]
            series_data[name] = fetch_series(arch_cfg, s, periods)
        cache_file.write_text(json.dumps({"series_data": series_data}, ensure_ascii=False, indent=2), encoding="utf-8")

    computed: Dict[str, dict] = {}
    for sec in conf["report"]["sections"]:
        for ch in sec["charts"]:
            computed[ch["id"]] = compile_chart(ch, periods, series_data)

    html = build_html(conf["report"], periods, computed)
    out_html = out_dir / (conf["report"].get("output_html") or f"{safe_filename(conf['report']['title'])}.html")
    out_html.write_text(html, encoding="utf-8")
    print(f"Wrote {out_html}")

    # 可选 md 索引
    md_path = conf.get("write_md_to")
    if md_path:
        md_file = ROOT / md_path
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text(
            f"# {conf['report']['title']}\n\n"
            f"- 图表：../{out_html.relative_to(ROOT)}\n"
            f"- 配置：{conf_path.relative_to(ROOT)}\n"
            f"- 缓存：../{cache_file.relative_to(ROOT)}\n",
            encoding="utf-8",
        )
        print(f"Wrote {md_file}")


if __name__ == "__main__":
    main()


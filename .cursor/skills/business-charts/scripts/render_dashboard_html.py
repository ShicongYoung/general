#!/usr/bin/env python3
"""
【第 2 段 / 渲染】通用业务看板 HTML 生成器。

- 输入：`--data` JSON（由 query-business-metrics 导出）+ `--manifest` 看板声明（图表类型、标题、业务导语）。
- 不访问 Archery；图表类型与配色由 manifest + 本脚本内主题色板共同决定。
- 每个图下方：`insight_lead`（业务角度说明）+ 自动统计句（峰谷、末月、近三月）。

示例：
  python3 render_dashboard_html.py \\
    --data ../cache/example_dashboard_data.json \\
    --manifest ../manifests/example_dashboard.manifest.json \\
    --output ../../图表/业务图表_manifest示例.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

THEME_PALETTE: Dict[str, Tuple[str, str, str]] = {
    "teal": ("#0f766e", "#2dd4bf", "#0ea5e9"),
    "blue": ("#4361ee", "#7b8cde", "#f97316"),
    "green": ("#15803d", "#4ade80", "#ca8a04"),
    "purple": ("#6d28d9", "#a78bfa", "#e11d48"),
    "orange": ("#c2410c", "#fb923c", "#0d9488"),
    "indigo": ("#4338ca", "#818cf8", "#db2777"),
    "crimson": ("#9f1239", "#fb7185", "#0369a1"),
}


def _repo_root() -> Path:
    p = Path(__file__).resolve().parent
    for _ in range(14):
        if (p / "查询指标").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    raise RuntimeError("找不到仓库根")


ROOT = _repo_root()
SKILL_BC = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_BC / "templates"
VENDOR_CHART = SKILL_BC / "vendor" / "chart.umd.min.js"


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def resolve_series(data: dict, bind: str) -> List[Optional[float]]:
    months: Sequence[str] = data.get("months") or sorted(
        set(data.get("custom", {}).keys()) | set(data.get("multi", {}).keys())
    )
    if bind == "_derived.collab_tasks_per_act":
        out: List[Optional[float]] = []
        for m in months:
            c = data.get("collab", {}).get(m) or {}
            act = c.get("act") or 0
            tasks = c.get("tasks") or 0
            out.append((float(tasks) / float(act)) if act else 0.0)
        return out
    parts = bind.split(".", 1)
    if len(parts) != 2:
        raise ValueError(f"bind 需为 module.field：{bind}")
    mod, field = parts
    blob = data.get(mod) or {}
    xs: List[Optional[float]] = []
    for m in months:
        row = blob.get(m)
        if row is None:
            xs.append(None)
            continue
        v = row.get(field)
        if v is None and field == "pv_per_act" and "pv_per_cov" in row:
            v = row.get("pv_per_cov")
        xs.append(float(v) if isinstance(v, (int, float)) else None)
    return xs


def fmt_int(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return str(int(round(v)))


def fmt_pct_ratio(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"{v * 100:.1f}%"


def wow(cur: Optional[float], pre: Optional[float]) -> Optional[float]:
    if cur is None or pre is None or pre == 0:
        return None
    return (cur - pre) / pre


def auto_stats_sentence(
    values: List[Optional[float]],
    labels: List[str],
    fmt: str,
) -> str:
    pts = [(i, v) for i, v in enumerate(values) if v is not None and isinstance(v, (int, float))]
    if not pts or all(v == 0 for _, v in pts):
        return "本期窗口内该序列以零或缺失为主，多与埋点保留周期、模块上线节奏有关。"
    nonzero = [(i, v) for i, v in pts if v != 0]
    mx_i, mx_v = max(nonzero or pts, key=lambda x: x[1])
    mn_i, mn_v = min(nonzero or pts, key=lambda x: x[1])
    _, last_v = pts[-1]
    tail = ""
    if len(pts) >= 3:
        a, b, c = pts[-3][1], pts[-2][1], pts[-1][1]
        if a and abs((c - a) / a) >= 0.1:
            tail = f"近三月{'上扬' if c > a else '回落'}约 {abs((c-a)/a)*100:.0f}%。"
    if fmt in ("ratio", "pct", "ratio_chart_pct"):
        return (
            f"峰值 **{fmt_pct_ratio(mx_v)}**（{labels[mx_i]}），低谷 **{fmt_pct_ratio(mn_v)}**（{labels[mn_i]}）；"
            f"{tail}末月 **{fmt_pct_ratio(last_v)}**。"
        )
    if fmt == "float2":
        return (
            f"峰值 **{mx_v:.2f}**（{labels[mx_i]}），低谷 **{mn_v:.2f}**（{labels[mn_i]}）；"
            f"{tail}末月 **{last_v:.2f}**。"
        )
    return (
        f"峰值 **{fmt_int(mx_v)}**（{labels[mx_i]}），低谷 **{fmt_int(mn_v)}**（{labels[mn_i]}）；"
        f"{tail}末月 **{fmt_int(last_v)}**。"
    )


def kpi_badge(cur: Optional[float], pre: Optional[float]) -> str:
    """A 股常用：上升红色，下降绿色（仅 KPI 区使用 .summary-row .badge）。"""
    w = wow(cur, pre)
    if w is None:
        return ""
    cls = "up" if w >= 0 else "down"
    sym = "▲" if w >= 0 else "▼"
    return f'<span class="badge {cls}">{sym} {abs(w) * 100:.1f}%</span>'


def js_array(vals: List[Optional[float]], *, mode: str, digits: int = 2) -> str:
    out: List[str] = []
    for v in vals:
        if v is None:
            out.append("null")
        elif mode == "ratio_chart_pct":
            out.append(f"{float(v) * 100:.{digits}f}")
        elif mode == "ratio":
            out.append(f"{float(v) * 100:.{digits}f}")
        elif mode == "float2":
            out.append(f"{float(v):.{digits}f}")
        elif mode == "int":
            out.append(str(int(round(float(v)))))
        else:
            out.append(f"{float(v):.{digits}f}")
    return "[" + ", ".join(out) + "]"


def role_color(theme: str, role: str, idx: int) -> str:
    pal = THEME_PALETTE.get(theme, THEME_PALETTE["blue"])
    if role == "contrast":
        return "#475569"
    if role == "secondary":
        return pal[1]
    if role == "tertiary":
        return pal[2]
    return pal[idx % 3]


def section_title_class(theme: str) -> str:
    m = {
        "blue": "",
        "green": "green",
        "purple": "purple",
        "orange": "orange",
        "teal": "teal",
        "indigo": "indigo",
        "crimson": "crimson",
    }
    return m.get(theme, "")


def insight_class(theme: str) -> str:
    return section_title_class(theme)


def grid_class(g: str) -> str:
    g = (g or "").strip().lower()
    if g == "three":
        return "chart-grid three"
    if g in ("one", "1", "single"):
        return "chart-grid one"
    return "chart-grid"


def build_html(data: dict, manifest: dict) -> str:
    months = data.get("months") or []
    labels_list: List[str] = list(data.get("labels") or [])
    if not labels_list and months:
        labels_list = [f"{m[2:4]}/{m[5:]}" for m in months]
    labels_js = json.dumps(labels_list, ensure_ascii=False)

    sheet = manifest.get("stylesheet") or "chart-report-light.css"
    css_path = TEMPLATES / sheet
    if not css_path.is_file():
        css_path = TEMPLATES / "chart-report-light.css"
    report_css = css_path.read_text(encoding="utf-8")

    page = manifest.get("page") or {}
    title = page.get("title") or "业务看板"
    sub_lines = page.get("subtitle_lines") or []
    subtitle_html = "<br>\n".join(sub_lines)

    last_i, prev_i = len(months) - 1, len(months) - 2

    # KPI
    kpi_html = '<div class="summary-row">\n'
    for k in manifest.get("kpi") or []:
        ser = resolve_series(data, k["bind"])
        fmt = k.get("format") or "int"
        cur = ser[last_i] if ser else None
        pre = ser[prev_i] if ser and prev_i >= 0 else None
        if fmt == "pct":
            val_s = fmt_pct_ratio(float(cur)) if cur is not None else "-"
            sub_s = fmt_pct_ratio(float(pre)) if pre is not None else "-"
            bdg = kpi_badge(cur, pre)
        else:
            val_s = fmt_int(float(cur)) if cur is not None else "-"
            sub_s = fmt_int(float(pre)) if pre is not None else "-"
            bdg = kpi_badge(cur, pre)
        kpi_html += f"""  <div class="kpi">
    <div class="title">{k["title"]}</div>
    <div class="val">{val_s}{bdg}</div>
    <div class="sub">上月 {sub_s}</div>
  </div>
"""
    kpi_html += "</div>\n"

    sections_blocks: List[str] = []
    chart_js_blocks: List[str] = []

    for sec in manifest.get("sections") or []:
        theme = sec.get("theme") or "blue"
        st_cls = section_title_class(theme)
        ins_cls = insight_class(theme)

        sec_html = f'<div class="section">\n  <div class="section-title {st_cls}">{sec["heading"]}</div>\n'
        sec_html += f'  <div class="{grid_class(sec.get("grid") or "three")}">\n'

        for ci, ch in enumerate(sec.get("charts") or []):
            cid = ch["id"]
            ctitle = ch["title"]
            insight_lead = ch.get("insight_lead") or ""
            # aggregate stats from first bound series
            first_bind = ch["datasets"][0]["bind"]
            first_fmt = ch["datasets"][0].get("format") or "int"
            if first_fmt == "ratio_chart_pct":
                st_fmt = "ratio"
            else:
                st_fmt = first_fmt
            ser0 = resolve_series(data, first_bind)
            stats_line = auto_stats_sentence(ser0, labels_list, st_fmt)
            insight_body = f"<b>解读</b>：{insight_lead}<br><b>数据摘要</b>：{stats_line}"

            sec_html += f"""    <div class="chart-card tone-{theme}">
      <h3>{ctitle}</h3>
      <div class="chart-body">
        <canvas id="{cid}"></canvas>
      </div>
      <div class="insight {ins_cls}">{insight_body}</div>
    </div>
"""

            # Build Chart.js
            ds_js: List[str] = []
            root_type = ch.get("root_type") or "line"
            use_pct = ch.get("use_pct_scale")
            y_left = ch.get("y_left") or ""
            y_right = ch.get("y_right") or ""
            has_y1 = any((d.get("y_axis") == "y1") for d in ch["datasets"])

            for di, d in enumerate(ch["datasets"]):
                bind = d["bind"]
                ser = resolve_series(data, bind)
                lab = d["label"]
                shape = d.get("shape") or "line"
                role = d.get("role") or "primary"
                fmt = d.get("format") or "int"
                color = role_color(theme, role, di)
                yid = d.get("y_axis") or "y"

                if fmt == "ratio_chart_pct":
                    jmode = "ratio_chart_pct"
                elif fmt == "ratio":
                    jmode = "ratio"
                elif fmt == "float2":
                    jmode = "float2"
                else:
                    jmode = "int"

                arr = js_array(ser, mode=jmode, digits=2)

                if shape == "bar":
                    ds_js.append(
                        f"mkBar('{_esc_js(lab)}', {arr}, '{color}', '{yid}')"
                    )
                else:
                    dash = [6, 3] if role == "contrast" else []
                    dash_s = json.dumps(dash)
                    ds_js.append(
                        "{...mkLine('%s', %s, '%s', %s), yAxisID:'%s'}"
                        % (_esc_js(lab), arr, color, dash_s, yid)
                    )

            ds_join = ",\n    ".join(ds_js)

            if has_y1 and root_type == "bar":
                opt = f"dualOpts('{_esc_js(y_left)}','{_esc_js(y_right)}')"
                chart_js_blocks.append(
                    f"""
new Chart(document.getElementById('{cid}'), {{
  type: 'bar',
  data: {{ labels, datasets: [
    {ds_join}
  ]}},
  options: {opt}
}});""".strip()
                )
            elif has_y1 and root_type == "line":
                opt = f"dualOpts('{_esc_js(y_left)}','{_esc_js(y_right)}')"
                chart_js_blocks.append(
                    f"""
new Chart(document.getElementById('{cid}'), {{
  type: 'line',
  data: {{ labels, datasets: [
    {ds_join}
  ]}},
  options: {opt}
}});""".strip()
                )
            elif use_pct:
                chart_js_blocks.append(
                    f"""
new Chart(document.getElementById('{cid}'), {{
  type: 'line',
  data: {{ labels, datasets: [
    {ds_join}
  ]}},
  options: pctOpts('%')
}});""".strip()
                )
            else:
                chart_js_blocks.append(
                    f"""
new Chart(document.getElementById('{cid}'), {{
  type: '{root_type}',
  data: {{ labels, datasets: [
    {ds_join}
  ]}},
  options: baseOpts('{_esc_js(y_left)}')
}});""".strip()
                )

        sec_html += "  </div>\n</div>\n"
        sections_blocks.append(sec_html)

    footer = manifest.get("footer_note") or ""

    charts_js = "\n".join(chart_js_blocks)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<script>__CHART_UMD__</script>
<style>
{report_css}
</style>
</head>
<body>

<h1>{title}</h1>
<p class="subtitle">{subtitle_html}</p>

{kpi_html}

{"".join(sections_blocks)}

<p style="font-size:11px;color:#94a3b8;margin-top:10px;line-height:1.6">{footer}</p>

<script>
const labels = {labels_js};

function mkLine(label, data, color, dash) {{
  return {{
    type: 'line',
    label, data,
    borderColor: color, backgroundColor: color+'22',
    pointBackgroundColor: color, pointRadius: 4, pointHoverRadius: 6,
    borderWidth: 2.2, borderDash: dash || [], tension: 0.35, fill: false, spanGaps: true,
  }};
}}
function mkBar(label, data, color, yAxisID) {{
  return {{ type:'bar', label, data, backgroundColor: color+'cc', borderRadius: 6, yAxisID: yAxisID || 'y' }};
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
    x: {{ grid:{{ color:'rgba(148,163,184,0.25)' }}, ticks:{{font:{{size:12}}, color:'#64748b'}} }},
    y: {{
      grid:{{ color:'rgba(148,163,184,0.25)' }},
      ticks:{{ font:{{size:12}}, padding: 6, color:'#64748b' }},
      title:{{ display:!!yLabel, text:yLabel, color:'#475569' }},
      beginAtZero:true,
      grace: '8%',
    }},
  }},
}});
const pctOpts = (yLabel='%') => {{
  const o = baseOpts(yLabel);
  o.scales.y.min = 0; o.scales.y.max = 100; o.scales.y.grace = 0;
  o.scales.y.ticks.callback = v => v + '%';
  o.scales.y.ticks.color = '#64748b';
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
    x: {{ grid:{{ color:'rgba(148,163,184,0.25)' }}, ticks:{{font:{{size:12}}, color:'#64748b'}} }},
    y: {{
      position:'left', beginAtZero:true, grace:'8%',
      title:{{display:true,text:yLeft, color:'#475569'}}, grid:{{color:'rgba(148,163,184,0.25)'}},
      ticks:{{ font:{{size:12}}, padding: 6, color:'#64748b' }},
    }},
    y1: {{
      position:'right', beginAtZero:true, grace:'8%',
      title:{{display:true,text:yRight, color:'#475569'}}, grid:{{drawOnChartArea:false}},
      ticks:{{ font:{{size:12}}, padding: 6, color:'#64748b' }},
    }},
  }},
}});

{charts_js}
</script>
</body>
</html>"""

    umd = VENDOR_CHART.read_text(encoding="utf-8")
    return html.replace("__CHART_UMD__", umd)


def _esc_js(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def main() -> None:
    ap = argparse.ArgumentParser(description="通用看板 HTML 渲染（business-charts）")
    ap.add_argument("--data", required=True, help="数据 JSON（query 技能产出）")
    ap.add_argument("--manifest", required=True, help="看板 manifest JSON")
    ap.add_argument("--output", "-o", required=True, help="输出 HTML 路径")
    args = ap.parse_args()

    data_path = Path(args.data)
    if not data_path.is_file():
        raise SystemExit(f"缺少数据文件：{data_path}")
    manifest = load_json(Path(args.manifest))
    data = load_json(data_path)
    # 确保 months 顺序与 derived 一致
    if "months" not in data:
        raise SystemExit("数据 JSON 须含 months 数组（或由模块键推导月份轴）；请用业务侧导出脚本生成 schema v2 数据")
    html = build_html(data, manifest)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

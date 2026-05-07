#!/usr/bin/env python3
"""
【第 2 段 / 渲染】通用业务看板 HTML 生成器。

- 输入：`--data` JSON（由 query-business-metrics 导出）+ `--manifest` 看板声明（图表类型、标题、业务导语）。
- 不访问 Archery；图表类型与配色由 manifest + 本脚本内主题色板共同决定。
- 每个图下方：`insight_lead`（业务角度说明）+ 自动统计句（峰谷、末月、近三月）。

示例：
  python3 render_dashboard_html.py \\
    --data ../../../查询指标/FY2025_chart_data.json \\
    --manifest ../../../查询指标/FY2025_dashboard.manifest.json \\
    --output ../../../图表/FY2025_功能使用年度总结.html
"""

from __future__ import annotations

import argparse
import html
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
    # 中性商务：主/次为 slate 阶，第三色用天蓝（避免蓝柱+绿线）
    "slate": ("#334155", "#64748b", "#0ea5e9"),
    # 青蓝系：柱线同属冷色家族，第三色用靛紫拉开层次
    "cyan": ("#0e7490", "#06b6d4", "#6366f1"),
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
CHARTJS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"


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


def _fmt_stat_val(v: float, stat_fmt: str) -> str:
    if stat_fmt in ("ratio", "ratio_chart_pct"):
        return fmt_pct_ratio(v)
    if stat_fmt == "float2":
        return f"{float(v):.2f}"
    return fmt_int(v)


def _normalize_chart_fmt(ds_fmt: str) -> str:
    if ds_fmt == "ratio_chart_pct":
        return "ratio"
    return ds_fmt or "int"


def _compact_data_line_style_a(
    series_name: str,
    values: List[Optional[float]],
    labels: List[str],
    stat_fmt: str,
) -> Optional[str]:
    """风格 A：指标名 + 末月标签 + 数值 +（上月、环比%）。"""
    pts = [
        (i, v)
        for i, v in enumerate(values)
        if v is not None and isinstance(v, (int, float))
    ]
    if not pts:
        return None
    last_i = len(values) - 1
    while last_i >= 0:
        v = values[last_i]
        if v is not None and isinstance(v, (int, float)):
            break
        last_i -= 1
    last_v = float(values[last_i])
    tag = labels[last_i] if last_i < len(labels) else ""
    latest = _fmt_stat_val(last_v, stat_fmt)
    pre_v: Optional[float] = None
    pre_i = last_i - 1
    while pre_i >= 0:
        v = values[pre_i]
        if v is not None and isinstance(v, (int, float)):
            pre_v = float(v)
            break
        pre_i -= 1
    w = wow(last_v, pre_v) if pre_v is not None else None
    if w is None:
        if pre_v is not None and pre_v == 0:
            return f"<b>{series_name}</b> {tag} <b>{latest}</b>（上月 0）。"
        if pre_v is None:
            return f"<b>{series_name}</b> {tag} <b>{latest}</b>。"
        return f"<b>{series_name}</b> {tag} <b>{latest}</b>。"
    prev_s = _fmt_stat_val(pre_v, stat_fmt)
    pct = f"{w * 100:+.1f}%"
    return f"<b>{series_name}</b> {tag} <b>{latest}</b>（上月 {prev_s}，{pct}）。"


def _nonzero_span(
    values: List[Optional[float]],
) -> Optional[Tuple[int, int, float, float]]:
    nz = [
        (i, float(v))
        for i, v in enumerate(values)
        if v is not None and isinstance(v, (int, float)) and float(v) != 0.0
    ]
    if len(nz) < 2:
        return None
    i0, v0 = nz[0]
    i1, v1 = nz[-1]
    return (i0, i1, v0, v1)


def _trend_word(v0: float, v1: float, *, thr: float = 0.05) -> str:
    if v1 > v0 * (1 + thr):
        return "上升"
    if v1 < v0 * (1 - thr):
        return "回落"
    return "相对平稳"


def _last_month_wow_sign(values: List[Optional[float]]) -> int:
    """最近一月相对上一月：1 涨、-1 跌、0 无或不可比。"""
    last_i = len(values) - 1
    while last_i >= 0:
        v = values[last_i]
        if v is not None and isinstance(v, (int, float)):
            break
        last_i -= 1
    else:
        return 0
    pre_v: Optional[float] = None
    pre_i = last_i - 1
    while pre_i >= 0:
        v = values[pre_i]
        if v is not None and isinstance(v, (int, float)):
            pre_v = float(v)
            break
        pre_i -= 1
    if pre_v is None:
        return 0
    w = wow(float(values[last_i]), pre_v)
    if w is None:
        return 0
    if w > 0.001:
        return 1
    if w < -0.001:
        return -1
    return 0


def _qualitative_conclusion_style_c(
    specs: List[Tuple[str, List[Optional[float]], str]],
    labels: List[str],
) -> str:
    """风格 C：只写定性判断，不复述从 X 月到 Y 月的数字。"""
    trends: List[str] = []
    mom_signs: List[int] = []
    has_point = False
    for _, vals, _ in specs:
        pts = [
            (i, v)
            for i, v in enumerate(vals)
            if v is not None and isinstance(v, (int, float))
        ]
        if pts and any(v != 0 for _, v in pts):
            has_point = True
        sp = _nonzero_span(vals)
        if sp:
            trends.append(_trend_word(sp[2], sp[3]))
        mom_signs.append(_last_month_wow_sign(vals))

    if not has_point:
        return "<b>结论</b>：时间窗内有效样本少，有待攒足月份再判断。"

    nonzero_mom = [s for s in mom_signs if s != 0]
    mom_mixed = len(set(nonzero_mom)) > 1 if len(nonzero_mom) >= 2 else False
    if mom_mixed:
        return "<b>结论</b>：最近一月各指标涨跌方向不一致，适合对照图形看结构。"

    if len(trends) >= 2:
        if all(t == "上升" for t in trends):
            return "<b>结论</b>：有数区间内整体抬升，使用和参与同步加厚，可继续向下游渗透。"
        if all(t == "回落" for t in trends):
            return "<b>结论</b>：有数区间内整体走弱，可结合季节或交付节奏再看原因。"
        return "<b>结论</b>：各指标长周期走向分化，需结合图形看是否「量与比例」错位。"

    if len(trends) == 1:
        t = trends[0]
        if t == "上升":
            return "<b>结论</b>：从首月到末月整体走高。"
        if t == "回落":
            return "<b>结论</b>：从首月到末月整体走弱。"
        return "<b>结论</b>：从首月到末月相对平稳，重点看单月起伏。"

    return "<b>结论</b>：可看末月与上月对比；长周期走势待样本更连续后再总结。"


def trend_march_chart_insight(
    insight_lead: str,
    values: List[Optional[float]],
    labels: List[str],
    stat_fmt: str,
    series_name: str = "该指标",
) -> str:
    """风格 A 数据行 + 风格 C 结论（轻量）。"""
    _ = insight_lead  # 当前版不写 manifest 导语，减轻阅读负担
    pts = [
        (i, v)
        for i, v in enumerate(values)
        if v is not None and isinstance(v, (int, float))
    ]
    if not pts or all(v == 0 for _, v in pts):
        return "时间窗内几乎全是 0，多半是埋点或功能尚未铺开，有数了再解读更准确。"

    fact = _compact_data_line_style_a(series_name, values, labels, stat_fmt)
    concl = _qualitative_conclusion_style_c([(series_name, values, stat_fmt)], labels)
    bits = [x for x in [fact, concl] if x]
    return "<br>".join(bits)


def trend_march_chart_insight_multi(
    data: dict,
    ch: dict,
    labels_list: List[str],
    insight_lead: str,
) -> str:
    """多序列：每条一行 A 样式 + 一句 C 结论。"""
    _ = insight_lead
    datasets = ch.get("datasets") or []
    if not datasets:
        return ""

    series_specs: List[Tuple[str, List[Optional[float]], str]] = []
    fact_lines: List[str] = []

    for d in datasets:
        bind = d["bind"]
        lab = d.get("label") or bind
        sf = _normalize_chart_fmt(d.get("format") or "int")
        ser = resolve_series(data, bind)
        series_specs.append((lab, ser, sf))
        s = _compact_data_line_style_a(lab, ser, labels_list, sf)
        if s:
            fact_lines.append(s)

    pts0 = [
        (i, v)
        for i, v in enumerate(series_specs[0][1])
        if v is not None and isinstance(v, (int, float))
    ]
    if not pts0 or all(v == 0 for _, v in pts0):
        return "时间窗内几乎全是 0，多半是埋点或业务尚未起来，有样本了再下结论更稳。"

    concl = _qualitative_conclusion_style_c(series_specs, labels_list)
    bits = fact_lines + [concl]
    return "<br>".join(bits)


def _series_last_pre(
    values: List[Optional[float]],
) -> Tuple[int, float, Optional[float]]:
    """最后一个有效点下标、值、上一有效点值（若无则 pre_v None）。"""
    last_i = len(values) - 1
    while last_i >= 0:
        v = values[last_i]
        if v is not None and isinstance(v, (int, float)):
            break
        last_i -= 1
    else:
        return -1, 0.0, None
    last_v = float(values[last_i])
    pre_v: Optional[float] = None
    pre_i = last_i - 1
    while pre_i >= 0:
        v = values[pre_i]
        if v is not None and isinstance(v, (int, float)):
            pre_v = float(v)
            break
        pre_i -= 1
    return last_i, last_v, pre_v


def _aggregate_mom_phrase(wows: List[Optional[float]]) -> str:
    valid = [w for w in wows if w is not None]
    if not valid:
        return "上月可比口径不足"
    pos = [w for w in valid if w > 0.02]
    neg = [w for w in valid if w < -0.02]
    strong_up = any(w >= 0.15 for w in valid)
    strong_dn = any(w <= -0.15 for w in valid)
    if pos and not neg:
        return "比上月均大幅上行" if strong_up else "比上月均上行"
    if neg and not pos:
        return "比上月均明显回落" if strong_dn else "比上月均回落"
    return "比上月涨跌不一"


def _single_mom_phrase(w: Optional[float]) -> str:
    if w is None:
        return "上月可比口径不足"
    if w >= 0.2:
        return "较上月大幅上行"
    if w > 0.02:
        return "较上月上行"
    if w <= -0.2:
        return "较上月明显回落"
    if w < -0.02:
        return "较上月回落"
    return "较上月基本持平"


def _peak_sentence(values: List[Optional[float]], labels: List[str]) -> str:
    pts = [
        (i, float(v))
        for i, v in enumerate(values)
        if v is not None and isinstance(v, (int, float))
    ]
    if not pts:
        return ""
    nonzero = [(i, v) for i, v in pts if v != 0]
    pool = nonzero or pts
    mx_i, _ = max(pool, key=lambda x: x[1])
    last_i = pts[-1][0]
    tag_mx = labels[mx_i] if mx_i < len(labels) else ""
    tag_last = labels[last_i] if last_i < len(labels) else ""
    if mx_i == last_i:
        return f"窗口内高点在末月 <b>{html.escape(tag_last)}</b> 附近。"
    return f"窗口内高点在 <b>{html.escape(tag_mx)}</b>，末月为 <b>{html.escape(tag_last)}</b>。"


def _weekly_e_conclusion_line(
    values: List[Optional[float]],
    labels: List[str],
) -> str:
    pts = [
        (i, float(v))
        for i, v in enumerate(values)
        if v is not None and isinstance(v, (int, float))
    ]
    if len(pts) < 2:
        return "<b>结论</b>：有效月份偏少，走势待数据续上再读。"
    if len(pts) >= 3:
        i3, v3 = pts[-3]
        i2, v2 = pts[-2]
        i1, v1 = pts[-1]
        t3 = labels[i3] if i3 < len(labels) else ""
        t2 = labels[i2] if i2 < len(labels) else ""
        t1 = labels[i1] if i1 < len(labels) else ""
        if v2 < v3 and v2 < v1 and v1 > v2:
            return (
                f"<b>结论</b>：<b>{html.escape(t2)}</b> 波动后 <b>{html.escape(t1)}</b> 收回，"
                f"全窗看仍偏强。"
            )
        if v1 > v2 > v3:
            return "<b>结论</b>：近三月逐月走强，节奏偏强。"
        if v1 < v2 < v3:
            return "<b>结论</b>：近三月逐月走弱，末段压力需关注。"
    sp = _nonzero_span(values)
    if sp:
        tw = _trend_word(sp[2], sp[3])
        if tw == "上升":
            return "<b>结论</b>：有样本以来整体抬升，末月延续势头。"
        if tw == "回落":
            return "<b>结论</b>：有样本以来整体走弱，末月仍在探底。"
    mom = _last_month_wow_sign(values)
    if mom == 1:
        return "<b>结论</b>：末月较上月改善，是否延续有待观察。"
    if mom == -1:
        return "<b>结论</b>：末月较上月走弱，建议结合业务节奏复盘。"
    return "<b>结论</b>：全窗相对平稳，重点看单月结构。"


def _weekly_e_conclusion_multi(
    series_specs: List[Tuple[str, List[Optional[float]], str]],
    labels_list: List[str],
) -> str:
    moms = [_last_month_wow_sign(vals) for _, vals, _ in series_specs]
    active = [m for m in moms if m != 0]
    if len(active) >= 2 and len(set(active)) > 1:
        return "<b>结论</b>：各指标短期走向分化，建议对照图形拆因。"
    return _weekly_e_conclusion_line(series_specs[0][1], labels_list)


def trend_weekly_e_single(
    insight_lead: str,
    values: List[Optional[float]],
    labels: List[str],
    stat_fmt: str,
    series_name: str,
) -> str:
    """风格 E：周报体式——末月+环比一句、高点一句、结论一句。"""
    _ = insight_lead
    pts = [
        (i, v)
        for i, v in enumerate(values)
        if v is not None and isinstance(v, (int, float))
    ]
    if not pts or all(v == 0 for _, v in pts):
        return "时间窗内几乎全是 0，多半是埋点或功能尚未铺开，有数了再解读更准确。"
    last_i, last_v, pre_v = _series_last_pre(values)
    w = wow(last_v, pre_v) if pre_v is not None else None
    nm = html.escape(series_name.strip() or "该指标")
    val_s = _fmt_stat_val(last_v, stat_fmt)
    line1 = f"末月 <b>{nm}</b> <b>{val_s}</b>，{_single_mom_phrase(w)}。"
    line2 = _peak_sentence(values, labels)
    line3 = _weekly_e_conclusion_line(values, labels)
    return "<br>".join([x for x in [line1, line2, line3] if x])


def trend_weekly_e_multi(
    data: dict,
    ch: dict,
    labels_list: List[str],
    insight_lead: str,
) -> str:
    """风格 E·多序列：末月并排列举 + 比上月总括 + 高点（领先序列）+ 结论。"""
    _ = insight_lead
    datasets = ch.get("datasets") or []
    if not datasets:
        return ""

    series_specs: List[Tuple[str, List[Optional[float]], str]] = []
    for d in datasets:
        bind = d["bind"]
        lab = (d.get("label") or bind).strip()
        sf = _normalize_chart_fmt(d.get("format") or "int")
        ser = resolve_series(data, bind)
        series_specs.append((lab, ser, sf))

    pts0 = [
        (i, v)
        for i, v in enumerate(series_specs[0][1])
        if v is not None and isinstance(v, (int, float))
    ]
    if not pts0 or all(v == 0 for _, v in pts0):
        return "时间窗内几乎全是 0，多半是埋点或业务尚未起来，有样本了再下结论更稳。"

    segs: List[str] = []
    wows: List[Optional[float]] = []
    for lab, ser, sf in series_specs:
        _, last_v, pre_v = _series_last_pre(ser)
        segs.append(f"<b>{html.escape(lab)}</b> <b>{_fmt_stat_val(last_v, sf)}</b>")
        wows.append(wow(last_v, pre_v) if pre_v is not None else None)
    line1 = f"末月 {'、'.join(segs)}，{_aggregate_mom_phrase(wows)}。"
    line2 = _peak_sentence(series_specs[0][1], labels_list)
    line3 = _weekly_e_conclusion_multi(series_specs, labels_list)
    return "<br>".join([x for x in [line1, line2, line3] if x])


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
        "slate": "slate",
        "cyan": "cyan",
    }
    return m.get(theme, "")


def insight_class(theme: str) -> str:
    return section_title_class(theme)


def metric_notes_html(ch: dict) -> str:
    """manifest `metric_notes`：字符串数组，每条一行指标定义（浅色列表）。"""
    raw = ch.get("metric_notes")
    if not raw:
        return ""
    items: List[str] = [raw] if isinstance(raw, str) else list(raw)
    lis: List[str] = []
    for line in items:
        t = (line or "").strip()
        if t:
            lis.append(f"      <li>{html.escape(t)}</li>")
    if not lis:
        return ""
    title = (ch.get("metric_notes_title") or "指标解释").strip()
    title_html = html.escape(title) if title else "指标解释"
    return (
        "      <div class=\"metric-notes-wrap\">\n"
        f"        <div class=\"metric-notes-title\">{title_html}</div>\n"
        "        <ul class=\"metric-notes\">\n"
        + "\n".join(lis)
        + "\n        </ul>\n"
        "      </div>"
    )


def grid_class(g: str) -> str:
    g = (g or "").strip().lower()
    if g == "three":
        return "chart-grid three"
    if g in ("one", "1", "single"):
        return "chart-grid one"
    # two / 缺省：与 chart-report-*.css 中 .chart-grid 一致（1fr 1fr）
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
        # 缺省与 chart-report-*.css 中 .chart-grid 一致：一行两列（1fr 1fr）
        sec_html += f'  <div class="{grid_class(sec.get("grid") or "")}">\n'

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
            # 手写洞察优先（用于汇报版看板）
            manual_html = (ch.get("insight_html") or ch.get("manual_insight_html") or "").strip()
            if manual_html:
                insight_body = manual_html
            elif ch.get("insight_style") == "trend_weekly_e":
                n_ds = len(ch.get("datasets") or [])
                if n_ds >= 2:
                    insight_body = trend_weekly_e_multi(
                        data, ch, labels_list, insight_lead
                    )
                else:
                    sname = (ch["datasets"][0].get("label") or "该指标").strip()
                    insight_body = trend_weekly_e_single(
                        insight_lead, ser0, labels_list, st_fmt, sname
                    )
            elif ch.get("insight_style") == "trend_march":
                n_ds = len(ch.get("datasets") or [])
                if n_ds >= 2:
                    insight_body = trend_march_chart_insight_multi(
                        data, ch, labels_list, insight_lead
                    )
                else:
                    sname = (ch["datasets"][0].get("label") or "该指标").strip()
                    insight_body = trend_march_chart_insight(
                        insight_lead, ser0, labels_list, st_fmt, sname
                    )
            else:
                stats_line = auto_stats_sentence(ser0, labels_list, st_fmt)
                insight_body = f"<b>解读</b>：{insight_lead}<br><b>数据摘要</b>：{stats_line}"

            notes_block = metric_notes_html(ch)
            sec_html += f"""    <div class="chart-card tone-{theme}">
      <h3>{ctitle}</h3>
      <div class="chart-body">
        <canvas id="{cid}"></canvas>
      </div>
{notes_block}
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
<script src="{CHARTJS_CDN}"></script>
<style>
{report_css}
</style>
</head>
<body>

<div class="page">
<h1>{title}</h1>
<p class="subtitle">{subtitle_html}</p>

{kpi_html}

{"".join(sections_blocks)}

<p class="footer-note">{footer}</p>

<script>
const labels = {labels_js};

function mkLine(label, data, color, dash) {{
  return {{
    type: 'line',
    label, data,
    /* Chart.js：order 越大越先绘制（在底层）；折线后画，盖在柱子上 */
    order: 0,
    borderColor: color, backgroundColor: color+'18',
    pointRadius: 3,
    pointHoverRadius: 5,
    pointHitRadius: 10,
    pointBorderWidth: 2,
    pointBorderColor: color,
    pointBackgroundColor: '#ffffff',
    borderWidth: 3, borderDash: dash || [], tension: 0.34, fill: false, spanGaps: true,
  }};
}}
function mkBar(label, data, color, yAxisID) {{
  return {{
    type:'bar',
    label,
    data,
    order: 10,
    backgroundColor: color+'e0',
    borderColor: color,
    borderWidth: 1,
    borderRadius: 6,
    barPercentage: 0.62,
    categoryPercentage: 0.72,
    yAxisID: yAxisID || 'y'
  }};
}}
const baseOpts = (yLabel) => ({{
  responsive: true,
  maintainAspectRatio: false,
  layout: {{ padding: {{ top: 10, right: 10, bottom: 6, left: 8 }} }},
  interaction: {{ mode:'index', intersect:false }},
  plugins: {{
    legend: {{
      position: 'top',
      align: 'center',
      labels: {{
        font: {{ size: 12, weight: '600' }},
        padding: 14,
        color: '#334155',
        usePointStyle: true,
        pointStyle: 'rectRounded',
        boxWidth: 10,
        boxHeight: 10,
      }}
    }},
    tooltip: {{
      padding: 10,
      cornerRadius: 10,
      backgroundColor: '#0f172a',
      titleColor: '#fff',
      bodyColor: '#e2e8f0',
      displayColors: true,
      usePointStyle: true,
      boxPadding: 4,
      titleAlign: 'center',
      bodyAlign: 'left',
    }},
  }},
  scales: {{
    x: {{ grid:{{ color:'rgba(148,163,184,0.08)' }}, ticks:{{font:{{size:12, weight:'500'}}, color:'#64748b'}} }},
    y: {{
      grid:{{ color:'rgba(148,163,184,0.10)' }},
      ticks:{{ font:{{size:12, weight:'500'}}, padding: 6, color:'#64748b' }},
      title:{{ display:!!yLabel, text:yLabel, color:'#475569', font:{{weight:'600'}} }},
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
    legend: {{
      position: 'top',
      align: 'center',
      labels: {{
        font: {{ size: 12, weight: '600' }},
        padding: 14,
        color: '#334155',
        usePointStyle: true,
        pointStyle: 'rectRounded',
        boxWidth: 10,
        boxHeight: 10,
      }}
    }},
    tooltip: {{
      padding: 10,
      cornerRadius: 10,
      backgroundColor: '#0f172a',
      titleColor: '#fff',
      bodyColor: '#e2e8f0',
      displayColors: true,
      usePointStyle: true,
      boxPadding: 4,
      titleAlign: 'center',
      bodyAlign: 'left',
    }},
  }},
  scales: {{
    x: {{ grid:{{ color:'rgba(148,163,184,0.08)' }}, ticks:{{font:{{size:12, weight:'500'}}, color:'#64748b'}} }},
    y: {{
      position:'left', beginAtZero:true, grace:'8%',
      title:{{display:true,text:yLeft, color:'#475569', font:{{weight:'600'}}}}, grid:{{color:'rgba(148,163,184,0.10)'}},
      ticks:{{ font:{{size:12, weight:'500'}}, padding: 6, color:'#64748b' }},
    }},
    y1: {{
      position:'right', beginAtZero:true, grace:'8%',
      title:{{display:true,text:yRight, color:'#475569', font:{{weight:'600'}}}}, grid:{{drawOnChartArea:false}},
      ticks:{{ font:{{size:12, weight:'500'}}, padding: 6, color:'#64748b' }},
    }},
  }},
}});

{charts_js}
</script>
</div>
</body>
</html>"""
    return html


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

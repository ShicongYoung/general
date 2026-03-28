#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import math
import os
import urllib.parse
import urllib.request
from typing import Dict, List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成核心模块周报指标")
    parser.add_argument(
        "--config",
        default=".cursor/skills/weekly-core-metrics/scripts/config.json",
        help="配置文件路径，默认 .cursor/skills/weekly-core-metrics/scripts/config.json",
    )
    parser.add_argument(
        "--output",
        default="",
        help="可选：自定义输出 markdown 文件路径；不传时自动输出到 周报/{xx月第x周周报}-杨士聪.md",
    )
    parser.add_argument(
        "--data-output",
        default="周报/latest_metrics.json",
        help="指标数据输出 JSON 路径，供技能内的 LLM 分析步骤使用",
    )
    return parser.parse_args()


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def period_dates(today: dt.date) -> Dict[str, Tuple[dt.date, dt.date]]:
    this_monday = today - dt.timedelta(days=today.weekday())
    this_sunday = this_monday + dt.timedelta(days=6)
    last_monday = this_monday - dt.timedelta(days=7)
    last_sunday = this_sunday - dt.timedelta(days=7)
    near2_start = last_monday
    near2_end = this_sunday
    month_start = today.replace(day=1)
    if today.month == 12:
        next_month_start = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month_start = today.replace(month=today.month + 1, day=1)
    month_end = next_month_start - dt.timedelta(days=1)
    return {
        "this_week": (this_monday, this_sunday),
        "last_week": (last_monday, last_sunday),
        "near2_week": (near2_start, near2_end),
        "this_month": (month_start, month_end),
    }


def d(date_obj: dt.date) -> str:
    return date_obj.strftime("%Y-%m-%d")


def default_output_path(today: dt.date) -> str:
    month_text = f"{today.month:02d}月"
    week_index = ((today.day - 1) // 7) + 1
    filename = f"{month_text}第{week_index}周周报-杨士聪.md"
    return os.path.join("周报", filename)


def post_sql(config: dict, instance_name: str, sql: str) -> dict:
    auth = config.get("auth", {})
    csrf = auth.get("csrftoken", "")
    sessionid = auth.get("sessionid", "")
    if not csrf or not sessionid or "请替换" in csrf or "请替换" in sessionid:
        raise RuntimeError("config.json 中 auth.csrftoken / auth.sessionid 未配置，请先更新。")

    data = {
        "instance_name": instance_name,
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
    req.add_header("cookie", f"csrftoken={csrf}; sessionid={sessionid}")

    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def first_dict_row(payload: dict) -> dict:
    # Archery 常见结构：{"data": {"rows": [[...]], "column_list": [...]}}
    data = payload.get("data")
    if isinstance(data, dict):
        rows = data.get("rows")
        columns = data.get("column_list")
        if isinstance(rows, list) and rows and isinstance(rows[0], list):
            first_row = rows[0]
            if isinstance(columns, list) and columns:
                mapped = {}
                for i, col in enumerate(columns):
                    if i < len(first_row):
                        mapped[str(col)] = first_row[i]
                if mapped:
                    return mapped
            return {f"c{i}": v for i, v in enumerate(first_row)}

    candidates = [payload]
    for key in ("data", "rows", "result", "results"):
        if key in payload:
            candidates.append(payload[key])
    for item in candidates:
        if isinstance(item, list) and item:
            if isinstance(item[0], dict):
                return item[0]
            if isinstance(item[0], list):
                # 如果返回是二维数组，兜底映射为 c0,c1...
                return {f"c{i}": v for i, v in enumerate(item[0])}
        if isinstance(item, dict):
            nested = item.get("rows") or item.get("data") or item.get("result")
            if isinstance(nested, list) and nested:
                if isinstance(nested[0], dict):
                    return nested[0]
                if isinstance(nested[0], list):
                    return {f"c{i}": v for i, v in enumerate(nested[0])}
    raise RuntimeError(f"无法识别查询结果结构：{json.dumps(payload, ensure_ascii=False)[:500]}")


def get_float(row: dict, key: str) -> float:
    val = row.get(key)
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def safe_div(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return a / b


def pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def wow(this_v: float, last_v: float) -> str:
    if last_v == 0:
        return "N/A"
    return f"{(this_v - last_v) / last_v * 100:.1f}%"


def heuristic_analysis(metric: str, this_v: float, last_v: float, is_rate: bool = False) -> Tuple[str, str]:
    if last_v == 0 and this_v > 0:
        return ("上周基数较低，本周启动或恢复明显", "核查新增客户来源，沉淀可复制打法")
    if last_v == 0 and this_v == 0:
        return ("连续两周无有效产出", "排查埋点、流程使用门槛与客户触达节奏")

    change = (this_v - last_v) / last_v
    if change <= -0.2:
        if is_rate:
            return ("转化率明显下滑，可能存在流程中断或质量问题", "定位流失环节，补齐发起-执行-闭环链路")
        return ("核心规模指标下滑较大，可能受活跃客户减少影响", "按客户分层复盘，优先召回高价值客户")
    if change >= 0.2:
        return ("指标增长明显，当前策略可能有效", "总结高贡献场景并扩大覆盖")
    return ("整体相对平稳，未见明显异常波动", "持续观察分场景结构变化，提前识别风险")


def sql_outsource_counts(start_date: str, end_date: str) -> str:
    return f"""
WITH orders AS (
    SELECT DISTINCT org_id
    FROM dt_outsource_order
    WHERE DATE(created_at) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
),
posts AS (
    SELECT DISTINCT org_id
    FROM dt_outsource_post
    WHERE DATE(created_at) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
)
SELECT
    (SELECT COUNT(*) FROM orders) AS order_customers,
    (SELECT COUNT(*) FROM orders o JOIN posts p USING(org_id)) AS covered_customers;
""".strip()


def sql_collab_counts(start_date: str, end_date: str) -> str:
    return f"""
WITH base AS (
    SELECT
        org_id,
        DATE(created_at) AS act_date,
        associate_id
    FROM dt_collaborative_task
    WHERE DATE(created_at) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
),
per_org AS (
    SELECT
        org_id,
        COUNT(DISTINCT act_date) AS active_days
    FROM base
    GROUP BY org_id
)
SELECT
    (SELECT COUNT(*) FROM per_org WHERE active_days >= 1) AS task_customers,
    (SELECT COUNT(*) FROM per_org WHERE active_days >= 2) AS covered_customers,
    (SELECT COUNT(*) FROM per_org WHERE active_days >= 2) AS active_2day_customers,
    (SELECT COUNT(*) FROM base) AS total_tasks,
    (SELECT COUNT(*) FROM base WHERE associate_id IS NOT NULL) AS associated_tasks;
""".strip()


def fetch_sum_over_instances(config: dict, sql: str, key_list: List[str]) -> Dict[str, float]:
    acc = {k: 0.0 for k in key_list}
    for instance in config["instances"]:
        payload = post_sql(config, instance, sql)
        row = first_dict_row(payload)
        for k in key_list:
            acc[k] += get_float(row, k)
    return acc


def build_metrics(config: dict, p: Dict[str, Tuple[dt.date, dt.date]]) -> List[dict]:
    tw_s, tw_e = d(p["this_week"][0]), d(p["this_week"][1])
    lw_s, lw_e = d(p["last_week"][0]), d(p["last_week"][1])
    n2_s, n2_e = d(p["near2_week"][0]), d(p["near2_week"][1])

    out_this = fetch_sum_over_instances(
        config, sql_outsource_counts(tw_s, tw_e), ["order_customers", "covered_customers"]
    )
    out_last = fetch_sum_over_instances(
        config, sql_outsource_counts(lw_s, lw_e), ["order_customers", "covered_customers"]
    )
    out_near2 = fetch_sum_over_instances(
        config, sql_outsource_counts(n2_s, n2_e), ["order_customers", "covered_customers"]
    )
    col_this = fetch_sum_over_instances(
        config,
        sql_collab_counts(tw_s, tw_e),
        ["task_customers", "covered_customers", "active_2day_customers", "total_tasks", "associated_tasks"],
    )
    col_last = fetch_sum_over_instances(
        config,
        sql_collab_counts(lw_s, lw_e),
        ["task_customers", "covered_customers", "active_2day_customers", "total_tasks", "associated_tasks"],
    )
    col_near2 = fetch_sum_over_instances(
        config,
        sql_collab_counts(n2_s, n2_e),
        ["task_customers", "covered_customers", "active_2day_customers", "total_tasks", "associated_tasks"],
    )
    metrics = []

    # 委外管理
    metrics.append(
        {
            "name": "委外管理-覆盖客户数",
            "definition": "一周内既创建委外订单又有收发记录的客户（订单与 post 表交集）",
            "this": out_this["covered_customers"],
            "last": out_last["covered_customers"],
            "is_rate": False,
        }
    )
    metrics.append(
        {
            "name": "委外管理-客户留存率",
            "definition": "本周覆盖客户数 / 近2周覆盖客户数",
            "this": safe_div(out_this["covered_customers"], out_near2["covered_customers"]),
            "last": safe_div(out_last["covered_customers"], out_near2["covered_customers"]),
            "is_rate": True,
        }
    )
    metrics.append(
        {
            "name": "委外管理-委外订单客户数",
            "definition": "一周内创建过委外订单的客户数",
            "this": out_this["order_customers"],
            "last": out_last["order_customers"],
            "is_rate": False,
        }
    )
    metrics.append(
        {
            "name": "委外管理-订单到收发货转换率",
            "definition": "本周覆盖客户数 / 本周委外订单客户数（有订单客户中，产生收发记录的比例）",
            "this": safe_div(out_this["covered_customers"], out_this["order_customers"]),
            "last": safe_div(out_last["covered_customers"], out_last["order_customers"]),
            "is_rate": True,
        }
    )

    # 协同任务
    metrics.append(
        {
            "name": "协同任务-覆盖客户数",
            "definition": "一周内有任意2天创建任务的客户数",
            "this": col_this["covered_customers"],
            "last": col_last["covered_customers"],
            "is_rate": False,
        }
    )
    metrics.append(
        {
            "name": "协同任务-客户留存率",
            "definition": "本周覆盖客户数 / 近2周覆盖客户数",
            "this": safe_div(col_this["covered_customers"], col_near2["covered_customers"]),
            "last": safe_div(col_last["covered_customers"], col_near2["covered_customers"]),
            "is_rate": True,
        }
    )
    metrics.append(
        {
            "name": "协同任务-创建协同任务客户数",
            "definition": "一周内创建过任务（至少1天有任务）的客户数",
            "this": col_this["task_customers"],
            "last": col_last["task_customers"],
            "is_rate": False,
        }
    )
    metrics.append(
        {
            "name": "协同任务-活跃客户转换率",
            "definition": "一周内有2天创建任务的客户数 / 一周内创建过任务的客户数",
            "this": safe_div(col_this["active_2day_customers"], col_this["task_customers"]),
            "last": safe_div(col_last["active_2day_customers"], col_last["task_customers"]),
            "is_rate": True,
        }
    )
    metrics.append(
        {
            "name": "协同任务-从工单创建协同任务的比例",
            "definition": "associate_id 不为空的任务数 / 一周内总任务数",
            "this": safe_div(col_this["associated_tasks"], col_this["total_tasks"]),
            "last": safe_div(col_last["associated_tasks"], col_last["total_tasks"]),
            "is_rate": True,
        }
    )

    for m in metrics:
        m["insight"], m["conclusion"] = "待LLM分析", "待LLM建议"
    return metrics


def fmt_value(v: float, is_rate: bool) -> str:
    if is_rate:
        return pct(v)
    if math.isclose(v, round(v)):
        return str(int(round(v)))
    return f"{v:.2f}"


def render_markdown(metrics: List[dict], p: Dict[str, Tuple[dt.date, dt.date]]) -> str:
    lines = []
    lines.append("# 核心模块周报指标")
    lines.append("")
    lines.append(
        f"- 本周周期：{d(p['this_week'][0])} ~ {d(p['this_week'][1])}；"
        f"上周同周期：{d(p['last_week'][0])} ~ {d(p['last_week'][1])}"
    )
    lines.append(
        f"- 近2周周期：{d(p['near2_week'][0])} ~ {d(p['near2_week'][1])}；"
        f"本月周期：{d(p['this_month'][0])} ~ {d(p['this_month'][1])}"
    )
    lines.append("")
    lines.append("| 核心指标 | 指标口径 | 本周结果 | 上周结果 | 环比 | 洞察结果 | 结论/改进建议 |")
    lines.append("|---|---|---:|---:|---:|---|---|")
    for m in metrics:
        this_str = fmt_value(m["this"], m["is_rate"])
        last_str = fmt_value(m["last"], m["is_rate"])
        wow_str = wow(m["this"], m["last"])
        lines.append(
            f"| {m['name']} | {m['definition']} | {this_str} | {last_str} | {wow_str} | {m['insight']} | {m['conclusion']} |"
        )
    lines.append("")
    lines.append("> 注1：如果接口 token 失效，请更新 config.json 中的 csrftoken/sessionid 后重跑。")
    lines.append("> 注2：洞察与结论由技能在同一次执行中基于 latest_metrics.json 使用对话大模型补全。")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    today = dt.date.today()
    periods = period_dates(today)
    metrics = build_metrics(config, periods)
    md = render_markdown(metrics, periods)

    output_path = args.output.strip() if args.output else default_output_path(today)
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)
    data_dir = os.path.dirname(args.data_output)
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
    with open(args.data_output, "w", encoding="utf-8") as f:
        json.dump(
            {
                "periods": {k: [d(v[0]), d(v[1])] for k, v in periods.items()},
                "metrics": metrics,
                "report_path": output_path,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"已生成周报：{output_path}")


if __name__ == "__main__":
    main()

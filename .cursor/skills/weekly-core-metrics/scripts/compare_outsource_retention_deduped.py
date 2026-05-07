#!/usr/bin/env python3
"""
对比「分实例计数相加」（周报脚本）与「跨实例 org_id 并集去重后再算留存」的委外留存率。

用法（在仓库根目录）：
  python3 .cursor/skills/weekly-core-metrics/scripts/compare_outsource_retention_deduped.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Set, Tuple

# 与 generate_weekly_report 同目录，便于复用 SQL 文本
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from generate_weekly_report import (  # noqa: E402
    fetch_sum_over_instances,
    load_config,
    sql_outsource_retention,
)


def post_sql_with_limit(config: dict, instance_name: str, sql: str, limit_num: int) -> dict:
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
        "limit_num": str(limit_num),
    }
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(config["archery_url"], data=encoded, method="POST")
    req.add_header("accept", "application/json, text/javascript, */*; q=0.01")
    req.add_header("content-type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("x-requested-with", "XMLHttpRequest")
    req.add_header("x-csrftoken", csrf)
    req.add_header("cookie", f"csrftoken={csrf}; sessionid={sessionid}")

    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def sql_outsource_active_org_ids(start_date: str, end_date: str) -> str:
    """单周「订单∩收发」活跃客户 org_id 列表（与周报活跃定义一致）。"""
    return f"""
WITH orders AS (
    SELECT DISTINCT org_id FROM dt_outsource_order
    WHERE DATE(created_at) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
),
posts AS (
    SELECT DISTINCT org_id FROM dt_outsource_post
    WHERE DATE(created_at) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
)
SELECT o.org_id FROM orders o JOIN posts p USING(org_id);
""".strip()


def fetch_org_ids_union(config: dict, start: str, end: str, limit_num: int) -> Set[str]:
    sql = sql_outsource_active_org_ids(start, end)
    out: Set[str] = set()
    for instance in config["instances"]:
        payload = post_sql_with_limit(config, instance, sql, limit_num)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            continue
        rows = data.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if row and len(row) > 0 and row[0] is not None:
                out.add(str(row[0]))
    return out


def retention_sum_method(
    config: dict, lw_s: str, lw_e: str, tw_s: str, tw_e: str
) -> Tuple[float, float, float]:
    acc = fetch_sum_over_instances(
        config, sql_outsource_retention(lw_s, lw_e, tw_s, tw_e), ["last_week_customers", "retained_customers"]
    )
    last_v = acc["last_week_customers"]
    ret_v = acc["retained_customers"]
    rate = ret_v / last_v if last_v else 0.0
    return rate, last_v, ret_v


def retention_deduped_method(
    config: dict, lw_s: str, lw_e: str, tw_s: str, tw_e: str, limit_num: int
) -> Tuple[float, int, int]:
    last_set = fetch_org_ids_union(config, lw_s, lw_e, limit_num)
    this_set = fetch_org_ids_union(config, tw_s, tw_e, limit_num)
    retained = last_set & this_set
    last_n = len(last_set)
    ret_n = len(retained)
    rate = ret_n / last_n if last_n else 0.0
    return rate, last_n, ret_n


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def main() -> None:
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    config = load_config(config_path)
    limit_num = int(os.environ.get("ARCHERY_ORG_ID_LIMIT", "500000"))

    scenarios = [
        {
            "name": "03月第5周「本周」列 = 上周→本周（3/23-29 → 3/30～4/5）",
            "lw": ("2026-03-23", "2026-03-29"),
            "tw": ("2026-03-30", "2026-04-05"),
        },
        {
            "name": "03月第5周「上周」列 = 前上周→上周（3/16-22 → 3/23-29）",
            "lw": ("2026-03-16", "2026-03-22"),
            "tw": ("2026-03-23", "2026-03-29"),
        },
        {
            "name": "04月第2周「本周」列 = 上周→本周（3/30～4/5 → 4/6-12）",
            "lw": ("2026-03-30", "2026-04-05"),
            "tw": ("2026-04-06", "2026-04-12"),
        },
    ]

    print(f"Archery org_id 拉取 limit_num={limit_num}（可用环境变量 ARCHERY_ORG_ID_LIMIT 调整）\n")

    for sc in scenarios:
        lw_s, lw_e = sc["lw"]
        tw_s, tw_e = sc["tw"]
        print("=" * 72)
        print(sc["name"])
        print(f"  last_week: {lw_s} ~ {lw_e}")
        print(f"  this_week: {tw_s} ~ {tw_e}")

        r_sum, n_last_sum, n_ret_sum = retention_sum_method(config, lw_s, lw_e, tw_s, tw_e)
        r_ded, n_last_ded, n_ret_ded = retention_deduped_method(config, lw_s, lw_e, tw_s, tw_e, limit_num)

        print(f"  [分实例相加] 上周活跃={int(n_last_sum):d} 留存={int(n_ret_sum):d} 留存率={pct(r_sum)}")
        print(f"  [并集去重]   上周活跃={n_last_ded:d} 留存={n_ret_ded:d} 留存率={pct(r_ded)}")
        delta_pp = (r_ded - r_sum) * 100
        print(f"  差值(去重−相加): {delta_pp:+.3f} 个百分点")

        if abs(r_ded - r_sum) > 1e-6:
            print("  → 两种算法结果不一致：存在跨实例重复 org_id 或其它统计差异，以「并集去重」为准更贴近全局口径。")
        else:
            print("  → 两种算法一致（或差异可忽略）。")
        print()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
查询委外管理第3周到第4周留存的客户ID列表
第3周：2026-03-16 ~ 2026-03-22
第4周：2026-03-23 ~ 2026-03-29

注：此脚本与周报逻辑一致，按实例分别计数后汇总（不去重）
"""

import json
import requests
from typing import List, Tuple

def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

def post_sql(config: dict, instance: str, sql: str):
    url = config["archery_url"]
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": config["auth"]["csrftoken"],
        "Cookie": f"csrftoken={config['auth']['csrftoken']}; sessionid={config['auth']['sessionid']}",
    }
    data = {
        "instance_name": instance,
        "db_name": config["db_name"],
        "schema_name": config["schema_name"],
        "tb_name": config.get("tb_name", "dt_outsource_order"),
        "sql_content": sql,
        "limit_num": config.get("limit_num", 10000),
    }
    resp = requests.post(url, headers=headers, data=data, timeout=60)
    resp.raise_for_status()
    return resp.json()

def parse_value(payload, key: str) -> float:
    """从Archery返回中提取单个数值"""
    if isinstance(payload, dict) and "data" in payload:
        data = payload["data"]
        if isinstance(data, dict) and "rows" in data and "column_list" in data:
            rows = data["rows"]
            columns = data["column_list"]
            if rows and len(rows[0]) > 0:
                try:
                    idx = columns.index(key)
                    return float(rows[0][idx])
                except (ValueError, IndexError):
                    pass
    return 0.0

def query_retention_counts(config: dict, instance: str, lw_start: str, lw_end: str, tw_start: str, tw_end: str) -> Tuple[float, float]:
    """查询留存率计数（与周报逻辑一致）"""
    sql = f"""
WITH last_week_orders AS (
    SELECT DISTINCT org_id FROM dt_outsource_order
    WHERE DATE(created_at) BETWEEN DATE '{lw_start}' AND DATE '{lw_end}'
),
last_week_posts AS (
    SELECT DISTINCT org_id FROM dt_outsource_post
    WHERE DATE(created_at) BETWEEN DATE '{lw_start}' AND DATE '{lw_end}'
),
last_week_active AS (
    SELECT o.org_id FROM last_week_orders o JOIN last_week_posts p USING(org_id)
),
this_week_orders AS (
    SELECT DISTINCT org_id FROM dt_outsource_order
    WHERE DATE(created_at) BETWEEN DATE '{tw_start}' AND DATE '{tw_end}'
),
this_week_posts AS (
    SELECT DISTINCT org_id FROM dt_outsource_post
    WHERE DATE(created_at) BETWEEN DATE '{tw_start}' AND DATE '{tw_end}'
),
this_week_active AS (
    SELECT o.org_id FROM this_week_orders o JOIN this_week_posts p USING(org_id)
),
retained AS (
    SELECT l.org_id FROM last_week_active l JOIN this_week_active t ON l.org_id = t.org_id
)
SELECT
    (SELECT COUNT(*) FROM last_week_active) AS last_week_customers,
    (SELECT COUNT(*) FROM retained) AS retained_customers;
""".strip()

    result = post_sql(config, instance, sql)
    last_week = parse_value(result, "last_week_customers")
    retained = parse_value(result, "retained_customers")
    return last_week, retained

def query_retained_customer_ids(config: dict, instance: str, lw_start: str, lw_end: str, tw_start: str, tw_end: str) -> List[str]:
    """查询具体留存的客户ID列表"""
    sql = f"""
WITH last_week_orders AS (
    SELECT DISTINCT org_id FROM dt_outsource_order
    WHERE DATE(created_at) BETWEEN DATE '{lw_start}' AND DATE '{lw_end}'
),
last_week_posts AS (
    SELECT DISTINCT org_id FROM dt_outsource_post
    WHERE DATE(created_at) BETWEEN DATE '{lw_start}' AND DATE '{lw_end}'
),
last_week_active AS (
    SELECT o.org_id FROM last_week_orders o JOIN last_week_posts p USING(org_id)
),
this_week_orders AS (
    SELECT DISTINCT org_id FROM dt_outsource_order
    WHERE DATE(created_at) BETWEEN DATE '{tw_start}' AND DATE '{tw_end}'
),
this_week_posts AS (
    SELECT DISTINCT org_id FROM dt_outsource_post
    WHERE DATE(created_at) BETWEEN DATE '{tw_start}' AND DATE '{tw_end}'
),
this_week_active AS (
    SELECT o.org_id FROM this_week_orders o JOIN this_week_posts p USING(org_id)
),
retained AS (
    SELECT l.org_id FROM last_week_active l JOIN this_week_active t ON l.org_id = t.org_id
)
SELECT org_id FROM retained ORDER BY org_id;
""".strip()

    result = post_sql(config, instance, sql)
    if isinstance(result, dict) and "data" in result:
        data = result["data"]
        if isinstance(data, dict) and "rows" in data:
            return [str(row[0]) for row in data["rows"] if row]
    return []

def main():
    config = load_config()

    # 第3周：2026-03-16 ~ 2026-03-22
    # 第4周：2026-03-23 ~ 2026-03-29
    lw_start, lw_end = "2026-03-16", "2026-03-22"
    tw_start, tw_end = "2026-03-23", "2026-03-29"

    instances = config["instances"]

    print(f"查询委外管理第3周到第4周留存的客户...")
    print(f"第3周：{lw_start} ~ {lw_end}")
    print(f"第4周：{tw_start} ~ {tw_end}")
    print(f"数据库实例：{instances}")
    print("-" * 60)

    total_last_week = 0
    total_retained = 0
    all_retained_ids = []

    for instance in instances:
        print(f"\n查询实例: {instance}")
        try:
            # 查询计数
            last_week_count, retained_count = query_retention_counts(
                config, instance, lw_start, lw_end, tw_start, tw_end
            )
            print(f"  第3周活跃客户: {int(last_week_count)}")
            print(f"  第4周留存客户: {int(retained_count)}")
            print(f"  实例留存率: {retained_count/last_week_count*100:.1f}%" if last_week_count > 0 else "  实例留存率: N/A")

            total_last_week += last_week_count
            total_retained += retained_count

            # 查询客户ID
            retained_ids = query_retained_customer_ids(
                config, instance, lw_start, lw_end, tw_start, tw_end
            )
            all_retained_ids.extend(retained_ids)

        except Exception as e:
            print(f"  查询失败: {e}")

    print("\n" + "=" * 60)
    print(f"【与周报一致的结果（按实例计数汇总）】")
    print(f"第3周活跃客户总数: {int(total_last_week)}")
    print(f"第4周留存客户总数: {int(total_retained)}")
    print(f"留存率: {total_retained/total_last_week*100:.1f}%")

    print(f"\n【客户ID列表（各实例合并，共{len(all_retained_ids)}条记录）】")
    print(f"说明：同一客户可能在多个实例中出现")

    # 按实例分组显示
    idx = 0
    for instance in instances:
        try:
            retained_ids = query_retained_customer_ids(
                config, instance, lw_start, lw_end, tw_start, tw_end
            )
            if retained_ids:
                print(f"\n  [{instance}] {len(retained_ids)}个客户:")
                for i in range(0, len(retained_ids), 10):
                    batch = retained_ids[i:i+10]
                    print(f"    {', '.join(batch)}")
        except Exception as e:
            print(f"\n  [{instance}] 查询失败: {e}")

if __name__ == "__main__":
    main()

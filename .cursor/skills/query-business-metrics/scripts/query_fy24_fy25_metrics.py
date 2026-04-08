#!/usr/bin/env python3
"""
财年代表周指标；日期窗为下方 WINDOWS，与
`.cursor/skills/query-business-metrics/reference-tables.md`「财年与代表周」中的 **B. 财年代表周** 一致。

FY24：2025-03-24 ~ 2025-03-30（仅协同任务、委外管理）
FY25：2026-03-23 ~ 2026-03-29

- 小工单 TV / 自定义报表访问 / 智能看板访问：仅统计 FY25（不查 FY24）。
- 协同任务、委外：FY24 + FY25，并计算环比 (FY25−FY24)/FY24。

自定义报表、智能看板：
  - 「一周内访问过」：PageView + reference-tables 已映射 url 条件，窗内 COUNT(DISTINCT orgId)（至少 1 次即可）。
  - 「不少于 2 天」：同上 + 同一 orgId 的 COUNT(DISTINCT dat) >= 2。
  - url：`get_json_string(eventValues, '$.url')`，条件见 reference-tables「自定义报表（访问）」「智能看板（访问）」。

TV「不少于 2 天」：event='tv-device-info'，按工厂 orgId 去重日期数≥2。

委外：FY24/FY25 统一为窗内 `dt_outsource_post` 存在 **收货**（post_type_name='收货'）的工厂，ADB 三实例 org_id 去重。
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Set, Tuple


def _repo_root() -> Path:
    """定位仓库根（存在「查询指标」目录的祖先）。"""
    p = Path(__file__).resolve().parent
    for _ in range(16):
        if (p / "查询指标").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    raise RuntimeError("找不到「查询指标」目录：请从本仓库内运行脚本。")


OUTPUT_DIR = _repo_root() / "查询指标"

CONFIG = {
    "archery_url": "https://archery.blacklake.tech/query/",
    "db_name": "liteman",
    "schema_name": "public",
    "limit_num": 500000,
    "instances_adb": [
        "小工单_阿里云_prod_ADB_01",
        "小工单_阿里云_prod_ADB_02",
        "小工单_阿里云_prod_ADB_03",
    ],
    "instance_starrocks": "小工单_阿里云_prod_starrocks",
    "auth": {
        "csrftoken": "h9zA8KXL8gCEJHqgaca737KSZR6Aae9jxb8BhPie6AYuuO0FJVtQs570O59OnvYd",
        "sessionid": "1i62cj8az2bbynzzdhf5if78zkonkv8d",
    },
}

WINDOWS = {
    "FY24": ("2025-03-24", "2025-03-30"),
    "FY25": ("2026-03-23", "2026-03-29"),
}


def post_sql(instance_name: str, tb_name: str, sql: str) -> dict:
    auth = CONFIG["auth"]
    csrf = auth["csrftoken"]
    sessionid = auth["sessionid"]
    data = {
        "instance_name": instance_name,
        "db_name": CONFIG["db_name"],
        "schema_name": CONFIG["schema_name"],
        "tb_name": tb_name,
        "sql_content": sql,
        "limit_num": str(CONFIG["limit_num"]),
    }
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(CONFIG["archery_url"], data=encoded, method="POST")
    req.add_header("content-type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("x-csrftoken", csrf)
    req.add_header("cookie", f"csrftoken={csrf}; sessionid={sessionid}")
    req.add_header("x-requested-with", "XMLHttpRequest")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rows(payload: dict) -> Tuple[List[str], List[list]]:
    data = payload.get("data") or {}
    return data.get("column_list") or [], data.get("rows") or []


def fetch_org_ids(sql: str, tb_name: str) -> Set[str]:
    merged: Set[str] = set()
    for inst in CONFIG["instances_adb"]:
        payload = post_sql(inst, tb_name, sql)
        if payload.get("status") != 0:
            raise RuntimeError(f"{inst}: {payload.get('msg')}")
        column_list, data_rows = rows(payload)
        if not column_list:
            continue
        idx = column_list.index("org_id")
        for r in data_rows:
            if r and r[idx] is not None:
                merged.add(str(int(r[idx])) if not isinstance(r[idx], str) else r[idx])
    return merged


def fetch_count_starrocks(sql: str) -> int:
    payload = post_sql(CONFIG["instance_starrocks"], "trace_log_dp", sql)
    if payload.get("status") != 0:
        raise RuntimeError(payload.get("msg"))
    _, data_rows = rows(payload)
    if not data_rows or data_rows[0][0] is None:
        return 0
    return int(data_rows[0][0])


def pct_change(cur: float, prev: float) -> str:
    if prev == 0:
        return "N/A"
    return f"{(cur - prev) / prev * 100:.1f}%"


def sql_tv_2day(ws: str, we: str) -> str:
    return f"""
SELECT COUNT(*) AS c FROM (
  SELECT orgId
  FROM trace_log_dp
  WHERE dat BETWEEN DATE '{ws}' AND DATE '{we}'
    AND event = 'tv-device-info'
  GROUP BY orgId
  HAVING COUNT(DISTINCT dat) >= 2
) x
""".strip()


def sql_pageview_distinct_orgs(ws: str, we: str, url_like: str) -> str:
    """窗内至少 1 次匹配 PageView 的去重工厂数。"""
    return f"""
SELECT COUNT(DISTINCT orgId) AS c
FROM trace_log_dp
WHERE dat BETWEEN DATE '{ws}' AND DATE '{we}'
  AND event = 'PageView'
  AND get_json_string(eventValues, '$.url') LIKE '{url_like}'
""".strip()


def sql_pageview_2day(ws: str, we: str, url_like: str) -> str:
    # url_like 传入已含 SQL 转义或单引号由调用方保证——使用 % 通配
    return f"""
SELECT COUNT(*) AS c FROM (
  SELECT orgId
  FROM trace_log_dp
  WHERE dat BETWEEN DATE '{ws}' AND DATE '{we}'
    AND event = 'PageView'
    AND get_json_string(eventValues, '$.url') LIKE '{url_like}'
  GROUP BY orgId
  HAVING COUNT(DISTINCT dat) >= 2
) x
""".strip()


def sql_collab_2day(ws: str, we: str) -> str:
    return f"""
SELECT org_id FROM (
  SELECT org_id, COUNT(DISTINCT DATE(created_at)) AS d
  FROM dt_collaborative_task
  WHERE DATE(created_at) BETWEEN DATE '{ws}' AND DATE '{we}'
  GROUP BY org_id
) t WHERE d >= 2
""".strip()


def sql_outsource_shou_huo_orgs(ws: str, we: str) -> str:
    """窗内有过「收货」过账的工厂（仅 dt_outsource_post）。"""
    return f"""
SELECT DISTINCT org_id
FROM dt_outsource_post
WHERE post_type_name = '收货'
  AND DATE(created_at) BETWEEN DATE '{ws}' AND DATE '{we}'
  AND COALESCE(deleted_at, 0) = 0
""".strip()


def main() -> None:
    s24, e24 = WINDOWS["FY24"]
    s25, e25 = WINDOWS["FY25"]

    # —— 仅 FY25：TV、自定义 PageView、智能 PageView ——
    tv_fy25 = fetch_count_starrocks(sql_tv_2day(s25, e25))
    custom_url = "%/customDashboard/detail%"
    intel_url = "%/intelligentDashboard/detail/%"
    custom_fy25_visited = fetch_count_starrocks(sql_pageview_distinct_orgs(s25, e25, custom_url))
    custom_fy25 = fetch_count_starrocks(sql_pageview_2day(s25, e25, custom_url))
    intel_fy25 = fetch_count_starrocks(sql_pageview_2day(s25, e25, intel_url))

    # —— FY24 / FY25：协同、委外 ——
    c24 = fetch_org_ids(sql_collab_2day(s24, e24), "dt_collaborative_task")
    c25 = fetch_org_ids(sql_collab_2day(s25, e25), "dt_collaborative_task")
    o24 = fetch_org_ids(sql_outsource_shou_huo_orgs(s24, e24), "dt_outsource_post")
    o25 = fetch_org_ids(sql_outsource_shou_huo_orgs(s25, e25), "dt_outsource_post")

    n_c24, n_c25 = len(c24), len(c25)
    n_o24, n_o25 = len(o24), len(o25)

    out_json = {
        "时间窗": {
            "FY24": [s24, e24],
            "FY25": [s25, e25],
        },
        "说明": {
            "小工单TV版": "tv-device-info，工厂 orgId 在窗内出现日期数≥2；仅 FY25。",
            "自定义报表_周内访问过": "PageView + 自定义报表 url（reference-tables）；窗内 COUNT(DISTINCT orgId)；仅 FY25。",
            "自定义报表_不少于2天": "同上，且各 org 的 dat 去重数≥2；仅 FY25。",
            "智能看板": "PageView + 智能看板 url（reference-tables）；仅 FY25。",
            "协同任务": "dt_collaborative_task.created_at，窗内不少于2个自然日有创建；跨 ADB 实例 org_id 去重；FY24+FY25。",
            "委外管理": "dt_outsource_post 窗内 post_type_name=收货；COALESCE(deleted_at,0)=0；FY24+FY25 同口径；跨实例去重。",
            "环比": "(FY25−FY24)/FY24，仅协同与委外。",
        },
        "metrics": {
            "小工单TV版_周内使用不少于2天工厂数": {"FY25": tv_fy25},
            "自定义报表_周内访问过的工厂数": {"FY25": custom_fy25_visited},
            "自定义报表_周内访问PageView不少于2天工厂数": {"FY25": custom_fy25},
            "智能看板_周内访问PageView不少于2天工厂数": {"FY25": intel_fy25},
            "协同任务_周内创建任务不少于2天工厂数": {
                "FY24": n_c24,
                "FY25": n_c25,
                "环比": pct_change(float(n_c25), float(n_c24)),
            },
            "委外管理_周内有过收货的工厂数": {
                "FY24": n_o24,
                "FY25": n_o25,
                "环比": pct_change(float(n_o25), float(n_o24)),
            },
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "FY24_FY25_指标.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)

    md_lines = [
        "# 财年代表周指标（见 reference-tables「财年与代表周」·B）",
        "",
        "## 时间窗",
        f"- **FY24**：{s24} ~ {e24}",
        f"- **FY25**：{s25} ~ {e25}",
        "",
        "## 仅 FY25（不对比 FY24）",
        "",
        "| 模块 | 指标 | FY25 |",
        "|------|------|------|",
        f"| 小工单TV版 | 一周内使用不少于 2 天（tv-device-info）的工厂 | **{tv_fy25}** |",
        f"| 自定义报表 | 一周内访问过（PageView，customDashboard/detail）的工厂 | **{custom_fy25_visited}** |",
        f"| 自定义报表 | 一周内访问不少于 2 天的工厂（同上路径） | **{custom_fy25}** |",
        f"| 智能看板 | 一周内访问（PageView，intelligentDashboard/detail）不少于 2 天的工厂 | **{intel_fy25}** |",
        "",
        "## FY24 / FY25 + 环比",
        "",
        "| 模块 | 指标 | FY24 | FY25 | 环比 |",
        "|------|------|------|------|------|",
        f"| 协同任务 | 一周内创建任务不少于 2 天的工厂 | {n_c24} | {n_c25} | {pct_change(float(n_c25), float(n_c24))} |",
        f"| 委外管理 | 一周内有过 **收货** 过账的工厂 | {n_o24} | {n_o25} | {pct_change(float(n_o25), float(n_o24))} |",
        "",
        "## 口径摘要",
        "- **TV / 报表 / 智能看板**：埋点在 StarRocks `trace_log_dp`，条件见 `reference-tables.md`。",
        "- **协同 / 委外**：PostgreSQL（ADB 三实例）`org_id` 并集后去重计数；**委外** 仅看 `dt_outsource_post`、类型为 **收货**。",
        "- **协同任务环比 N/A**：FY24 窗口内该指标为 0，分母为 0 不计算环比。",
    ]
    md_path = OUTPUT_DIR / "FY24_FY25_指标.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print(f"Wrote {json_path}\nWrote {md_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""
25 财年：自定义报表 / 智能看板 —— 筛选组件配置了「默认值」的工厂数。

数据来源：dt_custom_filter_info.filter_condition（JSON 数组），
至少一条元素含键 defaultValueInfo（jsonb_path_exists 判断，与 LIKE '%defaultValueInfo%' 在样例库上一致）。

关联：dt_custom_dashboard（同 org_id、dashboard_id = id），dashboard_type 1=自定义报表，3=智能看板。

时间窗：与 `reference-tables.md`「财年与代表周」·**A. 原 FYI 财年窗** 之 25 财年一致（下表 FY25_START / FY25_END）。
  - 全量：不限制时间，仅当前未删除记录。
  - 财年内有变更：filter 行 created_at 或 updated_at 落在该窗内（保存默认值通常会更新 updated_at）。

输出：仓库根目录「查询指标/」下 FY25_筛选组件默认值_工厂数.md / .json
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Set, Tuple


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
    "auth": {
        "csrftoken": "h9zA8KXL8gCEJHqgaca737KSZR6Aae9jxb8BhPie6AYuuO0FJVtQs570O59OnvYd",
        "sessionid": "1i62cj8az2bbynzzdhf5if78zkonkv8d",
    },
}

# 25 财年窗（reference-tables · A；与 query_fy24_fy25_metrics WINDOWS 不同）
FY25_START = "2026-03-30"
FY25_END = "2026-04-05"

# JSON：数组中某条筛选含 defaultValueInfo
JSONPATH_HAS_DEFAULT = r"$[*] ? (@.defaultValueInfo != null)"


def post_sql(instance_name: str, tb_name: str, sql: str) -> dict:
    auth = CONFIG["auth"]
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
    req.add_header("x-csrftoken", auth["csrftoken"])
    req.add_header(
        "cookie",
        f"csrftoken={auth['csrftoken']}; sessionid={auth['sessionid']}",
    )
    req.add_header("x-requested-with", "XMLHttpRequest")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rows(payload: dict) -> Tuple[List[str], list]:
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


def sql_orgs(
    dashboard_type: int,
    fy25_window_only: bool,
) -> str:
    date_pred = ""
    if fy25_window_only:
        date_pred = f"""
  AND (
    DATE(f.updated_at) BETWEEN DATE '{FY25_START}' AND DATE '{FY25_END}'
    OR DATE(f.created_at) BETWEEN DATE '{FY25_START}' AND DATE '{FY25_END}'
  )
""".rstrip()
    return f"""
SELECT DISTINCT f.org_id
FROM dt_custom_filter_info f
INNER JOIN dt_custom_dashboard d
  ON d.id = f.dashboard_id AND d.org_id = f.org_id
WHERE COALESCE(f.deleted_at, 0) = 0
  AND COALESCE(d.deleted_at, 0) = 0
  AND d.dashboard_type = {dashboard_type}
  AND jsonb_path_exists(
    f.filter_condition::jsonb,
    '{JSONPATH_HAS_DEFAULT}'
  )
{date_pred}
""".strip()


def main() -> None:
    out: dict = {
        "25财年时间窗": [FY25_START, FY25_END],
        "dt_custom_filter_info_列说明": [
            "id",
            "org_id",
            "dashboard_id",
            "name",
            "filter_condition（json/jsonb：筛选与图表映射，含 defaultValueInfo 表示默认值）",
            "deleted_at",
            "created_at",
            "updated_at",
            "creator_id",
            "operator_id",
        ],
        "默认值判定": (
            "jsonb_path_exists(filter_condition::jsonb, "
            "'$[*] ? (@.defaultValueInfo != null)') — 与业务样例中 defaultValueInfo 块一致"
        ),
        "metrics": {},
    }
    metrics = out["metrics"]

    for dtype, label in ((1, "自定义报表"), (3, "智能看板")):
        all_orgs = fetch_org_ids(sql_orgs(dtype, fy25_window_only=False), "dt_custom_filter_info")
        win_orgs = fetch_org_ids(sql_orgs(dtype, fy25_window_only=True), "dt_custom_filter_info")
        metrics[label] = {
            "全量_当前有效_有默认值配置的工厂数": len(all_orgs),
            "FY25窗内_筛选记录新建或更新_且有默认值的工厂数": len(win_orgs),
        }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "FY25_筛选组件默认值_工厂数.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    m = metrics
    md = f"""# FY25 筛选组件默认值 — 工厂数（`dt_custom_filter_info`）

## 25 财年时间窗（`reference-tables.md` · A）

- **{FY25_START}** ~ **{FY25_END}**

## 表结构摘要（`dt_custom_filter_info`）

| 列 | 含义 |
|----|------|
| org_id | 工厂 |
| dashboard_id | 关联 `dt_custom_dashboard.id` |
| filter_condition | JSON 数组：筛选配置；元素含 **defaultValueInfo** 时表示配置了默认值（如 conditionValue / conditionName 等） |
| deleted_at / created_at / updated_at | 软删与时间 |

## 指标（ADB 01+02+03，`org_id` 去重）

| 模块 | 全量：当前未删除且存在默认值配置 | FY25 窗内：该表 created_at **或** updated_at 落在窗内 |
|------|----------------------------------|------------------------------------------------------|
| 自定义报表（dashboard_type=1） | **{m["自定义报表"]["全量_当前有效_有默认值配置的工厂数"]}** | **{m["自定义报表"]["FY25窗内_筛选记录新建或更新_且有默认值的工厂数"]}** |
| 智能看板（dashboard_type=3） | **{m["智能看板"]["全量_当前有效_有默认值配置的工厂数"]}** | **{m["智能看板"]["FY25窗内_筛选记录新建或更新_且有默认值的工厂数"]}** |

## SQL 模板（单实例）

**全量 + 自定义报表：**

```sql
SELECT DISTINCT f.org_id
FROM dt_custom_filter_info f
INNER JOIN dt_custom_dashboard d
  ON d.id = f.dashboard_id AND d.org_id = f.org_id
WHERE COALESCE(f.deleted_at, 0) = 0
  AND COALESCE(d.deleted_at, 0) = 0
  AND d.dashboard_type = 1
  AND jsonb_path_exists(
    f.filter_condition::jsonb,
    '$[*] ? (@.defaultValueInfo != null)'
  );
```

智能看板将 `dashboard_type = 3`。若只统计 FY25 窗内变更，增加：

```sql
  AND (
    DATE(f.updated_at) BETWEEN DATE '{FY25_START}' AND DATE '{FY25_END}'
    OR DATE(f.created_at) BETWEEN DATE '{FY25_START}' AND DATE '{FY25_END}'
  )
```

## 口径说明

- **默认值**：以 JSON 中存在 **defaultValueInfo** 为准；未再强制要求数组非空（若需排除「仅占位」需产品侧补充规则）。
- **与图表组件**：`filter_condition` 内 `associatedCharts` 会挂图表；本条统计面向「筛选配置里带默认值的行」，不限于纯筛选、不含图表的配置。

数据文件：`FY25_筛选组件默认值_工厂数.json`
"""
    md_path = OUTPUT_DIR / "FY25_筛选组件默认值_工厂数.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"Wrote {json_path}\nWrote {md_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

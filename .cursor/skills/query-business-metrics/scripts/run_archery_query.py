#!/usr/bin/env python3
"""
通用 Archery 查询：换实例、表名、SQL 与模板变量即可，无需为单次查数新建脚本。

鉴权默认读取：.cursor/skills/weekly-core-metrics/scripts/config.json（勿将 token 提交进仓库）。

示例：

  python3 .cursor/skills/query-business-metrics/scripts/run_archery_query.py \\
    --instance 小工单_阿里云_prod_starrocks \\
    --table trace_log_dp \\
    --sql-file query.sql \\
    --var start=2026-03-01 --var end=2026-03-31

SQL 中可使用 {start}、{end} 等占位符（Python str.format）；字面量花括号写成 {{、}}。

ADB 三实例合并 org_id（并集去重个数），SQL 须每行返回待合并列（默认 org_id）：

  python3 .../run_archery_query.py --adb-merge --table dt_outsource_post \\
    --sql "SELECT DISTINCT org_id FROM dt_outsource_post WHERE ... LIMIT 100000"
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Set, Tuple

ADB_INSTANCES = [
    "小工单_阿里云_prod_ADB_01",
    "小工单_阿里云_prod_ADB_02",
    "小工单_阿里云_prod_ADB_03",
]


def repo_root() -> Path:
    p = Path(__file__).resolve().parent
    for _ in range(16):
        if (p / "查询指标").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    return Path.cwd()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def default_config_path() -> Path:
    return repo_root() / ".cursor/skills/weekly-core-metrics/scripts/config.json"


def post_sql(
    cfg: dict,
    instance_name: str,
    tb_name: str,
    sql: str,
    limit: str = "500000",
    timeout: int = 180,
) -> dict:
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


def parse_var_pair(raw: str) -> Tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"变量须为 KEY=VALUE，收到: {raw!r}")
    k, v = raw.split("=", 1)
    k = k.strip()
    if not k:
        raise argparse.ArgumentTypeError(f"变量名不能为空: {raw!r}")
    return k, v.strip()


def load_sql_text(args: argparse.Namespace) -> str:
    if args.sql and args.sql_file:
        raise SystemExit("请只指定 --sql 或 --sql-file 之一")
    if args.sql:
        return args.sql
    if args.sql_file:
        path = Path(args.sql_file).expanduser()
        if not path.is_file():
            raise SystemExit(f"找不到 SQL 文件: {path}")
        return path.read_text(encoding="utf-8")
    raise SystemExit("必须提供 --sql 或 --sql-file")


def apply_format(sql: str, variables: Dict[str, str]) -> str:
    if not variables:
        return sql
    try:
        return sql.format(**variables)
    except KeyError as e:
        raise SystemExit(f"SQL 中占位符缺少对应 --var：{e}") from e


def load_config(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"找不到配置文件: {path}")
    cfg = load_json(path)
    if "archery_url" not in cfg or "auth" not in cfg:
        raise SystemExit("配置文件须含 archery_url、auth（csrftoken、sessionid）")
    return cfg


def run_single(cfg: dict, instance: str, tb_name: str, sql: str, limit: str, timeout: int) -> dict:
    return post_sql(cfg, instance, tb_name, sql, limit=limit, timeout=timeout)


def merged_org_ids(
    cfg: dict,
    tb_name: str,
    sql: str,
    limit: str,
    timeout: int,
    merge_column: str,
) -> Tuple[Set[str], List[dict]]:
    merged: Set[str] = set()
    per_inst: List[dict] = []
    for inst in ADB_INSTANCES:
        payload = run_single(cfg, inst, tb_name, sql, limit, timeout)
        rec: dict = {"instance": inst, "status": payload.get("status"), "msg": payload.get("msg")}
        if payload.get("status") != 0:
            per_inst.append(rec)
            raise RuntimeError(f"{inst}: {payload.get('msg')}")
        cols, data_rows = rows(payload)
        rec["row_count"] = len(data_rows)
        if merge_column not in cols:
            raise RuntimeError(f"{inst}: 结果中无列 {merge_column!r}，实际列: {cols}")
        idx = cols.index(merge_column)
        for r in data_rows:
            if r and r[idx] is not None:
                v = r[idx]
                merged.add(str(int(v)) if not isinstance(v, str) else v)
        per_inst.append(rec)
    return merged, per_inst


def main() -> None:
    p = argparse.ArgumentParser(description="通用 Archery 查询（单实例或 ADB org_id 合并）")
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"含 archery_url / auth / db_name 的 JSON，默认 {default_config_path()}",
    )
    p.add_argument("--instance", help="Archery instance_name（与 --adb-merge 互斥）")
    p.add_argument("--table", dest="tb_name", help="Archery tb_name（如 trace_log_dp）")
    p.add_argument("--sql", help="SQL 字符串（与 --sql-file 二选一）")
    p.add_argument("--sql-file", help="SQL 文件；内容可用 {KEY} 占位符，由 --var KEY=VAL 替换")
    p.add_argument(
        "--var",
        dest="variables",
        action="append",
        default=[],
        type=parse_var_pair,
        metavar="KEY=VALUE",
        help="SQL 模板变量，可重复",
    )
    p.add_argument("--limit", default="500000", help="Archery limit_num")
    p.add_argument("--timeout", type=int, default=180, help="请求超时秒数")
    p.add_argument("--adb-merge", action="store_true", help="ADB 01/02/03 同 SQL 合并 org_id")
    p.add_argument("--merge-column", default="org_id", help="--adb-merge 时去重列名")
    p.add_argument(
        "--output",
        type=Path,
        help="可选：将 Archery 原始 JSON 写入文件（调试）；指标结论请写入 查询指标/*.md",
    )
    p.add_argument(
        "--stdout-format",
        choices=["json", "scalar"],
        default="json",
        help="scalar：仅 1 行 1 列时打印标量",
    )
    args = p.parse_args()

    cfg_path = args.config if args.config is not None else default_config_path()
    cfg = load_config(cfg_path)
    tb_name = args.tb_name
    if not tb_name:
        raise SystemExit("必须指定 --table")

    sql_raw = load_sql_text(args)
    variables = dict(args.variables)
    sql = apply_format(sql_raw, variables)

    out: dict = {
        "meta": {
            "config": str(cfg_path),
            "tb_name": tb_name,
            "adb_merge": bool(args.adb_merge),
            "variables": variables,
        },
        "sql_executed": sql,
    }

    if args.adb_merge:
        if args.instance:
            raise SystemExit("--adb-merge 时不要传 --instance")
        merged, per_inst = merged_org_ids(
            cfg, tb_name, sql, args.limit, args.timeout, args.merge_column
        )
        out["result"] = {
            "merged_distinct_count": len(merged),
            "merge_column": args.merge_column,
            "per_instance": per_inst,
        }
        if args.stdout_format == "scalar":
            print(len(merged))
        else:
            print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if not args.instance:
            raise SystemExit("单实例查询必须指定 --instance（或用 --adb-merge）")
        payload = run_single(cfg, args.instance, tb_name, sql, args.limit, args.timeout)
        out["archery_status"] = payload.get("status")
        out["archery_msg"] = payload.get("msg")
        cols, data_rows = rows(payload)
        out["column_list"] = cols
        out["rows"] = data_rows
        if payload.get("status") != 0:
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            raise SystemExit(f"Archery 错误: {payload.get('msg')}")

        if args.stdout_format == "scalar" and len(cols) == 1 and len(data_rows) == 1:
            v = data_rows[0][0]
            print("null" if v is None else v)
        else:
            print(json.dumps(out, ensure_ascii=False, indent=2))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n# 已写入 {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()

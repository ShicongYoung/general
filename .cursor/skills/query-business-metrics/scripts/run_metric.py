#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


SKILL_ROOT = Path(__file__).resolve().parent.parent
ROOT = SKILL_ROOT
for _ in range(16):
    if (ROOT / "查询指标").is_dir():
        break
    ROOT = ROOT.parent
else:
    ROOT = Path.cwd()

RUN_ARCHERY = SKILL_ROOT / "scripts/run_archery_query.py"
REGISTRY = SKILL_ROOT / "metrics/registry.json"

ADB_INSTANCES = [
    "小工单_阿里云_prod_ADB_01",
    "小工单_阿里云_prod_ADB_02",
    "小工单_阿里云_prod_ADB_03",
]


def read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def parse_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def as_int(v: Any) -> int:
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    return int(str(v))


def run_archery(instance: str, tb_name: str, sql: str, limit: int = 500000) -> dict:
    cmd = [
        sys.executable,
        str(RUN_ARCHERY),
        "--instance",
        instance,
        "--table",
        tb_name,
        "--sql",
        sql,
        "--limit",
        str(limit),
    ]
    p = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(p.stdout)


def rows(payload: dict) -> Tuple[List[str], List[list]]:
    return payload.get("column_list") or [], payload.get("rows") or []


def registry() -> dict:
    reg = read_json(REGISTRY)
    if reg.get("schema_version") != 1:
        raise SystemExit(f"metric registry schema_version 仅支持 1，收到: {reg.get('schema_version')}")
    return reg


def resolve_metric(metric_id: str) -> dict:
    reg = registry()
    m = (reg.get("metrics") or {}).get(metric_id)
    if not m:
        known = ", ".join(sorted((reg.get("metrics") or {}).keys()))
        raise SystemExit(f"未知 metric: {metric_id}。已知: {known}")
    return m


def fmt_sql(sql: str, start: date, end_excl: date) -> str:
    return sql.format(start=start.isoformat(), end_excl=end_excl.isoformat())


def exec_sum_scalar_adb(tb_name: str, sql: str) -> int:
    total = 0
    for inst in ADB_INSTANCES:
        payload = run_archery(inst, tb_name, sql, limit=200000)
        cols, data_rows = rows(payload)
        if len(cols) != 1 or not data_rows:
            raise SystemExit(f"{inst}: 期望 1 列标量结果，实际列: {cols}, rows: {len(data_rows)}")
        total += as_int(data_rows[0][0])
    return total


def exec_union_distinct_count_adb(tb_name: str, sql: str, merge_column: str) -> int:
    merged: Set[str] = set()
    for inst in ADB_INSTANCES:
        payload = run_archery(inst, tb_name, sql, limit=500000)
        cols, data_rows = rows(payload)
        if merge_column not in cols:
            raise SystemExit(f"{inst}: 结果缺少列 {merge_column}，实际: {cols}")
        idx = cols.index(merge_column)
        for r in data_rows:
            v = r[idx]
            if v is None:
                continue
            merged.add(str(as_int(v)))
    return len(merged)


def render_md(metric_id: str, meta: dict, start: date, end: date, value: Any, sql_executed: str) -> str:
    return "\n".join(
        [
            "## 背景与目标",
            "",
            f"查询指标：**{metric_id}**（skills 内置 metric）",
            "",
            "## 时间范围",
            "",
            f"- 起始：{start.isoformat()}",
            f"- 结束：{end.isoformat()}",
            "",
            "## 口径",
            "",
            f"- 描述：{meta.get('description','')}",
            "",
            "## SQL（执行）",
            "",
            "```sql",
            sql_executed.strip(),
            "```",
            "",
            "## 结果",
            "",
            f"- 值：**{value}**",
            "",
            "## 复跑命令",
            "",
            "```bash",
            f"python3 .cursor/skills/query-business-metrics/scripts/run_metric.py --metric {metric_id} --start {start.isoformat()} --end {end.isoformat()} --out-md \"{meta.get('out_md_example','查询指标/xxx.md')}\"",
            "```",
            "",
        ]
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Skills 内置指标运行器（零配置：metric + 参数 → 查询指标/*.md）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-metrics", help="列出可用 metrics")

    sp_run = sub.add_parser("run", help="执行一个 metric")
    sp_run.add_argument("--metric", required=True, help="metric id（见 list-metrics）")
    sp_run.add_argument("--start", help="YYYY-MM-DD；默认 end-lookback_days_default")
    sp_run.add_argument("--end", help="YYYY-MM-DD；默认今天")
    sp_run.add_argument("--out-md", required=True, help="输出 md（写入 查询指标/…）")

    args = p.parse_args()

    if args.cmd == "list-metrics":
        reg = registry()
        metrics = reg.get("metrics") or {}
        for mid in sorted(metrics.keys()):
            d = metrics[mid] or {}
            print(f"{mid}\t{d.get('description','')}")
        return

    meta = resolve_metric(args.metric)
    end_d = parse_ymd(args.end) if args.end else date.today()
    if args.start:
        start_d = parse_ymd(args.start)
    else:
        lookback = int(meta.get("lookback_days_default") or 30)
        start_d = end_d - timedelta(days=lookback)
    if start_d > end_d:
        raise SystemExit(f"start({start_d}) 不能晚于 end({end_d})")
    end_excl = end_d + timedelta(days=1)

    mode = meta.get("mode")
    tables = meta.get("tables") or []
    if not tables:
        raise SystemExit("metric registry 需配置 tables[0] 作为 tb_name")
    tb_name = tables[0]
    sql_executed = fmt_sql(meta.get("sql") or "", start_d, end_excl)

    if mode == "sum_scalar" and meta.get("source") == "adb":
        value = exec_sum_scalar_adb(tb_name, sql_executed)
    elif mode == "union_distinct_count" and meta.get("source") == "adb":
        merge_col = meta.get("merge_column") or "org_id"
        value = exec_union_distinct_count_adb(tb_name, sql_executed, merge_col)
    else:
        raise SystemExit(f"不支持的 metric mode/source：mode={mode}, source={meta.get('source')}")

    out_md = Path(args.out_md)
    if not out_md.is_absolute():
        out_md = (ROOT / out_md).resolve()
    md = render_md(args.metric, meta, start_d, end_d, value, sql_executed)
    write_text(out_md, md)
    print(f"Wrote\n- md: {out_md}\n- value: {value}")


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


SKILL_ROOT = Path(__file__).resolve().parent.parent
ROOT = SKILL_ROOT
for _ in range(16):
    if (ROOT / "查询指标").is_dir() and (ROOT / "图表").is_dir():
        break
    ROOT = ROOT.parent
else:
    ROOT = Path.cwd()

RUN_ARCHERY = SKILL_ROOT / "scripts/run_archery_query.py"
RENDER_HTML = ROOT / ".cursor/skills/business-charts/scripts/render_dashboard_html.py"
REGISTRY = SKILL_ROOT / "dashboards/registry.json"
MANIFEST_TPL_DIR = SKILL_ROOT / "dashboards/manifest_templates"
MD_TPL_DIR = SKILL_ROOT / "dashboards/md_templates"

ADB_INSTANCES = [
    "小工单_阿里云_prod_ADB_01",
    "小工单_阿里云_prod_ADB_02",
    "小工单_阿里云_prod_ADB_03",
]


def read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def parse_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_starts(start_monday: date, end_monday: date) -> List[date]:
    out: List[date] = []
    d = start_monday
    while d <= end_monday:
        out.append(d)
        d += timedelta(days=7)
    return out


def ts_compact() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H%M%S")


def as_int(v: Any) -> int:
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    return int(str(v))


def as_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v))


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


def template_render(raw: str, vars_: Dict[str, str]) -> str:
    out = raw
    for k, v in vars_.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def registry() -> dict:
    reg = read_json(REGISTRY)
    if reg.get("schema_version") != 1:
        raise SystemExit(f"registry schema_version 仅支持 1，收到: {reg.get('schema_version')}")
    return reg


@dataclass
class RunArgs:
    recipe: str
    start: date
    end: date
    title: str
    out_data: Path
    snapshot_dir: Path
    out_html: Path
    out_md: Path
    manifest_template: Optional[str]


def resolve_recipe_meta(recipe_id: str) -> dict:
    reg = registry()
    meta = (reg.get("dashboards") or {}).get(recipe_id)
    if not meta:
        known = ", ".join(sorted((reg.get("dashboards") or {}).keys()))
        raise SystemExit(f"未知 recipe: {recipe_id}。已知: {known}")
    return meta


def load_manifest_template(template_id_or_path: str) -> str:
    p = Path(template_id_or_path)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    tp = MANIFEST_TPL_DIR / template_id_or_path
    if not tp.is_file():
        raise SystemExit(f"找不到 manifest_template: {template_id_or_path}（也不在 {MANIFEST_TPL_DIR}）")
    return tp.read_text(encoding="utf-8")


def load_md_template(template_id: str) -> str:
    tp = MD_TPL_DIR / template_id
    if not tp.is_file():
        raise SystemExit(f"找不到 md_template: {template_id}（{MD_TPL_DIR}）")
    return tp.read_text(encoding="utf-8")


# -----------------------------
# Recipes
# -----------------------------


def recipe_collab_weekly_v1(t_start: date, t_end: date) -> Tuple[dict, Dict[str, str]]:
    # 时间边界使用 created_at，闭开区间：[start_monday, end_date+1day)
    start_m = monday_of(t_start)
    end_excl = t_end + timedelta(days=1)
    end_m = monday_of(t_end)
    weeks = week_starts(start_m, end_m)

    start_ts = f"{start_m.isoformat()} 00:00:00"
    end_ts = f"{end_excl.isoformat()} 00:00:00"

    axis = [w.isoformat() for w in weeks]
    labels = [w.strftime("%m/%d") for w in weeks]

    sql_tasks_week_agg = f"""
SELECT
  date_trunc('week', created_at)::date AS week_start,
  COUNT(*) AS created_tasks,
  SUM(CASE WHEN status = 2 OR completed_at IS NOT NULL THEN 1 ELSE 0 END) AS completed_tasks,
  SUM(CASE WHEN associate_id IS NOT NULL THEN 1 ELSE 0 END) AS assoc_tasks,
  SUM(CASE WHEN response_duration IS NOT NULL AND response_duration > 0 THEN 1 ELSE 0 END) AS response_n,
  SUM(CASE WHEN response_duration IS NOT NULL AND response_duration > 0 THEN response_duration ELSE 0 END) AS response_sum_s,
  SUM(CASE WHEN completion_duration IS NOT NULL AND completion_duration > 0 THEN 1 ELSE 0 END) AS completion_n,
  SUM(CASE WHEN completion_duration IS NOT NULL AND completion_duration > 0 THEN completion_duration ELSE 0 END) AS completion_sum_s
FROM dt_collaborative_task
WHERE COALESCE(deleted_at, 0) = 0
  AND created_at >= TIMESTAMP '{start_ts}'
  AND created_at <  TIMESTAMP '{end_ts}'
GROUP BY 1
ORDER BY 1;
""".strip()

    sql_tasks_week_orgs = f"""
SELECT DISTINCT
  date_trunc('week', created_at)::date AS week_start,
  org_id
FROM dt_collaborative_task
WHERE COALESCE(deleted_at, 0) = 0
  AND created_at >= TIMESTAMP '{start_ts}'
  AND created_at <  TIMESTAMP '{end_ts}';
""".strip()

    sql_comments_week_agg = f"""
SELECT
  date_trunc('week', created_at)::date AS week_start,
  SUM(
    CASE
      WHEN activity_type = 7
       AND type = 2
       AND comment_text IS NOT NULL
       AND comment_text <> ''
      THEN 1 ELSE 0
    END
  ) AS comment_cnt
FROM dt_collaborative_task_log
WHERE COALESCE(deleted_at, 0) = 0
  AND created_at >= TIMESTAMP '{start_ts}'
  AND created_at <  TIMESTAMP '{end_ts}'
GROUP BY 1
ORDER BY 1;
""".strip()

    sql_comments_week_orgs = f"""
SELECT DISTINCT
  date_trunc('week', created_at)::date AS week_start,
  org_id
FROM dt_collaborative_task_log
WHERE COALESCE(deleted_at, 0) = 0
  AND created_at >= TIMESTAMP '{start_ts}'
  AND created_at <  TIMESTAMP '{end_ts}'
  AND activity_type = 7
  AND type = 2
  AND comment_text IS NOT NULL
  AND comment_text <> '';
""".strip()

    sql_comments_week_users = f"""
SELECT DISTINCT
  date_trunc('week', created_at)::date AS week_start,
  creator_id
FROM dt_collaborative_task_log
WHERE COALESCE(deleted_at, 0) = 0
  AND created_at >= TIMESTAMP '{start_ts}'
  AND created_at <  TIMESTAMP '{end_ts}'
  AND activity_type = 7
  AND type = 2
  AND comment_text IS NOT NULL
  AND comment_text <> '';
""".strip()

    created_tasks: Dict[str, int] = {wk: 0 for wk in axis}
    completed_tasks: Dict[str, int] = {wk: 0 for wk in axis}
    assoc_tasks: Dict[str, int] = {wk: 0 for wk in axis}
    response_n: Dict[str, int] = {wk: 0 for wk in axis}
    response_sum_s: Dict[str, float] = {wk: 0.0 for wk in axis}
    completion_n: Dict[str, int] = {wk: 0 for wk in axis}
    completion_sum_s: Dict[str, float] = {wk: 0.0 for wk in axis}

    active_orgs: Dict[str, Set[str]] = {wk: set() for wk in axis}
    comment_orgs: Dict[str, Set[str]] = {wk: set() for wk in axis}
    comment_users: Dict[str, Set[str]] = {wk: set() for wk in axis}
    comment_cnt: Dict[str, int] = {wk: 0 for wk in axis}

    for inst in ADB_INSTANCES:
        cols, data_rows = rows(run_archery(inst, "dt_collaborative_task", sql_tasks_week_agg))
        idx = {c: i for i, c in enumerate(cols)}
        for r in data_rows:
            wk = str(r[idx["week_start"]])
            if wk not in created_tasks:
                continue
            created_tasks[wk] += as_int(r[idx["created_tasks"]])
            completed_tasks[wk] += as_int(r[idx["completed_tasks"]])
            assoc_tasks[wk] += as_int(r[idx["assoc_tasks"]])
            response_n[wk] += as_int(r[idx["response_n"]])
            response_sum_s[wk] += as_float(r[idx["response_sum_s"]])
            completion_n[wk] += as_int(r[idx["completion_n"]])
            completion_sum_s[wk] += as_float(r[idx["completion_sum_s"]])

        cols, data_rows = rows(run_archery(inst, "dt_collaborative_task", sql_tasks_week_orgs, limit=500000))
        idx = {c: i for i, c in enumerate(cols)}
        for r in data_rows:
            wk = str(r[idx["week_start"]])
            if wk not in active_orgs:
                continue
            org = r[idx["org_id"]]
            if org is None:
                continue
            active_orgs[wk].add(str(as_int(org)))

        cols, data_rows = rows(run_archery(inst, "dt_collaborative_task_log", sql_comments_week_agg, limit=200000))
        idx = {c: i for i, c in enumerate(cols)}
        for r in data_rows:
            wk = str(r[idx["week_start"]])
            if wk not in comment_cnt:
                continue
            comment_cnt[wk] += as_int(r[idx["comment_cnt"]])

        cols, data_rows = rows(run_archery(inst, "dt_collaborative_task_log", sql_comments_week_orgs, limit=500000))
        idx = {c: i for i, c in enumerate(cols)}
        for r in data_rows:
            wk = str(r[idx["week_start"]])
            if wk not in comment_orgs:
                continue
            org = r[idx["org_id"]]
            if org is None:
                continue
            comment_orgs[wk].add(str(as_int(org)))

        cols, data_rows = rows(run_archery(inst, "dt_collaborative_task_log", sql_comments_week_users, limit=500000))
        idx = {c: i for i, c in enumerate(cols)}
        for r in data_rows:
            wk = str(r[idx["week_start"]])
            if wk not in comment_users:
                continue
            uid = r[idx["creator_id"]]
            if uid is None:
                continue
            comment_users[wk].add(str(as_int(uid)))

    collab: Dict[str, dict] = {}
    for wk in axis:
        ct = created_tasks[wk]
        collab[wk] = {
            "act": len(active_orgs[wk]),
            "tasks": ct,
            "ret": None,
            "complete_rate": (completed_tasks[wk] / float(ct)) if ct else 0.0,
            "assoc": (assoc_tasks[wk] / float(ct)) if ct else 0.0,
            "avg_resp_h": (response_sum_s[wk] / float(response_n[wk]) / 3600.0) if response_n[wk] else None,
            "avg_comp_h": (completion_sum_s[wk] / float(completion_n[wk]) / 3600.0) if completion_n[wk] else None,
            "comment_cnt": comment_cnt[wk],
            "comment_orgs": len(comment_orgs[wk]),
            "comment_users": len(comment_users[wk]),
        }
        prev = (parse_ymd(wk) - timedelta(days=7)).isoformat()
        if prev in active_orgs and len(active_orgs[prev]) > 0:
            collab[wk]["ret"] = len(active_orgs[wk] & active_orgs[prev]) / float(len(active_orgs[prev]))

    data = {
        "meta": {
            "label": f"协同任务周度（{start_m.isoformat()}～{t_end.isoformat()}）",
            "schema_version": 2,
            "definitions": "week=Mon..Sun; act=当周创建过协同任务的工厂数（跨分片 org_id 并集）；ret=prev_act∩cur_act/prev_act; complete_rate=当周已完成任务数/当周新建任务数；comment=activity_type=7 且 type=2 且 comment_text 非空",
        },
        "collab": collab,
        "months": axis,
        "labels": labels,
    }
    sql_snippets = {
        "sql_tasks_week_agg": sql_tasks_week_agg,
        "sql_tasks_week_orgs": sql_tasks_week_orgs,
        "sql_comments_week_agg": sql_comments_week_agg,
        "sql_comments_week_orgs": sql_comments_week_orgs,
        "sql_comments_week_users": sql_comments_week_users,
    }
    return data, {k: v for k, v in sql_snippets.items()}


def build_data(recipe_id: str, t_start: date, t_end: date) -> Tuple[dict, Dict[str, str], str]:
    if recipe_id == "collab_weekly_v1":
        data, sqls = recipe_collab_weekly_v1(t_start, t_end)
        return data, sqls, "week"
    raise SystemExit(f"未知 recipe: {recipe_id}")


def sql_snippets_to_md(sqls: Dict[str, str]) -> str:
    parts: List[str] = []
    for k in sorted(sqls.keys()):
        parts.append(f"### {k}\n\n```sql\n{sqls[k]}\n```\n")
    return "\n".join(parts)


def render_manifest(meta: dict, title: str, data_path: str, manifest_template_override: Optional[str]) -> dict:
    template_id = manifest_template_override or meta.get("manifest_template")
    raw = load_manifest_template(template_id)
    rendered = template_render(raw, {"title": title, "data_path": data_path})
    try:
        return json.loads(rendered)
    except json.JSONDecodeError as e:
        raise SystemExit(f"manifest 模板渲染后不是合法 JSON：{e}") from e


def main() -> None:
    p = argparse.ArgumentParser(description="Skills 内置看板运行器（零配置：recipe + 参数 → 交付物）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_list = sub.add_parser("list-recipes", help="列出可用 recipe")

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--recipe", required=True, help="recipe id（见 list-recipes）")
        sp.add_argument("--start", help="YYYY-MM-DD；默认 end-182 天（或 registry 默认）")
        sp.add_argument("--end", help="YYYY-MM-DD；默认今天")
        sp.add_argument("--title", help="看板标题（默认使用 registry 描述）")
        sp.add_argument("--out-data", required=True, help="输出 latest 数据 JSON（写入 查询指标/…）")
        sp.add_argument("--snapshot-dir", required=True, help="快照目录（写入 查询指标/…）")
        sp.add_argument("--out-html", required=True, help="输出 HTML（写入 图表/…）")
        sp.add_argument("--out-md", required=True, help="输出 md（写入 查询指标/…）")
        sp.add_argument("--manifest-template", help="可选：覆盖 registry 的 manifest_template（id 或路径）")

    sp_refresh = sub.add_parser("refresh", help="取数并写 snapshot + latest（不渲染）")
    add_common(sp_refresh)

    sp_render = sub.add_parser("render", help="用 out-data 渲染 out-html（不取数）")
    add_common(sp_render)

    sp_all = sub.add_parser("all", help="refresh + render")
    add_common(sp_all)

    args = p.parse_args()

    if args.cmd == "list-recipes":
        reg = registry()
        dashboards = reg.get("dashboards") or {}
        for rid in sorted(dashboards.keys()):
            d = dashboards[rid] or {}
            print(f"{rid}\t{d.get('description','')}")
        return

    meta = resolve_recipe_meta(args.recipe)
    end_d = parse_ymd(args.end) if args.end else date.today()
    if args.start:
        start_d = parse_ymd(args.start)
    else:
        lookback = int(meta.get("lookback_days_default") or 182)
        start_d = end_d - timedelta(days=lookback)
    if start_d > end_d:
        raise SystemExit(f"start({start_d}) 不能晚于 end({end_d})")

    title = args.title or meta.get("description") or args.recipe
    out_data = (ROOT / args.out_data).resolve() if not Path(args.out_data).is_absolute() else Path(args.out_data)
    snapshot_dir = (ROOT / args.snapshot_dir).resolve() if not Path(args.snapshot_dir).is_absolute() else Path(args.snapshot_dir)
    out_html = (ROOT / args.out_html).resolve() if not Path(args.out_html).is_absolute() else Path(args.out_html)
    out_md = (ROOT / args.out_md).resolve() if not Path(args.out_md).is_absolute() else Path(args.out_md)

    manifest_obj = render_manifest(meta, title=title, data_path=str(out_data), manifest_template_override=args.manifest_template)
    manifest_path = out_data.parent / f".manifest.{args.recipe}.json"
    write_json(manifest_path, manifest_obj)

    if args.cmd in ("refresh", "all"):
        data, sqls, axis = build_data(args.recipe, start_d, end_d)
        write_json(out_data, data)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snap_path = snapshot_dir / f"{ts_compact()}.json"
        write_json(snap_path, data)

        md_template_id = meta.get("md_template") or "dashboard_run_report_v1.md"
        md_tpl = load_md_template(md_template_id)
        md = md_tpl.format(
            start=start_d.isoformat(),
            end=end_d.isoformat(),
            axis=axis,
            recipe=args.recipe,
            manifest_template=meta.get("manifest_template") or "",
            definition_hint=data.get("meta", {}).get("definitions") or "",
            sql_snippets=sql_snippets_to_md(sqls),
            out_data=str(out_data),
            snapshot_dir=str(snapshot_dir),
            out_html=str(out_html),
            out_md=str(out_md),
            title=title,
        )
        write_text(out_md, md)

        print(f"Wrote\n- latest: {out_data}\n- snapshot: {snap_path}\n- md: {out_md}")

    if args.cmd in ("render", "all"):
        out_html.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                sys.executable,
                str(RENDER_HTML),
                "--data",
                str(out_data),
                "--manifest",
                str(manifest_path),
                "--output",
                str(out_html),
            ],
            check=True,
        )
        print(f"Wrote\n- html: {out_html}\n- manifest_used: {manifest_path}")


if __name__ == "__main__":
    main()


## 背景与目标

本次使用 skills 内置 recipe 生成业务看板数据与 HTML 看板，用于复盘指标趋势与变化。

## 时间范围

- 起始：{start}
- 结束：{end}
- 维度：{axis}

## 使用的 recipe / 模板

- recipe：`{recipe}`
- manifest_template：`{manifest_template}`

## 指标口径

口径说明（业务侧可补充更细口径）：{definition_hint}

## SQL（核心查询）

> 说明：SQL 由 recipe 固化在 skills 中；此处记录本次运行使用的 SQL 片段，便于追溯。\n\n{sql_snippets}

## 产物

- latest 数据：`{out_data}`
- 快照目录：`{snapshot_dir}`
- HTML：`{out_html}`

## 复跑命令

```bash
python3 .cursor/skills/query-business-metrics/scripts/run_dashboard.py all \
  --recipe {recipe} \
  --start {start} --end {end} \
  --title \"{title}\" \
  --out-data \"{out_data}\" \
  --snapshot-dir \"{snapshot_dir}\" \
  --out-html \"{out_html}\" \
  --out-md \"{out_md}\"
```


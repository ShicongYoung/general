---
name: query-business-metrics
description: >-
  通过 Archery 查询小工单/黑湖业务指标：用通用脚本 run_archery_query.py 换参查数；陌生指标则先拉表结构、再推断口径并生成 SQL（StarRocks 或 ADB 多分片合并）。查询语句须优先采用高性能写法（分区与选择性条件前置、库内聚合、避免无谓全表扫描）。
  Use when the user asks for 业务指标, 工厂数, 活跃, 埋点, Archery, SQL 查数, 查询指标, FY24, FY25, 委外, 协同, 自定义报表, 智能看板, TV 看板, trace_log_dp, 或「怎么统计某指标」。
---

# 业务指标查询（Archery）

## 第一步：通用查数脚本

**优先使用** **`scripts/run_archery_query.py`**：传入 `--instance`、`--table`、`--sql` 或 `--sql-file`、以及重复的 **`--var KEY=VALUE`** 做 SQL 模板替换（`str.format`）。ADB 需三实例合并 `org_id` 时用 **`--adb-merge`**。鉴权默认读 **`weekly-core-metrics/scripts/config.json`**。

```bash
python3 .cursor/skills/query-business-metrics/scripts/run_archery_query.py \
  --instance 小工单_阿里云_prod_starrocks \
  --table trace_log_dp \
  --sql "SELECT COUNT(DISTINCT orgId) AS c FROM trace_log_dp WHERE dat BETWEEN DATE '{a}' AND DATE '{b}' AND event = 'tv-device-info'" \
  --var a=2026-03-01 --var b=2026-03-31 \
  --stdout-format scalar
```

**公司财年、财年（周）、财年（月）**及 **代表周 / FYI 短窗**、**常见模块 SQL 模板**见 [reference-tables.md](reference-tables.md)。

**周报（委外 + 协同）**仍可用 **`.cursor/skills/weekly-core-metrics/scripts/generate_weekly_report.py`**（读其 `config.json`）。

## 第二步：陌生指标 — 缺少表名

若用户没说表名：**先问用户表名或业务模块**（自定义报表 / 智能看板 / 协同 / 委外 / TV 等）；可同时提示查 **[reference-tables.md](reference-tables.md)**「已映射业务」表。

## 第三步：拉表结构

使用 Archery（**URL 与鉴权**见 [reference-tables.md](reference-tables.md)「Archery 接口与鉴权」）：

- **表结构**：`POST https://archery.blacklake.tech/instance/describetable/`  
  表单字段：`instance_name`, `db_name=liteman`, `tb_name=...`  
  请求头：`X-CSRFToken`、`Cookie: csrftoken=...; sessionid=...`（从 **`weekly-core-metrics/scripts/config.json`** 读取，勿假设永久有效）

- **执行 SQL**：`POST https://archery.blacklake.tech/query/`  
  表单：`instance_name`, `db_name`, `schema_name=public`, `tb_name`（按 Archery 要求填本次 SQL 涉及的表）, `sql_content`, `limit_num`（大数表注意上限）

 describetable 若返回空行：尝试 `information_schema`（本环境曾需 `schema_name=public` 查列）。

**抽样**：`SELECT * FROM ... LIMIT 3` 推断 JSON/枚举字段含义。

## 查询性能与语句选择（必须遵守）

在 **不牺牲业务口径** 的前提下，**优先选用执行最快的 SQL**（减少扫描行数、尽早过滤、在库内完成聚合）。

1. **选择性条件前置**：`trace_log_dp` 尽量同时使用 **`dat` 范围** + **`event` / `module` 等高选择性列**（在用户允许的时间范围内取 **最小必要区间**）；`get_json_string` 等解析放在已被上面条件收紧的子集上。用户要 **全量** 时再放弃日期过滤，并声明保留周期与性能代价。
2. **库内聚合**：统计类查询用 **`GROUP BY` / `COUNT` / `COUNT(DISTINCT)`** 在 StarRocks/ADB 完成；**禁止** `SELECT` 大批量明细再在本地脚本去重计数（除非诊断性抽样）。
3. **投影最小化**：只选 **`SELECT` 需要的列**；计数用 **`COUNT(1)`**；避免无必要的 `SELECT *` 跑大表。
4. **与引擎/网关对齐**：本环境 Archery 对 **部分 CTE**、**`COUNT(*)`** 等可能受限或变慢，已确认可行时优先 **单层嵌套子查询** 或 **分步查询**；不要把明显会炸的 SQL 一次扔上去。
5. **ADB 多分片**：继续 **按实例拆分**；单分片内避免 **巨型 `IN`**（必要时改 **存在性子查询** 或分段）；合并工厂时优先 **`run_archery_query.py --adb-merge`**。
6. **脚本批跑**：周期循环查数时，复用 **已验证的快 SQL**，不要为省事复制低效模板。

## ADB 多分片：比率类指标（xx 率）的跨实例去重（标准口径）

凡指标形态为 **比率 / 比例 / 转化率 / 留存率 / 占比** 等（记作「xx 率」），且 **分子或分母涉及客户、工厂等实体**（常见 **`org_id`**）时，**必须**按 **全局去重** 后再算率，避免多分片下重复计数或「分片率取平均」失真。

**推荐流程（与「先并集、再算率」一致）：**

1. **分实例**跑同一套 SQL（或分步查询），得到各分片上的 **实体集合**（如 `SELECT DISTINCT org_id ...`）或 **仅单分片内可解释的计数**。
2. 在脚本侧对实体 ID 做 **并集（union）去重**（`set` 合并），得到 **全局分子集合、全局分母集合**（或全局 distinct 计数）。
3. **xx 率 = 全局分子 / 全局分母**（分母为 0 时单独约定展示为 N/A 或 0，并在口径中写明）。

**不推荐（除非用户明确接受近似口径并写明）：**

- 各实例 **先各自算一个率** 再 **算术平均**。
- 在 **未确认**「实体是否只落在一个分片」时，把多分片的分子、分母 **简单相加** 当作全局（若存在跨片重复 `org_id`，会偏离全局比率）。

**工具衔接：**

- 命令行合并多实例结果时，优先 **`run_archery_query.py --adb-merge`**（按工具说明合并）；本质目标仍是 **全局 distinct 后再算率**。
- 周报委外留存若需用「拉齐 org_id 再交集/并集」核对，可用 **`.cursor/skills/weekly-core-metrics/scripts/compare_outsource_retention_deduped.py`** 与脚本结果对照。

**说明：** 当业务上 **每个 `org_id` 只存在于一个 ADB 分片** 时，「分片内计数再相加」与「并集去重后计数」在数值上常 **一致**；**标准写法仍以上述「并集去重」为准**，便于与异常重复数据、迁移数据对齐。

## 第四步：推断口径并写 SQL

1. **工厂维度**：ADB 一般用 **`org_id`**；埋点 **`orgId`**。
2. **多分片（ADB 01/02/03）**：每个实例跑同一 SQL，对 **`org_id` 列表做并集** 再计数；或 **`run_archery_query.py --adb-merge`**；**比率类指标** 另见上一节 **「ADB 多分片：比率类指标」**。
3. **StarRocks**：`trace_log_dp` 中保留字列名如 `` `function` `` 需反引号；JSON 常用 `get_json_string(eventValues, '$.url')`。
4. **软删**：有 `deleted_at` 时通常 `COALESCE(deleted_at, 0) = 0`。
5. **时间窗（默认规则，须遵守）**：
   - **用户未提及「财年」「FY24」「FY25」等时间范围**：视为 **全量可查数据**——**不要**自动套用 [reference-tables.md](reference-tables.md) 中的财年窗 `dat BETWEEN`。埋点表通常 **不加** 自然日/财年过滤（仅保留业务必要的条件，如 `event = ...`）；**ADB** 按指标常规口径（如未删除行），**不因财年额外截断** `created_at`/`updated_at`，除非用户要求按某段时间统计。
   - **用户明确财年或给出起止日期**：以 **[reference-tables.md](reference-tables.md)** **「公司财年」**（整年 / 财年（月）/ 财年（周））或用户当次口述为准；若用户说 **财年** 而未区分周/月/整年，**先确认** 再写 SQL。**历史短窗 A/B** 仅在与旧产物对齐时使用。
   - **说明义务**：若查的是埋点全量，回复中简述「全量、受 `trace_log_dp` 保留周期限制」；若用户后来补了时间窗，再按新口径重跑。

生成 SQL 后：**在对话里说明口径假设**，再执行或交给用户确认。

## 第五步：沉淀表知识

每确认一张新表或新口径：**在 [reference-tables.md](reference-tables.md) 增补一行**（业务 ↔ 表 ↔ 关键字段/条件），避免下次从零推断。

**表结构对照图**：仓库**不内置** Archery 截图；需要时用者在对话中**提供**截图或路径，确认后将列名与口径**写回** `reference-tables.md` 正文（勿长期依赖外链图片）。

## 必读域知识摘要

更全的映射、实例名、合并规则、SQL 模板见 **[reference-tables.md](reference-tables.md)**。

核心约定：

- **埋点** → `小工单_阿里云_prod_starrocks` + `trace_log_dp`
- **业务表** → ADB **01、02、03** + `liteman` + 按业务选表；**按工厂统计必须合并三实例**
- **ADB 比率类**（转化率、留存率、占比等）→ **跨实例并集去重后再算率**，见上文 **「ADB 多分片：比率类指标」**；周报场景见 **[weekly-core-metrics](../weekly-core-metrics/SKILL.md)** 中 **「多分片比率与跨实例去重」**

## 与图表产出（两段式）

| 段 | 技能 | 职责 |
|----|------|------|
| **第 1 段（本技能）** | query-business-metrics | 定口径、**`run_archery_query.py`** 或 Archery 查数；**指标结论落盘仅 `查询指标/*.md`**（口径 + SQL + 结果）。 |
| **第 2 段** | **[business-charts](../business-charts/SKILL.md)** | 若需 HTML 看板：读业务侧维护的 **数据 JSON + manifest**，`render_dashboard_html.py` → **`图表/*.html`**。 |

**FY2025 月度看板**：口径见 **`查询指标/FY2025_功能使用年度总结_口径.md`**；数据文件 **`FY2025_chart_data.json`** 由业务按需更新（专用导出脚本已移除）。

## Skills 内复用层（推荐）

当用户需求是「查询任何指标 / 生成任何看板」且希望**复用脚手架**时，复用层应全部沉淀在本技能目录（`.cursor/skills/`）内：

- 看板运行器：`.cursor/skills/query-business-metrics/scripts/run_dashboard.py`
- 指标运行器：`.cursor/skills/query-business-metrics/scripts/run_metric.py`
- 看板 registry / 模板：`.cursor/skills/query-business-metrics/dashboards/`
- 指标 registry：`.cursor/skills/query-business-metrics/metrics/`

用户目录（`查询指标/`、`图表/`）只放**交付物**（md / data.json / snapshots / html），不放复用配置文件。

### 生成看板（零配置：recipe + 参数 → 交付物）

```bash
python3 .cursor/skills/query-business-metrics/scripts/run_dashboard.py all \
  --recipe <recipe_id> \
  --out-data "查询指标/<看板目录>/latest.json" \
  --snapshot-dir "查询指标/<看板目录>/snapshots" \
  --out-html "图表/<看板名>.html" \
  --out-md "查询指标/<看板名>.md"
```

可用 recipe 列表：

```bash
python3 .cursor/skills/query-business-metrics/scripts/run_dashboard.py list-recipes
```

### 查询单个指标（零配置：metric + 参数 → `查询指标/*.md`）

```bash
python3 .cursor/skills/query-business-metrics/scripts/run_metric.py list-metrics

python3 .cursor/skills/query-business-metrics/scripts/run_metric.py run \
  --metric <metric_id> \
  --start YYYY-MM-DD --end YYYY-MM-DD \
  --out-md "查询指标/<指标名>.md"
```

## 注意事项

- Token 易失效：鉴权失败时让用户更新 **`weekly-core-metrics/scripts/config.json`** 中的 `csrftoken` / `sessionid`。
- `trace_log_dp` **保留周期有限**；历史财年可能没有埋点，需说明「不可得」或换业务表口径。
- **单次指标查询交付**：**只写一个 `.md`** 到 **`查询指标/`**（含口径 + 结果）；`run_archery_query.py` 的 **`--output`** 仅作原始响应调试，不作为指标正式交付物。
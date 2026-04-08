---
name: query-business-metrics
description: >-
  通过 Archery 查询小工单/黑湖业务指标：优先复用仓库内现成 Python 脚本；陌生指标则先拉表结构、再推断口径并生成 SQL（StarRocks 或 ADB 多分片合并）。查询语句须优先采用高性能写法（分区与选择性条件前置、库内聚合、避免无谓全表扫描）。
  Use when the user asks for 业务指标, 工厂数, 活跃, 埋点, Archery, SQL 查数, 查询指标, FY24, FY25, 委外, 协同, 自定义报表, 智能看板, TV 看板, trace_log_dp, 或「怎么统计某指标」。
---

# 业务指标查询（Archery）

## 第一步：有无现成脚本

在本仓库 **优先执行**（**公司财年、财年（周）、财年（月）**见 [reference-tables.md](reference-tables.md)「公司财年」；历史脚本短窗见同文件「历史短窗」；改常量后同步该表）：

| 路径 | 用途 |
|------|------|
| `.cursor/skills/query-business-metrics/scripts/query_fy24_fy25_metrics.py` | 财年窗口内 TV / 自定义&智能 PageView / 协同 / 委外 等；产出在 `查询指标/` |
| `.cursor/skills/query-business-metrics/scripts/query_fy25_filter_info_defaults.py` | `dt_custom_filter_info` 筛选默认值（`defaultValueInfo`）按工厂；产出在 `查询指标/` |
| `.cursor/skills/weekly-core-metrics/scripts/generate_weekly_report.py` | 周报：委外 + 协同（读其目录下 `config.json` 的 auth） |

能覆盖用户问题时：**直接运行脚本**，把结果摘要回复用户；输出路径见各脚本末尾说明。

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
5. **ADB 多分片**：继续 **按实例拆分**；单分片内避免 **巨型 `IN`**（必要时改 **存在性子查询** 或分段）。
6. **脚本批跑**：周期循环查数时，复用 **已验证的快 SQL**，不要为省事复制低效模板。

## 第四步：推断口径并写 SQL

1. **工厂维度**：ADB 一般用 **`org_id`**；埋点 **`orgId`**。
2. **多分片（ADB 01/02/03）**：每个实例跑同一 SQL，对 **`org_id` 列表做并集** 再计数；或 SQL 只返回 `org_id` 由脚本合并（与 `weekly-core-metrics/scripts` / `query-business-metrics/scripts` 同思路）。
3. **StarRocks**：`trace_log_dp` 中保留字列名如 `` `function` `` 需反引号；JSON 常用 `get_json_string(eventValues, '$.url')`。
4. **软删**：有 `deleted_at` 时通常 `COALESCE(deleted_at, 0) = 0`。
5. **时间窗（默认规则，须遵守）**：
   - **用户未提及「财年」「FY24」「FY25」等时间范围**：视为 **全量可查数据**——**不要**自动套用 [reference-tables.md](reference-tables.md) 中的财年窗 `dat BETWEEN`。埋点表通常 **不加** 自然日/财年过滤（仅保留业务必要的条件，如 `event = ...`）；**ADB** 按指标常规口径（如未删除行），**不因财年额外截断** `created_at`/`updated_at`，除非用户要求按某段时间统计。
   - **用户明确财年或给出起止日期**：以 **[reference-tables.md](reference-tables.md)** **「公司财年」**（整年 / 财年（月）/ 财年（周））或用户当次口述为准；若用户说 **财年** 但未区分周/月/整年，**先确认** 再写 SQL。**历史短窗 A/B** 仅在与旧脚本/旧产物对齐时使用。
   - **说明义务**：若查的是埋点全量，回复中简述「全量、受 `trace_log_dp` 保留周期限制」；若用户后来补了时间窗，再按新口径重跑。

生成 SQL 后：**在对话里说明口径假设**，再执行或交给用户确认。

## 第五步：沉淀表知识

每确认一张新表或新口径：**在 [reference-tables.md](reference-tables.md) 增补一行**（业务 ↔ 表 ↔ 关键字段/条件），避免下次从零推断。

**表结构对照图**：仓库**不内置** Archery 截图；需要时用者在对话中**提供**截图或路径，确认后将列名与口径**写回** `reference-tables.md` 正文（勿长期依赖外链图片）。

## 必读域知识摘要

更全的映射、实例名、合并规则、已有脚本列表见 **[reference-tables.md](reference-tables.md)**。

核心约定：

- **埋点** → `小工单_阿里云_prod_starrocks` + `trace_log_dp`
- **业务表** → ADB **01、02、03** + `liteman` + 按业务选表；**按工厂统计必须合并三实例**

## 注意事项

- Token 易失效：鉴权失败时让用户更新 **`weekly-core-metrics/scripts/config.json`**（及脚本内 `CONFIG['auth']` 若未改为读配置）中的 `csrftoken` / `sessionid`。
- `trace_log_dp` **保留周期有限**；历史财年可能没有埋点，需说明「不可得」或换业务表口径。
- 产出若落盘：**指标类查询结果**写在仓库 **`查询指标/`**，且 **每次须保存 Markdown（`.md`）**（含口径说明 + 结果表/要点）；若同时有结构化产物可并存 **`.json`**。拉数脚本在 **`query-business-metrics/scripts/`**（除非另行说明）；**新脚本/改脚本**应在 `查询指标/` 写出与指标同名的 **`.md`**。

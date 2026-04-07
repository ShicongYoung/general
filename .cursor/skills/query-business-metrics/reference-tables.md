# 业务指标 — 库表与口径速查（随查询沉淀，可增删改）

> 新确认的表结构或指标口径：在 `SKILL.md` 工作流末尾要求追加一行到本节对应表。

## Archery 接口与鉴权

| 用途 | URL | 说明 |
|------|-----|------|
| 执行 SQL | `https://archery.blacklake.tech/query/` | POST：`instance_name`, `db_name=liteman`, `schema_name=public`, `tb_name`, `sql_content`, `limit_num` |
| 表结构 | `https://archery.blacklake.tech/instance/describetable/` | POST：`instance_name`, `db_name=liteman`, `tb_name` |
| 请求头 | `X-CSRFToken`；`Cookie: csrftoken=...; sessionid=...` | **勿将真实 token 写入本文件**；从 **`.cursor/skills/weekly-core-metrics/scripts/config.json`**（字段与脚本 `CONFIG['auth']` 一致）读取；失效时由使用者在本地更新 |

## Archery 实例

| 用途 | instance_name | 库 | 说明 |
|------|---------------|-----|------|
| 行为埋点 | 小工单_阿里云_prod_starrocks | liteman | `tb_name` 填 `trace_log_dp` |
| 业务库（分片） | 小工单_阿里云_prod_ADB_01 / 02 / 03 | liteman | 按表选 `tb_name`；**按工厂统计需三实例结果合并** |

**合并规则（ADB）**：`org_id` 对工厂去重时，对 01/02/03 查询结果做 **并集** 再 `COUNT(DISTINCT)`，勿简单相加。

## 已映射业务 ↔ 表 / 埋点

| 业务 | 数据源 | 表 / 条件 | 备注 |
|------|--------|-----------|------|
| TV 版 | StarRocks | `trace_log_dp` `event='tv-device-info'` | 工厂 `orgId`。**TV 版活跃工厂**（默认）：在**所统计的一周**内，`tv-device-info` 出现的 **不同自然日数 > 1**（即一周内有埋点的天数 ≥ 2）；与「当周任一天有过心跳」的口径区分使用。 |
| TV 看板缩放 | StarRocks | `trace_log_dp` `event='tv-board-scale-level'` | `eventValues`：含 `layout`、`scale`、`id` 等 |
| TV 在线看板（APK） | StarRocks | `module='kanban'` `` `function`='online' `` `method='kanbanOnline-apk'` | 按日去重会话等口径另定 |
| 自定义报表（访问） | StarRocks | `event='PageView'` `get_json_string(eventValues,'$.url')` LIKE `%/customDashboard/detail%` | `orgId` |
| 智能看板（访问） | StarRocks | 同上，url LIKE `%/intelligentDashboard/detail/%` | `orgId` |
| 自定义报表（存储） | ADB | `dt_custom_dashboard` `dashboard_type=1` | 与 `org_id` |
| 智能看板（存储） | ADB | `dt_custom_dashboard` `dashboard_type=3` | 与 `org_id` |
| 筛选默认值 | ADB | `dt_custom_filter_info` JOIN `dt_custom_dashboard` | `filter_condition` JSON 含 **`defaultValueInfo`**（`jsonb_path_exists`） |
| 协同任务 | ADB | `dt_collaborative_task` | `org_id`/`created_at` |
| 协同任务 · 处理记录 | ADB | `dt_collaborative_task_process_record` | 与任务主表关联 |
| 协同任务 · 评论/动态 | ADB | `dt_collaborative_task_log` | 与任务主表关联 |
| 协同任务 · 任务类型 | ADB | `dt_collaborative_task_type` | 依赖/类型配置 |
| 委外订单 | ADB | `dt_outsource_order` | `org_id` |
| 委外过账 | ADB | `dt_outsource_post` | `post_type_name`：`发料` / `收货` |
| 图表/明细表（存储） | ADB | `dt_custom_chart_info` JOIN `dt_custom_dashboard` | 见下节；**`chart_type=6`** 在 type=1、3 下均存在；产品说「明细表」常指 **仅 `dashboard_type=1`** |

## 表结构明细（已核对）

### `dt_custom_chart_info`

- **用途**：看板下的图表配置（含数据源、维度、筛选等）。
- **主键维度**：`id`，**工厂** `org_id`，**所属看板** `dashboard_id`（对应 `dt_custom_dashboard.id`，**需同 `org_id` 与看板表关联**）。
- **常用列**：`name`, `chart_type`, `data_source`, `data_source_type`, `dimension_row`, `dimension_column`, `indicator_info`, `filter_condition`, `order_condition`, `deleted_at`, `created_at`, `updated_at`, `creator_id`, `operator_id` 等。
- **`chart_type = 6`**：业务侧可作「明细表」类组件；库中 **自定义报表（`dashboard_type=1`）与智能看板（`dashboard_type=3`）均有**，统计「自定义报表明细」时 **必须加 `d.dashboard_type = 1`**。
- **统计**：创建条数 = 三实例 `COUNT(*)` **相加**；工厂数 = 三实例 `org_id` **并集去重**。条件常写 `COALESCE(c.deleted_at,0)=0` 且看板 `COALESCE(d.deleted_at,0)=0`。

### `dt_custom_filter_info`

- **用途**：看板级筛选配置（与图表通过 `filter_condition` 内 `associatedCharts` 等关联）。
- **主键维度**：`id`，`org_id`，`dashboard_id`（与 `dt_custom_dashboard` 同 `org_id` 关联）。
- **列**：`name`, **`filter_condition`（JSON/JSONB 数组）**, `deleted_at`, `created_at`, `updated_at` 等。
- **筛选默认值**：数组元素若含 **`defaultValueInfo`** 即视为配置默认值（推荐 `jsonb_path_exists(filter_condition::jsonb, '$[*] ? (@.defaultValueInfo != null)')`）。
- **指标区分**：**配置行数**（`dt_custom_filter_info` 行）vs **筛选组件数**（`jsonb_array_elements` 展开后带 `defaultValueInfo` 的元素个数）；工厂数多为 `org_id` 去重或 `IN (1,3)` 合并去重。

## 常用字段命名

- Trace：`orgId`（camelCase）、`dat`、`event`、`eventValues`（JSON）
- ADB 业务表：多为 `org_id`、`deleted_at`、`created_at`、`updated_at`

## 财年与「代表周」时间窗（请勿混用）

**查询默认（与 `SKILL.md` 一致）**：用户 **未** 写明财年或起止日时，埋点/SQL **不按**下列窗口截断（全量可查，受 `trace_log_dp` 保留周期限制）。

本仓库存在 **两套** 日期约定，适用脚本不同：

| 名称 | 25 财年窗 | 24 财年窗 | 主要使用者 |
|------|-----------|-----------|------------|
| **A. 原 FYI 财年窗** | `2026-03-30` ~ `2026-04-05` | `2025-03-31` ~ `2025-04-06` | `年度总结/query_fy25_filter_info_defaults.py`（`FY25_START`/`FY25_END`）；用户口头「FYI 财年」分析 |
| **B. 财年代表周** | `2026-03-23` ~ `2026-03-29` | `2025-03-24` ~ `2025-03-30` | `年度总结/query_fy24_fy25_metrics.py` 内常量 `WINDOWS`；`FY24_FY25_指标.*` |

改任意一套日期时：**同步修改对应脚本常量** 及本表，避免文档与代码不一致。

## 已有脚本（优先复用）

| 脚本 | 作用 |
|------|------|
| `年度总结/query_fy24_fy25_metrics.py` | FY 窗口：TV/报表/智能/协同/委外等指标 |
| `年度总结/query_fy25_filter_info_defaults.py` | 筛选 `defaultValueInfo` 工厂数 |
| `.cursor/skills/weekly-core-metrics/scripts/generate_weekly_report.py` | 周报委外 + 协同 |

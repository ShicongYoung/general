# 业务指标 — 库表与口径速查（随查询沉淀，可增删改）

> 新确认的表结构或指标口径：在 `SKILL.md` 工作流末尾要求追加一行到本节对应表。  
> **性能**：新建/改写 SQL 须遵守 `SKILL.md`「查询性能与语句选择」——优先最快且口径正确的写法。

**仓库目录**：**`查询指标/`** 存每次指标查询产出；**每次只新增一个 `.md`**（口径说明 + SQL + 结果表/要点），**不**为单次查数再配合同名 `.json`。图表用结构化 JSON（如 `FY2025_chart_data.json`）由业务侧按需单独维护，不属于「单次指标查询」的必交付物。

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

### 表结构截图（按需）

本仓库 **不再内置** Archery 表结构截图。需要对照列名/类型时：由使用者在对话中 **贴图或附件**，或在本地保存后指明路径；确认口径后把文字结论写回本节（业务 ↔ 表 ↔ 字段），避免依赖过期截图。

## 公司财年（主口径）

**定义（业务口述对齐）**：**一个财年** = 从 **上一自然年的 3 月最后一天之后**起算，至 **本自然年的 3 月最后一天**止。落地为 **自然日闭区间**：

- **财年整年**：**`(去年 3 月 31 日) + 1 天`** ～ **`今年 3 月 31 日`**  
  即常见 **「4 月～次年 3 月」**：**`YYYY-04-01` ～ `(YYYY+1)-03-31`**，其中 **`YYYY+1` 为财年「结束年」**（3 月所在自然年）。

| 财年（以结束年表述） | 财年整年（`dat`） | 财年（月）·3 月整月 | 财年（周）·3 月内最后完整自然周（不跨月） |
|----------------------|-------------------|---------------------|------------------------------------------|
| 截至 **2026-03-31**（例：当前公司 FY） | `2025-04-01` ～ `2026-03-31` | `2026-03-01` ～ `2026-03-31` | `2026-03-23` ～ `2026-03-29`（周界 **周一～周日**，周一与周日均在 **3 月**） |
| 截至 **2025-03-31** | `2024-04-01` ～ `2025-03-31` | `2025-03-01` ～ `2025-03-31` | `2025-03-24` ～ `2025-03-30` |

**财年（月）**：财年 **结束年** 的 **3 月 1 日～3 月 31 日**（整月）。  
**财年（周）**：财年 **结束年** 的 **3 月** 里，**最后一个**「**周一至周日**」**整段都落在 3 月** 的完整自然周（**不跨月**，不含 4 月日期）。**不是**「含 3/31 那一周」若该周会跨入 4 月。若公司周界为 **周日～周六**，需在 SQL 中按同逻辑取「3 月内最后完整一周」另算。  

**推算要点**：从 **3 月 31 日**向前找，第一个满足「该周周一与周日都在 3 月」的周一即为财年（周）的起始日。

**查询默认（与 `SKILL.md` 一致）**：用户 **未** 写「财年 / 财年周 / 财年月」或起止日时，埋点 **不按** 上表截断（全量可查，受保留周期限制）。用户说 **财年** 而未说周/月/整年时，**先问** 要整年、3 月当月还是 3 月最后一周。

---

## 历史短窗（旧产物对齐用）

下列 **非** 公司财年整段，仅为历史产物中曾出现的 **短窗口**；**新分析默认用上一节「公司财年」**。需要复现旧数时，将日期代入下方 **SQL 模板** 与 `run_archery_query.py`（或 Archery）即可。

| 名称 | 曾用「25 窗」 | 曾用「24 窗」 | 说明 |
|------|---------------|---------------|------|
| **A. 原 FYI 短窗** | `2026-03-30` ~ `2026-04-05` | `2025-03-31` ~ `2025-04-06` | 曾用于筛选默认值「窗内有更新」类指标 |
| **B. 原代表周（财年周）** | `2026-03-23` ~ `2026-03-29` | `2025-03-24` ~ `2025-03-30` | 与现行 **财年（周）** 一致；`查询指标/FY24_FY25_指标.*` 等历史文件名沿用 |

## 代表周类指标 · SQL 模板（原财年批跑脚本已下线）

以下 **`{ws}` / `{we}`** 替换为「历史短窗」**B** 行对应起止日，或替换为任意业务窗。执行：**单实例**用 `run_archery_query.py` 传 `--instance` + `--table`；**ADB** 返回 `org_id` 列表时用 `--adb-merge`（或各实例导出后在库外并集）。

### TV（≥2 个自然日有 `tv-device-info`）

```sql
SELECT COUNT(*) AS c FROM (
  SELECT orgId
  FROM trace_log_dp
  WHERE dat BETWEEN DATE '{ws}' AND DATE '{we}'
    AND event = 'tv-device-info'
  GROUP BY orgId
  HAVING COUNT(DISTINCT dat) >= 2
) x;
```

- **实例**：`小工单_阿里云_prod_starrocks`，`tb_name`：`trace_log_dp`。

### 自定义报表 / 智能看板（PageView，周内 ≥2 天）

自定义 URL：`%/customDashboard/detail%`；智能 URL：`%/intelligentDashboard/detail/%`。

```sql
SELECT COUNT(*) AS c FROM (
  SELECT orgId
  FROM trace_log_dp
  WHERE dat BETWEEN DATE '{ws}' AND DATE '{we}'
    AND event = 'PageView'
    AND get_json_string(eventValues, '$.url') LIKE '%/customDashboard/detail%'
  GROUP BY orgId
  HAVING COUNT(DISTINCT dat) >= 2
) x;
```

### 协同（窗内创建任务天数 ≥2）

```sql
SELECT org_id FROM (
  SELECT org_id, COUNT(DISTINCT DATE(created_at)) AS d
  FROM dt_collaborative_task
  WHERE DATE(created_at) BETWEEN DATE '{ws}' AND DATE '{we}'
  GROUP BY org_id
) t WHERE d >= 2;
```

- **表**：`dt_collaborative_task`；**ADB 三实例** `org_id` 并集计数。

### 委外（窗内有过「收货」过账的工厂）

```sql
SELECT DISTINCT org_id
FROM dt_outsource_post
WHERE post_type_name = '收货'
  AND DATE(created_at) BETWEEN DATE '{ws}' AND DATE '{we}'
  AND COALESCE(deleted_at, 0) = 0;
```

- **表**：`dt_outsource_post`；**ADB 三实例**并集去重。

### 筛选默认值（`dt_custom_filter_info` · `defaultValueInfo`）

**全量 · 自定义报表（`dashboard_type = 1`）**（单实例示例；工厂数需 01/02/03 合并）：

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

智能看板改 `dashboard_type = 3`。若仅统计 **A 类短窗**内新建或更新，增加：

```sql
  AND (
    DATE(f.updated_at) BETWEEN DATE '{ws}' AND DATE '{we}'
    OR DATE(f.created_at) BETWEEN DATE '{ws}' AND DATE '{we}'
  );
```

## 通用查数入口

| 路径 | 作用 |
|------|------|
| **`query-business-metrics/scripts/run_archery_query.py`** | **唯一推荐**：Archery 单实例查询或 `--adb-merge` 合并 `org_id`；SQL + `--var` 模板变量 |
| `business-charts/scripts/render_dashboard_html.py` | 第 2 段：读已有 JSON + manifest → `图表/*.html` |
| `weekly-core-metrics/scripts/generate_weekly_report.py` | 周报：委外 + 协同（独立场景） |

**FY2025 月度看板 JSON**（`FY2025_chart_data.json`）：原专用导出脚本已移除；更新数据需按 `查询指标/FY2025_功能使用年度总结_口径.md` 各模块口径自行查数（`run_archery_query.py` / Archery），再维护 JSON 或使用 md 表格承载结论。

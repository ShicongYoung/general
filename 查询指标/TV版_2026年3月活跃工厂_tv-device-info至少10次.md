# TV 版 2026 年 3 月活跃工厂数（tv-device-info ≥10）

## 时间范围

`2026-03-01` ～ `2026-03-31`（3 月整月）

## 数据源

- **实例**：`小工单_阿里云_prod_starrocks`
- **表**：`trace_log_dp`

## 口径（本次采用）

在 3 月内，对 `event = 'tv-device-info'` 按工厂 `orgId` 聚合，**当月该事件埋点行数 `COUNT(*) ≥ 10`** 的工厂计入活跃。

```sql
SELECT COUNT(*) AS c
FROM (
  SELECT orgId
  FROM trace_log_dp
  WHERE dat BETWEEN DATE '2026-03-01' AND DATE '2026-03-31'
    AND event = 'tv-device-info'
  GROUP BY orgId
  HAVING COUNT(*) >= 10
) x;
```

## 结果

| 指标 | 工厂数 |
|------|--------|
| **当月 tv-device-info 条数 ≥ 10 的工厂** | **515** |

## 备选口径（若「≥10」指自然日数而非条数）

当月 **`COUNT(DISTINCT dat) ≥ 10`** 的工厂：**296**（与上表二选一，勿混用）。

## 备注

- 与 `reference-tables.md` 默认「一周内不同自然日数 > 1」的 TV 活跃定义不同；本题为明确 **`tv-device-info≥10`** 条件下的单月统计。
- 查数：`.cursor/skills/query-business-metrics/scripts/run_archery_query.py`（`--var` 替换 SQL 模板中的日期占位符）。

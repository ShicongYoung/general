---
name: business-charts
description: 配置驱动生成任意业务指标图表 HTML（周度/月度趋势、对比图、双轴图），自动附洞察并落盘到「图表/」（可选写「查询指标/」索引）。Use when you need 业务图表, 趋势图, 周/月报图表, 年度总结图表, 指标可视化, chart, trend chart, 或「根据 SQL 生成图」。
---

# 通用业务图表（trend-chart 升级版）

## 适用场景

当用户需要生成**任意业务指标**的趋势图/对比图（周度、月度等）并输出 HTML 时，执行本技能。

- **输出**：HTML **仅**写入仓库根目录 **`图表/`**（最终产物）；不在 `图表/` 放脚本、缓存或 `vendor`。
- **样式模板**：浅色主题 CSS 见 **`templates/chart-report-light.css`**（生成脚本读入后写入 HTML `<style>`，或与页面结构注释一并维护）。
- **结构约定**：每个 `<canvas>` 外包一层 **`<div class="chart-body">`**；Chart.js 使用 **`maintainAspectRatio: false`**，由 `.chart-body` 固定高度，避免 y 轴区域被压扁。
- **Chart.js**：UMD 文件在 **`vendor/chart.umd.min.js`**；生成 HTML 时**内联**到 `<script>`，避免 `file://` 或缺失相对路径导致空白图。
- **缓存**：示例与 FY 拉数缓存放在 **`cache/`**（可在配置 JSON 里用 `.cursor/skills/trend-chart/cache/xxx.json`）。
- **配置驱动**：通过 JSON 定义「时间分段」「数据源」「SQL」「图表类型」「洞察规则」。
- **FY2025 多模块年度页**：**`scripts/generate_fy25_usage_report.py`** → `图表/FY2025_功能使用年度总结.html`（原始数据 **`cache/fy25_usage_raw.json`**）。

## 支持的时间范围表达

| 用户说法 | 对应参数 |
|---------|---------|
| 周度 / 月度 | 配置 `periods.kind = week / month` |
| 指定起止日期 | 配置 `periods.start / periods.end`（YYYY-MM-DD） |
| 周界（周一~周日） | 周度配置 `periods.week_start=0`（默认周一） |

## 执行步骤

1. 新建/修改一份图表配置 JSON（参考示例配置）
2. 运行脚本生成 HTML：

```bash
python3 .cursor/skills/trend-chart/scripts/generate_business_charts.py \
  --config .cursor/skills/trend-chart/scripts/chart-config.fy25-usage.example.json
```

3. 若 Archery 较慢或 token 失效：先更新 `.cursor/skills/weekly-core-metrics/scripts/config.json`，或使用 `--offline` 仅用缓存渲染：

```bash
python3 .cursor/skills/trend-chart/scripts/generate_business_charts.py \
  --config .cursor/skills/trend-chart/scripts/chart-config.fy25-usage.example.json \
  --offline
```

```bash
# FY2025 年度总结（多图），离线仅渲染
python3 .cursor/skills/trend-chart/scripts/generate_fy25_usage_report.py --offline
```

## 典型命令示例

```bash
# FY2025 示例（配置驱动）
python3 .cursor/skills/trend-chart/scripts/generate_business_charts.py \
  --config .cursor/skills/trend-chart/scripts/chart-config.fy25-usage.example.json

# 离线重渲（不请求 Archery）
python3 .cursor/skills/trend-chart/scripts/generate_business_charts.py \
  --config .cursor/skills/trend-chart/scripts/chart-config.fy25-usage.example.json \
  --offline
```

## 图表内容

由配置文件 `report.sections[].charts[]` 决定。支持（先做常用三类）：

- `line`：折线图
- `pct_line`：百分比折线图（0~100%）
- `dual_bar_line`：双轴（柱 + 线）

## 注意事项

- 数据来源：Archery / StarRocks（`trace_log_dp`）与 ADB（`ADB_01/02/03`）
- **SQL 限制**：Archery 可能拦截部分语法（如某些 CTE / FILTER / `COUNT(*)`）。推荐用标量 `COUNT(1)`、子查询写法。
- Token 失效时更新 `.cursor/skills/weekly-core-metrics/scripts/config.json` 中的 `csrftoken` / `sessionid`
- **多图页维护**：在 HTML 中用注释区分 **页头 / KPI / 各业务模块 / 脚本**；样式与图区高度以模板为准，避免再对 `canvas` 使用过小 `max-height`。
- 索引：可在 `查询指标/` 写同名 `.md`（配置 `write_md_to`）。

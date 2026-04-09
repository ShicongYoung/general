---
name: business-charts
description: >-
  第 2 段：在结构化数据 JSON 已就绪时，用 manifest 声明图表类型、配色与业务导语，渲染通用业务看板 HTML（趋势/对比/双轴等），内联 Chart.js，产物写入「图表/」。
  数据由 query-business-metrics 导出。Use when you need 业务图表, 指标可视化, HTML 图表, 趋势图, 周报图表, manifest 看板, chart, 或「根据 JSON 出图」。
---

# 业务图表（`business-charts`）— 第 2 段：渲染

本目录：**`.cursor/skills/business-charts/`**。

## 与取数技能的关系（先数据，后图表）

| 顺序 | 技能 | 职责 |
|------|------|------|
| **1** | **[query-business-metrics](../query-business-metrics/SKILL.md)** | 定口径、**`run_archery_query.py`** 等查数；单次指标结论以 **`查询指标/*.md`** 沉淀。需看板时再维护 **JSON**。**本段不写 HTML。** |
| **2** | **本技能** | 读 **数据 JSON + manifest**，决定页面上 **图表类型与主题色**、**业务化标题与 KPI 文案**、**每图下方分析**（`insight_lead` + 自动数据摘要），输出 **`图表/*.html`**。 |

- **通用性**：本技能只提供 **渲染器 + 示例 manifest/缓存**；具体财年或业务场景的 manifest、数据文件名放在 **`查询指标/`** 等业务目录即可。
- **场景化看板**：通用页生成后若要删减模块或改叙述，在产物 HTML 上再改，或复制 manifest 到业务目录维护。

## 主路径：`render_dashboard_html.py`

**不访问 Archery**（数据须已由第 1 段落盘）。

```bash
# 示例：使用技能内示例数据 + 示例 manifest → 图表目录
python3 .cursor/skills/business-charts/scripts/render_dashboard_html.py \
  --data .cursor/skills/business-charts/cache/example_dashboard_data.json \
  --manifest .cursor/skills/business-charts/manifests/example_dashboard.manifest.json \
  --output 图表/业务图表_manifest示例.html
```

- **manifest**：[`manifests/example_dashboard.manifest.json`](manifests/example_dashboard.manifest.json) 为结构与文案参考；复制后按业务改 `page` / `kpi` / `sections` / `footer_note`。
- **图表类型与颜色**：由 manifest 的 **`root_type`**、**`datasets[].shape`**、**`theme`** 决定；颜色来自 `render_dashboard_html.py` 中 **`THEME_PALETTE`**。

## KPI 顶行着色（仅 KPI）

- **环比/同比徽章**：**上升 = 红色，下降 = 绿色**，见 **`templates/chart-report-light.css`**（`.summary-row .badge`）。

## 样式模板（`templates/`）

| 文件 | 说明 |
|------|------|
| `chart-report-light.css` | 默认；KPI 涨红跌绿、卡片与分区标题。 |
| `chart-report-calm.css` | 低饱和、适合长时间阅读。 |
| `chart-report-spectrum.css` | 略强调渐变顶条，适合演示。 |

说明见 [`templates/README.md`](templates/README.md)。结构预览：**[`multi-chart-page.template.html`](templates/multi-chart-page.template.html)**（同级 CSS + `../vendor/chart.umd.min.js`）。

## 兼容：配置驱动（`generate_business_charts.py`）

仍可用于 **JSON 内联 `series`**、Archery 直连等流程：

```bash
python3 .cursor/skills/business-charts/scripts/generate_business_charts.py \
  --config .cursor/skills/business-charts/scripts/chart-config.example.json
```

示例配置见 **`scripts/chart-config.example.json`**；离线缓存 **`cache/example_multiseries_monthly.json`**。

**Archery 通用查数**（换参跑 SQL、ADB 合并）：见 **`query-business-metrics/scripts/run_archery_query.py`** 与 **[query-business-metrics/SKILL.md](../query-business-metrics/SKILL.md)**。

## 注意事项

- **口径**以 query-business-metrics / `查询指标/*.md` 为准。
- **Chart.js**：**`vendor/chart.umd.min.js`**，生成时 **内联** 进 HTML。
- **产出**：HTML **只** 写入仓库根目录 **`图表/`**。

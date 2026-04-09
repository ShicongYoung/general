# 图表（仅最终 HTML 产出）

本目录**只存放**对外展示的图表 HTML；脚本、缓存、Chart.js、样式模板均在 **`.cursor/skills/business-charts/`**。

| 文件 | 说明 |
|------|------|
| `FY2025_功能使用年度总结.html` | FY2025 五模块月度趋势 + 洞察（数据 `查询指标/FY2025_chart_data.json` + `render_dashboard_html.py` + `查询指标/FY2025_dashboard.manifest.json`，内联 Chart.js） |
| `FY2025_功能使用年度总结_通用图表版.html` | 配置驱动示例页（由 `generate_business_charts.py` + `chart-config.example.json` 或自建配置生成） |
| `业务图表_manifest示例.html` | manifest + `render_dashboard_html.py` 通用示例（数据与声明在 business-charts 的 `cache/example_dashboard_data.json`、`manifests/example_dashboard.manifest.json`） |

**取数**见 **`.cursor/skills/query-business-metrics/SKILL.md`**；**出图**见 **`.cursor/skills/business-charts/SKILL.md`**。

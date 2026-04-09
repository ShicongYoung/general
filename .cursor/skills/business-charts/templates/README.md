# 业务图表样式模板（`templates/`）

| 文件 | 场景 |
|------|------|
| `chart-report-light.css` | 默认浅色、卡片阴影、多色分区标题、KPI、**顶部 KPI 涨红跌绿**（`.summary-row .badge`）。 |
| `chart-report-calm.css` | 低饱和背景、柔和分割线；适合长时间阅读的复盘/周报。 |
| `chart-report-spectrum.css` | 略强调渐变分区与卡片顶条；适合对外演示稿。 |

渲染时由 manifest 的 `stylesheet` 字段选择文件名（置于本目录）。

局部预览可打开 `multi-chart-page.template.html`（需同级 CSS + `../vendor/chart.umd.min.js`）。

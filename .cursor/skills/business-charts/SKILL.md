---
name: business-charts
description: >-
  第 2 段：在结构化数据 JSON 已就绪时，用 manifest 声明图表类型、配色与业务导语，渲染通用业务看板 HTML（趋势/对比/双轴等），产物写入「图表/」。
  数据由 query-business-metrics 导出。Use when you need 业务图表, 指标可视化, HTML 图表, 趋势图, 周报图表, manifest 看板, chart, 或「根据 JSON 出图」。
---

# 业务图表（`business-charts`）— 第 2 段：渲染

本目录：**`.cursor/skills/business-charts/`**。

## 与取数技能的关系（先数据，后图表）

| 顺序 | 技能 | 职责 |
|------|------|------|
| **1** | **[query-business-metrics](../query-business-metrics/SKILL.md)** | 定口径、**`run_archery_query.py`** 等查数；单次指标结论以 **`查询指标/*.md`** 沉淀。需看板时再维护 **JSON**。**本段不写 HTML。** |
| **2** | **本技能** | 读 **数据 JSON + manifest**，决定 **图表类型与主题色**、**KPI 与图表标题文案**、**每图下方解读**（默认：`insight_lead` + 自动摘要；`trend_march`：**A 量 + C 结论**，见下节），输出 **`图表/*.html`**。 |

- **通用性**：本技能只提供 **渲染器 + 示例 manifest/缓存**；具体财年或业务场景的 manifest、数据文件名放在 **`查询指标/`** 等业务目录即可。
- **场景化看板**：通用页生成后若要删减模块或改叙述，在产物 HTML 上再改，或复制 manifest 到业务目录维护。

## 主路径：`render_dashboard_html.py`

**不访问 Archery**（数据须已由第 1 段落盘）。

```bash
# 示例：使用仓库内 FY2025 数据 + manifest → 图表目录
python3 .cursor/skills/business-charts/scripts/render_dashboard_html.py \
  --data 查询指标/FY2025_chart_data.json \
  --manifest 查询指标/FY2025_dashboard.manifest.json \
  --output 图表/FY2025_功能使用年度总结.html
```

- **可复用看板（推荐）**：当看板需要「任何指标都可复用生成」时，建议使用取数技能提供的 **skills 运行器** 做取数与临时 manifest 渲染；本技能仍只负责最终渲染 HTML。
- **看板一键生成**（含取数、写入 `查询指标/` 交付数据与 md、输出 `图表/` html）示例：

```bash
python3 .cursor/skills/query-business-metrics/scripts/run_dashboard.py all \
  --recipe <recipe_id> \
  --out-data "查询指标/<看板目录>/latest.json" \
  --snapshot-dir "查询指标/<看板目录>/snapshots" \
  --out-html "图表/<看板名>.html" \
  --out-md "查询指标/<看板名>.md"
```

- **manifest**：复制仓库内 **`查询指标/FY2025_dashboard.manifest.json`**，按业务改 `page` / `kpi` / `sections` / `footer_note`。
- **图表类型与颜色**：由 manifest 的 **`root_type`**、**`datasets[].shape`**、**`sections[].theme`** 决定；序列颜色由 **`datasets[].role`** 经 `render_dashboard_html.py` 内 **`THEME_PALETTE`** 解析。**主题名、色值与柱线 role 搭配**见模板目录内 **[`templates/theme-palette-reference.md`](templates/theme-palette-reference.md)**（与 `chart-report-*.css` 同目录，便于对照 `tone-*`）。
- **分区内布局**（`sections[].grid`）：**不写或空字符串 → 一行两列**（`chart-report-*.css` 里 `.chart-grid` 为 `1fr 1fr`）；**`one`** 单列（适合区内只有一张图、避免半行留白）；**`three`** 三列。
- **指标口径备注**：图表块可选 **`metric_notes`**（字符串数组），渲染为解读区下方的 **`<ul class="metric-notes">`**（浅色小字、每条一行）。与 `查询指标/*口径.md` 对齐维护。

## 标题与解读（manifest 约定）

### 图表标题：**动作 / 场景型**

- **用意**：让读者一眼知道「**这块业务在干什么**」，而不是堆叠指标缩写。
- **写法**：偏短句、动宾或场景；可带模块名前缀，但避免过长技术口径（口径放 `查询指标/*口径.md` 或脚注）。
- **示例**（与 FY2025 看板一致的方向）：
  - 自定义报表的**使用面与深度**（对应 PV + 活跃厂）
  - 进销存报表的**渗透与活跃**
  - TV 端**使用强度与粘性**
  - 协同任务的**创建节奏与参与厂**
  - 委外**下单、收货深度与转化**
- **KPI 卡片标题**可略短于图表标题（如「TV 版活跃厂」），仍以「谁在看、看什么」可读为先。

### 图下解读：`insight_style`

| 模式 | manifest | 输出形态 |
|------|----------|----------|
| **默认**（不写或为空） | 无 `insight_style` | **粗体「解读」** + `insight_lead`；**粗体「数据摘要」** + 脚本自动峰/谷、末月等。 |
| **`trend_weekly_e`** | `"insight_style": "trend_weekly_e"` | **周报体式 E**（对标《趋势图表-3月》口吻、更短）：**末月并列举值** → **比上月总括** → **窗口内高点（领先序列）** → **结论**；见下。 |
| **`trend_march`** | `"insight_style": "trend_march"` | **A（量）+ C（结论）**：每条序列一行末月数值与环比，再接一句定性结论。 |

**`trend_weekly_e`（FY2025 等财月 / 周报趋势推荐）**

1. **第一段**：`末月 **指标1** **值1**、**指标2** **值2**，比上月均大幅上行/均上行/…/涨跌不一。` 多序列时在一句内顿号串联；比上月用语由各序列环比**聚合**（如普遍 ≥15% 用「均大幅上行」）。  
2. **第二段**：按**第一条序列**判**窗口内最高点**是否在末月：在则「高点在末月 **xx** 附近」；否则「高点在 **xx**，末月为 **yy**」。  
3. **第三段**：`**结论**：…` 由近三月形态与全窗首末自动生成（如「中段回落后末月收回」「近三月逐月走强」「各指标短期走向分化」等）。  
4. **`insight_lead`**：当前与 `trend_march` 相同，**不使用**（可留空）。

**`trend_march`**


## KPI 顶行着色（仅 KPI）

- **环比/同比徽章**：**上升 = 红色，下降 = 绿色**，见 **`templates/chart-report-light.css`**（`.summary-row .badge`）。

## 样式模板（`templates/`）

| 文件 | 说明 |
|------|------|
| `chart-report-light.css` | 默认；KPI 涨红跌绿、卡片与分区标题。 |
| `chart-report-calm.css` | 低饱和、适合长时间阅读。 |
| `chart-report-spectrum.css` | 略强调渐变顶条，适合演示。 |

说明见 [`templates/README.md`](templates/README.md)。

## 注意事项

- **口径**以 query-business-metrics / `查询指标/*.md` 为准。
- **Chart.js**：生成的 HTML 默认引用 CDN（打开 HTML 需联网）。
- **产出**：HTML **只** 写入仓库根目录 **`图表/`**。

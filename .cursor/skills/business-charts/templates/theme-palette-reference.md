# 看板主题色与 manifest 配色参考

本文与 **`chart-report-*.css`** 同目录，说明 manifest 里 **`sections[].theme`**、**`datasets[].role`** 如何对应到图表颜色与卡片 **`tone-*`** 样式。

**单一事实来源**：三色十六进制以渲染脚本 [`../scripts/render_dashboard_html.py`](../scripts/render_dashboard_html.py) 中的 **`THEME_PALETTE`** 为准；下表与脚本保持一致，修改色盘时请同步更新本文件。

## `THEME_PALETTE`：每组 `(primary, secondary, tertiary)`

| `theme` | primary | secondary | tertiary | 观感说明 |
|---------|---------|-----------|----------|----------|
| `blue` | `#4361ee` | `#7b8cde` | `#f97316` | 默认蓝系；第三色偏橙，适合「量级 + 对比线」冷暖分轨 |
| `teal` | `#0f766e` | `#2dd4bf` | `#0ea5e9` | 青绿 + 天蓝 |
| `green` | `#15803d` | `#4ade80` | `#ca8a04` | 绿 + 黄棕点缀 |
| `purple` | `#6d28d9` | `#a78bfa` | `#e11d48` | 紫 + 玫红点缀 |
| `orange` | `#c2410c` | `#fb923c` | `#0d9488` | 橙 + 青绿点缀 |
| `indigo` | `#4338ca` | `#818cf8` | `#db2777` | 靛紫 + 粉点缀 |
| `crimson` | `#9f1239` | `#fb7185` | `#0369a1` | 酒红 + 粉 + 蓝点缀 |
| `slate` | `#334155` | `#64748b` | `#0ea5e9` | 中性 slate + 天蓝第三色，避免「蓝柱 + 绿线」硬凑 |
| `cyan` | `#0e7490` | `#06b6d4` | `#6366f1` | 青蓝主/次 + 靛紫第三色，冷色家族内分层 |

各 `theme` 在 HTML 中还会驱动 **`chart-card.tone-{theme}`**、**`.section-title.{theme}`**、**`.insight.{theme}`**（见各 `chart-report-*.css`）。

## `datasets[].role` 与 `role_color()`

规则（与脚本一致）：

- **`primary`** → 色盘第 1 色（`primary`）
- **`secondary`** → 色盘第 2 色
- **`tertiary`** → 色盘第 3 色
- **`contrast`** → 固定 **`#475569`**（中性灰蓝，常用作第二条折线、对比序列）

未写 `role` 时默认为 `primary`；多序列会按数据集索引在色盘上轮换，**柱线混合图建议显式写 `role`**。

## 柱 + 折线搭配建议

- **柱 + 单折线**：柱 **`primary`**；折线 **`secondary`**（同色系深浅）或 **`contrast`**（中性、最不抢色相）。
- **柱 + 双折线**：柱 **`primary`**；第一条线 **`secondary`**，第二条 **`tertiary`** 或 **`contrast`**（避免两条线都与柱形成「蓝 + 绿」等低协调组合）。

## 与 `datasets[].color` 的关系

若 manifest 中存在 **`color`** 字段，当前 **`render_dashboard_html.py` 仍以 `role_color(theme, role, di)` 为准**（不读取 `color`）。需要自定义 hex 时应在脚本中扩展逻辑，或改用手写 HTML。

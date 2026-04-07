---
name: trend-chart
description: 生成核心指标趋势图表 HTML，支持自定义时间范围（近N周、近N个月、指定起止日期）。Use when the user asks for 趋势图、指标趋势、近X个月、近X周、半年趋势、图表分析、trend chart。
---

# 核心指标趋势图表

## 适用场景

当用户需要查看一段时间内核心指标的趋势变化时，执行本技能。输出一个 HTML 文件，包含委外管理、协同任务两大分区，共 6 张折线图，每图下方附自动洞察。

## 支持的时间范围表达

| 用户说法 | 对应参数 |
|---------|---------|
| 近4周（默认） | 不传参数 |
| 近12周 / 近3个月 | `--recent-weeks 12` 或 `--recent-months 3` |
| 近半年 | `--recent-months 6` |
| 近1年 | `--recent-months 12` |
| 指定起止日期 | `--start 2026-01-01 --end 2026-06-30` |
| 指定起始到今天 | `--start 2026-01-01` |

## 执行步骤

1. 根据用户描述的时间范围，选择对应参数
2. 运行脚本：
   ```bash
   python3 .cursor/skills/weekly-core-metrics/scripts/generate_trend_chart.py [参数]
   ```
3. 脚本自动输出 HTML 到 `周报/趋势图表-{范围描述}.html`
4. 告知用户文件路径，并基于脚本打印的汇总表做简要分析

## 典型命令示例

```bash
# 近3个月
python3 .cursor/skills/weekly-core-metrics/scripts/generate_trend_chart.py --recent-months 3

# 近半年
python3 .cursor/skills/weekly-core-metrics/scripts/generate_trend_chart.py --recent-months 6

# 近12周
python3 .cursor/skills/weekly-core-metrics/scripts/generate_trend_chart.py --recent-weeks 12

# 指定自定义范围
python3 .cursor/skills/weekly-core-metrics/scripts/generate_trend_chart.py --start 2026-01-01 --end 2026-06-30

# 指定输出路径
python3 .cursor/skills/weekly-core-metrics/scripts/generate_trend_chart.py --recent-months 3 --output 周报/Q1趋势.html
```

## 图表内容

### 委外管理（蓝色区）
- **客户规模趋势**：覆盖客户数（有订单+有收发）+ 委外订单客户数
- **客户留存率趋势**：上周活跃→本周仍活跃的比例
- **订单→收发货转化率**：覆盖客户数 / 订单客户数

### 协同任务（绿色区）
- **客户规模趋势**：活跃客户数（≥2天创建任务）+ 创建任务客户数
- **客户留存率趋势**：上周活跃→本周仍活跃的比例
- **活跃转换率 & 工单关联比例**：双折线

## 注意事项

- 数据来源：Archery / 小工单生产库（ADB_01/02/03 三实例加总）
- 留存率计算：使用标量 COUNT SQL（不依赖 limit_num），第一周无上周基准显示为空
- 若范围超过半年（>26周），查询时间较长（约每周5秒），请耐心等待
- Token 失效时更新 `.cursor/skills/weekly-core-metrics/scripts/config.json` 中的 `csrftoken` / `sessionid`

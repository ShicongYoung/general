---
name: weekly-core-metrics
description: 一次触发完成周报：先查询委外管理和协同任务固定指标，再使用当前对话中的大模型生成洞察和结论，最终写入周报文件。Use when the user asks for weekly report, 核心指标, 委外管理指标, 协同任务指标, 环比分析, 或周报洞察。
---

# Weekly Core Metrics

## 适用场景

当用户需要生成周报中的核心指标与洞察时，执行本技能。

## 固定指标范围

- 委外管理：
  - 覆盖客户数：一周内既创建过委外订单，又有收发记录的客户
  - 客户留存率：本周覆盖客户数/近2周覆盖客户数
  - 委外订单客户数：一周内有创建过委外订单的客户
  - 订单到收发货转换率：本周委外覆盖的客户数/本周委外订单客户数（有订单客户中产生收发记录的比例；原「仅下单」分母易导致比率超过 100%，故采用此口径）
- 协同任务：
  - 覆盖客户数：一周内有任意2天创建任务的客户
  - 客户留存率：本周覆盖客户数/近2周覆盖客户数
  - 创建协同任务客户数：一周内创建过任务的客户数
  - 活跃客户转换率：一周内有2天创建任务的客户数/一周内创建过任务的客户数
  - 从工单创建协同任务的比例：associate_id 不为空的任务数/一周内总的任务数

## 周期规则

- 本周：本周一 ~ 本周日
- 近2周：上周一 ~ 本周日
- 本月：这个月第一天~最后一天

## 一句话触发

用户只需说：`生成本周核心模块周报`

## 执行步骤（技能内部自动完成）

1. 检查配置文件是否存在：`.cursor/skills/weekly-core-metrics/scripts/config.json`
2. 如果不存在，先从模板复制并填写：
   - `cp .cursor/skills/weekly-core-metrics/scripts/config.example.json .cursor/skills/weekly-core-metrics/scripts/config.json`
3. 重点检查 `auth.csrftoken` 和 `auth.sessionid` 是否为最新值（失效就更新）。
4. 运行脚本：
   - `python3 .cursor/skills/weekly-core-metrics/scripts/generate_weekly_report.py`
5. 脚本会自动输出到：
   - `周报/{xx月第x周周报}-杨士聪.md`（例如 `周报/03月第4周周报-杨士聪.md`）
6. 脚本会同时输出结构化数据：
   - `周报/latest_metrics.json`
7. 读取 `latest_metrics.json`，使用**当前对话的大模型能力**为每个指标生成：
   - `洞察结果`
   - `结论/改进建议`
8. 将 LLM 结果写回对应周报 markdown 文件，确保最终表格完整可直接使用。

## 输出格式

必须输出以下列：

`核心指标 | 指标口径 | 本周结果 | 上周结果 | 环比 | 洞察结果 | 结论/改进建议`

## 指标口径说明

- 委外“覆盖客户数”在当前脚本中定义为：周期内在 `dt_outsource_order` 有订单且在 `dt_outsource_post` 有收发记录的客户交集。
- 协同任务“覆盖客户数”定义为：周期内 `dt_collaborative_task` 按客户统计，至少 2 天有创建任务。
- 如后续确认更精确字段（如收发货状态字段），可直接调整脚本 SQL。

## 注意事项

- 接口 token 会频繁失效；脚本报鉴权错误时，优先更新 `config.json` 的 token。
- 业务数据分布在 3 个实例，脚本会分实例查询并汇总。
- 如需临时自定义输出路径，可加参数：`--output your_path.md`。
- 不依赖你自己的模型 API Key；分析步骤使用当前对话中的大模型完成。

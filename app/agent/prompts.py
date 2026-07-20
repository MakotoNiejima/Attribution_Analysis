"""
提示词模板

用于：
- 问题解析：从用户问题中提取分析参数
- 报告生成：基于证据生成分析报告
- 证据校验：验证报告结论是否有证据支持
"""

# ============================================================
# 问题解析提示词
# ============================================================

PARSE_QUESTION_PROMPT = """你是一个经营分析助手。用户会提出关于业务指标的问题，你需要从中提取分析参数。

用户问题：{user_question}

当前日期：{current_date}

本演示数据库可用的分析窗口（结束日期为排他边界）：
- 基准期：{available_baseline_start} 至 {available_baseline_end}
- 当前期：{available_current_start} 至 {available_current_end}

请从问题中提取以下信息，并以JSON格式返回：

1. problem：标准化的问题描述（一句话）
2. start_date：分析周期开始日期（格式：YYYY-MM-DD）
3. end_date：分析周期结束日期（格式：YYYY-MM-DD）
4. compare_start：对比周期开始日期（可选）
5. compare_end：对比周期结束日期（可选）
6. dimensions：需要分析的维度列表，可选值：channel（渠道）、device（设备）、region（地区）、user_type（用户类型）
7. is_complete：信息是否完整（bool）
8. clarification：如果信息不完整，需要追问的问题（string）

规则：
- 如果用户说"本月"，使用当前月份
- 如果用户说"上月"，使用上个月
- 本演示中，用户说"本月"或"上月"时，必须使用上述可用窗口，不得自行扩展到没有数据的日期
- 如果用户没有指定对比周期，默认对比上一个同等长度的周期
- 如果用户没有指定维度，默认分析所有维度
- 如果时间范围不明确，is_complete设为false

返回格式（只返回JSON，不要其他文字）：
```json
{{
    "problem": "...",
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "compare_start": "YYYY-MM-DD",
    "compare_end": "YYYY-MM-DD",
    "dimensions": ["channel", "device"],
    "is_complete": true,
    "clarification": null
}}
```"""


PARSE_QUESTION_WITH_HISTORY_PROMPT = """你是一个经营分析助手。用户正在多轮对话中逐步补充分析所需信息。

## 历史对话
{history_text}

## 用户最新消息
{user_question}

## 当前日期
{current_date}

## 可用分析窗口（结束日期为排他边界）
- 基准期：{available_baseline_start} 至 {available_baseline_end}
- 当前期：{available_current_start} 至 {available_current_end}

## 任务
结合历史对话和用户最新消息，提取完整的分析参数。

特别注意：
- 如果历史中有追问（status=clarify），用户最新消息很可能是对追问的补充回答
- 将历史中已明确的信息（如指标、维度）与最新补充合并
- 如果历史中已有已完成的分析（status=completed），最新消息可能是追问或深入分析

请以JSON格式返回（字段含义同上）：
```json
{{
    "problem": "合并后的完整问题描述",
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "compare_start": "YYYY-MM-DD",
    "compare_end": "YYYY-MM-DD",
    "dimensions": ["channel", "device"],
    "is_complete": true,
    "clarification": null
}}
```"""


# ============================================================
# 报告生成提示词
# ============================================================

GENERATE_REPORT_PROMPT = """你是一个经营分析报告撰写助手。请根据以下分析结果和证据，生成一份结构化的分析报告。

## 问题
{problem}

## 分析结果

### 整体漏斗
- 基准期（{baseline_period}）转化率：{baseline_rate}%
- 当前期（{current_period}）转化率：{current_rate}%
- 变化：{rate_change}%

### 漏斗环节分解
{stage_breakdown}

### 渠道维度
{channel_breakdown}

### 设备维度
{device_breakdown}

### 匹配的业务事件
{business_events}

### 上传附件中的补充证据（仅在结果与附件原文一致时引用）
{attachment_evidence}

### 相关业务文档（仅作参考，不可替代数据证据）
{retrieved_docs}

## 要求

1. 报告必须包含以下部分：
   - 问题定义
   - 关键指标
   - 主要发现（按影响程度排序）
   - 归因结论
   - 待补充数据
   - 下一步建议

2. **重要约束**：
   - 每个结论必须有证据支持，不能编造原因
   - 数字必须逐字使用上方分析结果中的实际数值；不得自行重新计算、估算或引入百分比占比
   - 禁止写出“超过70%”“约占一半”等上方没有直接提供的量化结论
   - 时间范围必须逐字使用上方的基准期和当前期，不得写成整月或其他日期
   - 如果某个维度没有显著发现，不要强行解释
   - 业务事件只能复述给定事件，并使用“同一时期存在……事件，可能与……异常同时出现，仍需进一步验证”的表述
   - 业务事件不得使用”导致、造成、直接影响、高度相关、证明、最直接问题”等因果或强关联措辞，也不能添加事件中未提供的细节
   - 文档片段仅作为背景参考信息；如需引用，必须使用”根据文档《xxx》第X段，……”的格式，并标注 [来源: xxx]
   - 文档片段不得替代数据证据；数据结论仍必须基于上方漏斗和维度数据
   - 如果文档内容与数据证据矛盾，以数据证据为准

3. 格式要求：
   - 使用Markdown格式
   - 关键数字加粗
   - 结论要有依据

请生成报告："""


# ============================================================
# 证据校验提示词
# ============================================================

VALIDATE_REPORT_PROMPT = """请检查以下分析报告中的每条结论，是否都有对应的证据支持。

## 报告内容
{report}

## 可用证据
{evidence_summary}

## 校验规则
1. 每个数字结论必须能在证据中找到对应数值
2. 每个归因结论必须有维度拆解数据支持
3. 业务事件只能作为关联因素，不能作为直接原因
4. 不能出现证据中没有的数字或结论
5. 证据中的百分比允许与报告相差不超过 0.01 个百分点的展示性四舍五入
6. “业务事件”部分出现的事件可以作为关联因素，但报告必须明确使用“可能关联”而非因果表述
7. 如果报告把业务事件描述为“导致、造成、直接影响、高度相关、证明、最直接问题”，或基于事件给出未验证的修复结论，则必须判定为无效

请以JSON格式返回校验结果：
```json
{{
    "is_valid": true,
    "errors": [],
    "warnings": []
}}
```

如果发现错误，errors列表中说明具体问题。"""


# ============================================================
# 附件相关性判断与查询计划提示词
# ============================================================

ATTACHMENT_QUERY_PROMPT = """你是一个数据分析助手。用户上传了一份文件作为分析的补充数据。

## 文件预览
文件名：{filename}
总行数：{row_count}
列名：{columns}
前5行数据：
{preview}

## 当前分析的关键发现
{key_findings}

## 任务
判断这个文件是否与当前分析相关。如果相关，生成查询计划。

规则：
1. 只有文件中的列与分析发现有明确关联时才算相关
2. 不要强行关联——如果文件内容跟分析问题无关，返回 is_relevant=false
3. 查询计划应尽量精确（指定 filters 和 columns），避免返回大量无关数据

请以JSON格式返回：
```json
{{
    "is_relevant": true,
    "reason": "简述为什么相关",
    "queries": [
        {{
            "description": "查询描述",
            "action": "query 或 aggregate",
            "filters": {{"列名__gte": "值"}},
            "columns": ["列1", "列2"],
            "group_by": "分组列名（仅aggregate需要）",
            "metrics": {{"列名": "sum/avg/count"}},
            "limit": 50
        }}
    ]
}}
```

如果 is_relevant=false，queries 返回空列表。"""


# ============================================================
# 提取关键发现提示词
# ============================================================

EXTRACT_FINDINGS_PROMPT = """请从以下分析结果中提取关键发现。

## 分析结果
{analysis_result}

## 提取规则
1. 只提取效应绝对值最大的前3个发现
2. 每个发现必须包含：维度、分组、效应值、证据引用
3. 优先提取负向异常（转化率下降的分组）
4. 如果某个维度的效应很小（绝对值<0.1%），不要提取

请以JSON格式返回：
```json
{{
    "findings": [
        {{
            "dimension": "渠道",
            "group": "organic",
            "effect": -0.6476,
            "effect_type": "total",
            "evidence_ref": "channel_decomposition.contributions[organic].total_effect",
            "description": "自然流量渠道对整体转化率下降贡献最大"
        }}
    ]
}}
```"""

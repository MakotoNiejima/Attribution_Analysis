# LangGraph Agent 模块

## 目录结构

```
app/agent/
├── __init__.py     # 模块导出
├── state.py        # 图状态定义
├── nodes.py        # 各节点函数
├── graph.py        # LangGraph 编排
├── prompts.py      # 提示词模板
├── test_agent.py   # 测试脚本
└── README.md       # 本文件
```

## 设计原则

1. **LLM 只负责理解和生成**，不负责计算
2. **数字计算完全由 analysis_core 负责**，LLM 只读取结果
3. **每条结论必须有证据支持**，不能编造原因
4. **业务事件只是关联因素**，不能直接说"导致了"

## 流程图

```
用户问题
  ↓
parse_question: 解析问题与时间范围
  ↓
check_completeness: 信息是否完整？
  ├─否→ ask_clarification: 追问用户 → END（等待回复）
  └─是→ build_request: 构造 AnalysisRequest
          ↓
        run_analysis: 调用 run_conversion_analysis
          ↓
        extract_findings: 提取主要发现与证据
          ↓
        generate_report: LLM 生成报告草稿
          ↓
        validate_report: 证据校验
          ↓
        finalize: 最终结构化报告
          ↓
        END
```

## 使用方式

### 1. 设置环境变量

```bash
# .env 文件
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1  # 可选
LLM_MODEL=gpt-4o-mini  # 可选
```

### 2. 运行分析

```python
from app.agent import run_analysis_pipeline

result = run_analysis_pipeline("为什么本月整体转化率比上月下降了？")

if result.report_final:
    print(result.report_final)
elif result.clarification_question:
    print(result.clarification_question)
```

### 3. 测试（不依赖LLM）

```bash
python app/agent/test_agent.py
```

## 状态说明

`AnalysisState` 包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| user_question | str | 用户原始问题 |
| parsed_problem | str | 解析后的标准问题 |
| parsed_start/end | datetime | 解析后的时间范围 |
| is_info_complete | bool | 信息是否完整 |
| clarification_question | str | 追问问题 |
| analysis_result | dict | 分析结果 |
| key_findings | list | 关键发现 |
| evidence | dict | 证据 |
| matched_events | list | 匹配的业务事件 |
| report_draft | str | 报告草稿 |
| report_final | str | 最终报告 |
| validation_errors | list | 证据校验错误 |
| errors | list | 流程错误 |

## 节点说明

| 节点 | 职责 | 输入 | 输出 |
|------|------|------|------|
| parse_question | 从自然语言提取参数 | user_question | parsed_* |
| check_completeness | 检查信息完整性 | parsed_* | complete/clarify |
| ask_clarification | 生成追问问题 | - | clarification_question |
| build_request | 构造分析请求 | parsed_* | analysis_request |
| run_analysis | 调用分析服务 | analysis_request | analysis_result |
| extract_findings | 提取关键发现 | analysis_result | key_findings |
| generate_report | LLM生成报告 | analysis_result + evidence | report_draft |
| validate_report | 校验证据一致性 | report_draft + evidence | validation_errors |
| finalize | 添加声明，输出最终报告 | report_draft | report_final |

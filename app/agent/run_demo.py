"""
Agent 演示脚本

使用 DeepSeek 运行完整的分析流程
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from app.agent import run_analysis_pipeline


def main():
    print("=" * 60)
    print("经营归因分析系统 - LangGraph 演示")
    print("=" * 60)

    # 测试问题
    question = "为什么本月整体转化率比上月下降了？"
    print(f"\n问题: {question}")
    print("-" * 60)

    # 运行分析
    result = run_analysis_pipeline(question)

    # LangGraph 返回字典
    print("\n[结果]")
    print(f"  下一步动作: {result.get('next_action', 'unknown')}")

    if result.get("errors"):
        print(f"  错误: {result['errors']}")

    if result.get("clarification_question") and result.get("next_action") == "clarify":
        print(f"  追问: {result['clarification_question']}")

    if result.get("parsed_problem"):
        print(f"  解析问题: {result['parsed_problem']}")

    if result.get("key_findings"):
        print(f"\n  关键发现 ({len(result['key_findings'])}条):")
        for f in result["key_findings"][:3]:
            print(f"    - {f['dimension']}-{f['group']}: {f['effect']*100:+.4f}%")

    if result.get("matched_events"):
        print(f"\n  匹配事件 ({len(result['matched_events'])}条):")
        for e in result["matched_events"][:3]:
            print(f"    - {e['title']}")

    if result.get("report_final"):
        print(f"\n  报告已生成 ({len(result['report_final'])}字)")
        print("\n" + "=" * 60)
        print("完整报告")
        print("=" * 60)
        print(result["report_final"])
    elif result.get("report_draft"):
        print(f"\n  报告草稿已生成 ({len(result['report_draft'])}字)")
        print("\n" + "=" * 60)
        print("报告草稿")
        print("=" * 60)
        print(result["report_draft"])
    else:
        print("\n  未生成报告")


if __name__ == "__main__":
    main()

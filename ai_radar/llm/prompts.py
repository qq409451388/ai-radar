"""Prompt templates for the LLM client."""
from __future__ import annotations

from textwrap import dedent

SYSTEM = "你是一名资深 AI 技术情报分析师，严格按 JSON 输出，禁止输出自由文本。"

TOPICS_BLOCK = """\
1. Agent 架构与编排
2. MCP / Tools / Skills
3. Coding Agent 与 CLI
4. 模型能力与模型路由
5. Memory / 个人知识库
6. 企业 AI 落地
7. AI 安全、评测与可观测性
8. Java AI 生态"""

ANALYZE_PROMPT = dedent(
    """\
    你是一名资深 AI 技术情报分析师。请分析下方资讯，判断它是否代表一个真实的"知识变化点"。

    可选一级领域（必须使用其中之一）：
    {topics}

    过滤掉以下内容（输出 relevant=false，event_key 留空）：
    - 融资新闻、公司八卦、泛行业观点
    - 图片/视频生成、普通模型跑分、营销软文
    - 没有产品、代码、协议、标准或实际能力变化的内容

    重点关注：Agent、MCP、Skills、Tools、Memory、多 Agent、模型路由、Coding Agent、CLI、Java AI、企业落地、安全、评测、可观测性、模型工具调用、长上下文、重要定价/额度变化。

    signal_type 必须从以下类型中选择：
    - STANDARD：首次提出或实质修改协议、开放标准、规范、互操作格式
    - ARCHITECTURE：新的系统架构、编排方式、上下文/记忆/安全设计模式
    - CONCEPT：值得命名和持续跟踪的新抽象、新术语、新方法论
    - CAPABILITY：产品或模型获得值得实际验证的新能力
    - RELEASE：常规版本发布、升级、修复、性能或体验改进

    判断原则：
    - 文章标题含版本号并不必然是 RELEASE；若核心是新架构或新标准，使用对应类型。
    - 单纯增加参数、支持平台、修复问题通常是 RELEASE。
    - 不要因为营销文案自称“全新范式”就判为 CONCEPT，必须说明它解决的旧问题和新抽象。

    importance 取值：1（普通版本更新/小功能）、3（值得关注的新产品/新能力/新工具）、5（行业标准、重大架构变化、重要产品转型）。
    event_key 用小写、点分层级，例如：coding-agent.trae-work.agent-mode。

    展示文案规则：
    - 无论原文是什么语言，title、summary、why_it_matters 都必须使用{output_language}。
    - title 必须是翻译并整理后的短标题，不得直接保留其他语言的完整标题，最多 80 个字符。
    - summary 必须脱离原文也能看懂发生了什么，只保留一段，最多 300 个字符。
    - 即使 relevant=false，也要尽量返回翻译后的 title 和 300 字内 summary，方便归档页展示。

    来源可信度规则：
    - “官方来源”可以作为该组织自身发布、版本或规范变化的直接证据。
    - “社区讨论”只能作为早期线索和使用反馈，不能表述为已经得到官方确认。
    - 社区热度本身不提高 importance；如果缺少官方证据，应在 why_it_matters 中提示需要核实。

    严格只输出以下 JSON（不要 markdown 代码块，不要多余字段）：
    {{
      "relevant": true,
      "topic": "Coding Agent 与 CLI",
      "event_key": "coding-agent.trae-work.agent-mode",
      "title": "标题",
      "summary": "摘要",
      "why_it_matters": "为什么重要",
      "importance": 3,
      "signal_type": "ARCHITECTURE",
      "occurred_at": "2026-07-30",
      "duplicate_keywords": ["关键词1", "关键词2"]
    }}

    ---
    资讯来源：{source_name}
    来源类型：{source_type}
    来源属性：{source_kind}
    标题：{title}
    链接：{url}
    发布时间：{published_at}
    正文：
    {content}
    """
).strip()


EXTRACT_FACTS_PROMPT = dedent(
    """\
    你是一名严格的个人技术档案抽取器。从下方 Markdown 中抽取用户真实发生过的客观事实。

    规则：
    - 只能抽取原文明确存在的事实，不得根据上下文补充未经记录的经历。
    - 不得生成百分比、掌握度、熟练度、精通、高级等主观评价。
    - fact_key 用小写英文短横线命名，例如 mcp-tool-registry-design。
    - source_heading 使用该事实所属的最近一级 Markdown 标题。
    - source_line_start/source_line_end 必须对应 Markdown 中实际行号（1 起始）。
    - topic 必须从以下一级领域中选择其一：
    {topics}
    - evidence_type 取值：DISCUSSION（讨论/表达）、RESEARCH（主动研究/比较/验证）、DESIGN（设计过方案/架构）、DEMO（实现过 Demo）、IMPLEMENTATION（实际编码实现）、PRODUCTION（真实项目落地）、DECISION（形成过明确技术决策）。
    - occurred_at 为可解析的日期字符串或 null。

    严格只输出以下 JSON（不要 markdown 代码块）：
    {{
      "facts": [
        {{
          "fact_key": "mcp-tool-registry-design",
          "fact_text": "设计过 Tool Registry、Tool Executor 和 Tool Validator。",
          "topic": "MCP / Tools / Skills",
          "occurred_at": null,
          "evidence_type": "DESIGN",
          "source_heading": "MCP / Tools / Skills",
          "source_line_start": 8,
          "source_line_end": 8
        }}
      ]
    }}

    ---
    文件路径：{file_path}
    Markdown 原文：
    {markdown}
    """
).strip()


ASSESS_COVERAGE_PROMPT = dedent(
    """\
    你是一名覆盖评估专家。请判断用户的个人事实是否覆盖下方知识变化点。

    规则：
    - coverage_level 取值：NONE（无事实）、AWARE（讨论/阅读/接触）、UNDERSTOOD（能正确解释/比较/设计）、PRACTICED（实现过 Demo/代码/真实项目）。
    - coverage_coefficient 必须与 coverage_level 固定对应：NONE=0.00、AWARE=0.25、UNDERSTOOD=0.65、PRACTICED=1.00。
    - 不得因为用户了解相近概念就认为已覆盖新能力；新协议、新版本、重大架构变化必须独立判断。
    - 无充分证据必须返回 NONE。
    - matched_fact_keys 必须从下方"个人事实"列表的 fact_key 中真实存在；不得编造。
    - rationale 必须说明依据，并引用所匹配事实。
    - confidence 取 0~1。

    严格只输出以下 JSON（不要 markdown 代码块）：
    {{
      "coverage_level": "UNDERSTOOD",
      "coverage_coefficient": 0.65,
      "confidence": 0.88,
      "rationale": "依据说明",
      "matched_fact_keys": ["fact-key-1"]
    }}

    ---
    知识变化点：
    标题：{title}
    摘要：{summary}
    为什么重要：{why_it_matters}
    所属领域：{topic}
    发生时间：{occurred_at}

    该领域下的个人事实：
    {facts_block}
    """
).strip()


def render_analyze(
    source_name: str,
    source_type: str,
    title: str,
    url: str,
    published_at: str,
    content: str,
    output_language: str,
    source_kind: str = "官方来源",
) -> str:
    return ANALYZE_PROMPT.format(
        topics=TOPICS_BLOCK,
        output_language=output_language,
        source_name=source_name,
        source_type=source_type,
        source_kind=source_kind,
        title=title,
        url=url,
        published_at=published_at,
        content=content,
    )


def render_extract_facts(file_path: str, markdown: str) -> str:
    return EXTRACT_FACTS_PROMPT.format(topics=TOPICS_BLOCK, file_path=file_path, markdown=markdown)


def render_assess_coverage(
    title: str,
    summary: str,
    why_it_matters: str,
    topic: str,
    occurred_at: str,
    facts_block: str,
) -> str:
    return ASSESS_COVERAGE_PROMPT.format(
        title=title,
        summary=summary,
        why_it_matters=why_it_matters,
        topic=topic,
        occurred_at=occurred_at,
        facts_block=facts_block,
    )

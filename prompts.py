"""Prompt templates — 獨立成檔方便日後調整。"""

from __future__ import annotations

SUMMARIZE_PROMPT = """你是 AI paper reviewer。把下面這篇 paper 用台灣口語繁體中文做結構化摘要。

規則：
- 避免翻譯腔（不要「值得注意的是」「綜上所述」）
- 用「這篇」而非「本研究 / 本文」
- 英文專有名詞（模型名、方法名、dataset 名）可保留原文

Title: {title}
Abstract: {abstract}

只回 JSON（不要 ``` fence），格式：
{{
  "tldr": "一到兩句話（≤ 60 字）講這篇做了什麼 + 為什麼有趣",
  "venue": "",
  "strengths": ["優點1", "優點2"],
  "limitations": ["限制1", "限制2"],
  "open_questions": ["開放問題 / 後續研究方向1"],
  "future_work": ["作者明確提到的 future work 1"],
  "tags": ["tag1", "tag2"]
}}

欄位：
- tldr：單段，不超過 60 字
- venue：abstract 若提到投稿會議/期刊（例 "accepted at CVPR 2025"）就填「CVPR 2025」；沒提填空字串
- strengths：2-3 點短句，講這篇的貢獻 / 亮點
- limitations：2-3 點短句，講能看出的限制或待解決問題；看不出就寫「abstract 資訊不足，無法評估」
- open_questions：這篇提出但沒解決的問題 / 從 abstract 合理推測的後續研究題目；看不出就空 list []
- future_work：作者在 abstract 裡明確說之後要做什麼；沒提就空 list []
- tags：2-4 個小寫連字號英文詞，例 ["llm", "rag", "vision-language"]
"""


NOTION_PUSH_PROMPT = """讀 {summaries_path}。

把這批論文寫進 Notion 的一個叫 "AI Paper Radar" 的 database（parent 是 {parent_page_url}）。

Step 1：找 database
- 用 notion-search 找標題 "AI Paper Radar" 且 parent 是 {parent_page_url} 的 database，拿它的 ID

Step 2：若沒找到，用 notion-create-database 建一個，parent_page_url={parent_page_url}，properties（完整 schema）：
  - Title — title
  - Year — number
  - Venue — rich_text
  - Link — url
  - Code — url
  - TL;DR — rich_text
  - Strengths — rich_text
  - Limitations — rich_text
  - Open Questions — rich_text
  - Future Work — rich_text
  - Authors — rich_text
  - Citations — number
  - Influential Citations — number
  - Watched — checkbox
  - My Notes — rich_text
  - Tags — multi_select
  - Date — date

Step 2b（很重要）：若 database 已存在但缺少上面任何一個 property，用 notion-update-data-source 把缺的補上，型別要對。**不要**改已存在 property 的型別，只補缺的。

Step 3：用 notion-create-pages 把 summaries.json 每篇塞成一個 row（parent 是上面的 database）：
  - Title = paper.title
  - Year = paper.year
  - Venue = paper.venue（可能空）
  - Link = paper.arxiv_url
  - Code = paper.github_url（空就不設）
  - TL;DR = paper.tldr
  - Strengths = paper.strengths 用 "• xxx\\n• yyy" 形式串成一段 rich_text
  - Limitations = 同上，用 paper.limitations
  - Open Questions = 同上，用 paper.open_questions
  - Future Work = 同上，用 paper.future_work
  - Authors = paper.authors 用 ", " 串起來
  - Citations = paper.citation_count（可能 0）
  - Influential Citations = paper.influential_citation_count（可能 0）
  - Watched = paper.watched (bool)
  - My Notes = 留空
  - Tags = paper.tags
  - Date = {date}

Step 4：只回一個 JSON（不要 fence）：
{{"notion_url": "https://www.notion.so/..."}}
notion_url 是 database 的 URL，不是單篇 row。
"""


EXPLAIN_FIGURE_PROMPT = """這是一篇 AI paper 的 Figure 1 原始 caption：

Title: {title}
Caption: {caption}

用台灣口語繁體中文，**不超過 40 字**，一句話濃縮這張圖到底在講什麼。
- 避免翻譯腔（不要「這張圖展示了」「本圖顯示」開頭）
- 直接講圖的重點，不用複述 caption 內的每個細節
- 英文專有名詞可保留原文

只回一段純文字，不要 JSON、不要 ``` fence。
"""


BOT_SYSTEM_PROMPT = """你是使用者的 coding 助手，透過 Telegram 對話。
- 預設用繁體中文回答，除非問題本身是英文
- 程式碼用 ``` fence 包起來
- Telegram 訊息上限 4096 字元，回覆盡量精簡
- 不要編造 API、函式名、或檔案路徑
"""


def build_chat_prompt(
    history: list[dict],
    current: str,
    todays_papers: list[dict] | None = None,
    paper_fulltext: str | None = None,
) -> str:
    """Assemble system prompt + optional papers + optional fulltext + history + current.

    ``paper_fulltext`` is the full markdown of a single paper the user is asking
    about in depth. Placed between the short summaries block and the dialog
    history so it cache-aligns by paper.
    """
    parts = [BOT_SYSTEM_PROMPT]
    if todays_papers:
        parts.append("--- 今日 paper_radar 推播的論文 ---")
        for i, p in enumerate(todays_papers, start=1):
            bits = [f'{i}. "{p.get("title", "")}"']
            if p.get("year"):
                bits.append(f"({p['year']})")
            line = " ".join(bits)
            parts.append(line)
            if p.get("tldr"):
                parts.append(f"   tldr: {p['tldr']}")
            if p.get("arxiv_url"):
                parts.append(f"   link: {p['arxiv_url']}")
            if p.get("tags"):
                parts.append(f"   tags: {', '.join(p['tags'])}")
    if paper_fulltext:
        parts.append("--- 使用者提到那篇的論文全文（markdown）---")
        parts.append(paper_fulltext)
    if history:
        parts.append("--- 對話歷史 ---")
        for h in history:
            parts.append(f"{h['role']}: {h['text']}")
    parts.append("--- 目前提問 ---")
    parts.append(f"user: {current}")
    return "\n".join(parts)

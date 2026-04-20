"""Prompt templates — 獨立成檔方便日後調整。"""

from __future__ import annotations

SUMMARIZE_PROMPT = """你是一個科普寫手。把下面這篇 AI paper 用「三句話」介紹給台灣的中學生。

規則：
- 第一句：這篇做了什麼（不准用英文專有名詞，要翻譯或比喻）
- 第二句：為什麼有趣 / 解決什麼痛點
- 第三句：跟以前的方法比，新在哪
- 全程用台灣口語繁體中文
- 避免翻譯腔（不要「值得注意的是」「綜上所述」這類）
- 不要用「本研究」「本文」這類學術用語，用「這篇」就好

Title: {title}
Abstract: {abstract}

只回 JSON，格式如下：
{{
  "summary_zh": "三句話摘要（用全形句號分隔）",
  "tags": ["tag1", "tag2", "tag3"]
}}

tags 用 2-4 個英文短詞（小寫、連字號），譬如 ["llm", "rag", "vision-language"]。
"""


NOTION_PUSH_PROMPT = """讀 {summaries_path}。
在我的 Notion workspace 裡，{parent_page_url} 這個 page 底下建一個新的子 page。
Page title: "AI Radar - {date}"
Page 內容對每篇 paper 加入：
  - heading_3: title
  - paragraph: summary_zh
  - bookmark: arxiv_url
  - paragraph (italic, 小字): tags · upvotes · hf_url
  - divider
完成後只回傳一個 JSON: {{"notion_url": "https://www.notion.so/..."}}
"""


BOT_SYSTEM_PROMPT = """你是使用者的 coding 助手，透過 Telegram 對話。
- 預設用繁體中文回答，除非問題本身是英文
- 程式碼用 ``` fence 包起來
- Telegram 訊息上限 4096 字元，回覆盡量精簡
- 不要編造 API、函式名、或檔案路徑
"""


def build_chat_prompt(history: list[dict], current: str) -> str:
    """Assemble system prompt + optional history block + current question."""
    parts = [BOT_SYSTEM_PROMPT]
    if history:
        parts.append("--- 對話歷史 ---")
        for h in history:
            parts.append(f"{h['role']}: {h['text']}")
    parts.append("--- 目前提問 ---")
    parts.append(f"user: {current}")
    return "\n".join(parts)

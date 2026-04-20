# CLAUDE.md — paper_radar agent

這個檔案是 `agents/paper_radar/` 這隻 agent 的 sub-CLAUDE.md，提供 Claude Code 修改這個目錄時的 context。根目錄 `/app/CLAUDE.md` 是 repo-level 規範。

## 這隻 agent 在幹嘛

每天早上自動跑：HF daily papers → Claude Sonnet 三句繁中摘要 → Notion page → Telegram 通知。Spec 見 `/app/docs/plans/paper.md`（feature-level）跟 `/app/docs/superpowers/specs/2026-04-20-paper-radar-design.md`（repo 整合）。

## 結構

- `radar.py` — orchestrator + 5 pure functions (`fetch_papers` / `dedup` / `summarize` / `push_to_notion` / `notify_telegram`) + `main()`
  - `summarize` 支援 claude / gemini 雙 backend，由 `SUMMARIZER` env var 切換（default `claude`）。Gemini JSON outer key 是 `response`，claude 是 `result` — `_run_claude_summarize` / `_run_gemini_summarize` 各自處理這個差異
  - `push_to_notion` 仍硬綁 claude（Notion MCP 是 Claude-only）
- `bot.py` — Telegram Q&A bot（long-polling）。獨立 process，docker-compose service `paper_radar_bot`，lifecycle 跟 cron 的 `radar.py` 分開。`handle_update` 透過 `Context` dataclass inject 依賴（`send_message` / `ask_llm` / `db_path`），測試塞 fake
- `telegram_client.py` — `radar.py` + `bot.py` 共用的 HTTP wrapper (`send_message` / `send_chat_action` / `get_updates`)
- `chat_db.py` — bot 專用 SQLite wrapper，獨立檔 `bot.sqlite`（不跟 `db.sqlite` 混）。Tables: `chat_history` + `bot_state`（存 update offset）
- `prompts.py` — `SUMMARIZE_PROMPT` + `NOTION_PUSH_PROMPT` + `BOT_SYSTEM_PROMPT` + `build_chat_prompt`
- `db.py` — SQLite 包一層：`init_db` / `get_seen_ids` / `mark_seen`（只給 radar.py 用）
- `verify/` — 每個 wet step 的 smoke script，手動跑，**不上 CI**
- Tests: `/app/tests/agents/paper_radar/`

## 修改時要注意

- **不要** 在 library code 用 `print`（CLAUDE.md 全域規則），用 `logger`
- **不要** 引入 `notion-client` SDK — 此 agent 走 Claude Code Notion MCP connector
- **不要** 引入 Anthropic Python SDK — 走 `claude -p` subprocess
- `prompts.py` 裡 `SUMMARIZE_PROMPT` 跟 `NOTION_PUSH_PROMPT` 的 JSON 範例用 `{{ }}` 跳脫，改 prompt 時要保留
- `summarize` / `push_to_notion` 都是雙層 JSON parse（outer `.result` 是字串，裡面又是 JSON），且要處理 claude 會把 JSON 包在 ```json fence 的情況 — 改 parse 邏輯時所有層級都要顧到
- Notion MCP tool namespace 是 `mcp__claude_ai_Notion__*`（不是 `mcp__notion__*`），這是此 container 環境特有的
- `--bare` flag 在此環境會觸發 "Not logged in"，不要加回去
- SQLite connection 每次 function call 開關，不要做 pool
- `mark_seen` 只在 Notion + Telegram **都** 成功（且沒 early-exit）後呼叫，失敗時不寫 DB（safe re-run）
- 所有檔案路徑（`.env`、`db.sqlite`、`summaries.json`、`radar.log`、`bot.sqlite`、`bot.log`）都從 `_MODULE_DIR = Path(__file__).parent` 錨定絕對路徑 — cwd 在哪都一樣找得到，別改回相對路徑
- `bot.py` 的 `run_loop` 不管 handler 出什麼錯都會推進 offset — poison message 不會卡住 queue；要加 retry 行為記得別改這個不變量
- Bot whitelist：`TELEGRAM_AUTHORIZED_CHAT_IDS` CSV，未設 fallback 到 `TELEGRAM_CHAT_ID`；空集合時 `bot.main()` 直接 return 1（拒絕啟動，避免被陌生人 DM）
- Bot LLM 呼叫**沒有** `--allowedTools` 跟 `--max-turns > 1` — 純文字 single-shot Q&A，不給 MCP access
- 新 env：`TELEGRAM_AUTHORIZED_CHAT_IDS` / `BOT_BACKEND` / `BOT_HISTORY_TURNS` / `BOT_LLM_TIMEOUT`

## 改完之後

1. `pytest tests/agents/paper_radar/ -v` 要全 green
2. 改到 wet function (`summarize` / `push_to_notion` / `notify_telegram` / `fetch_papers`) 要跑對應 `verify/verify_*.py` 實測一次
3. commit message 依 repo 規範 (`feat:` / `fix:` / `refactor:` / `docs:` / `test:`)

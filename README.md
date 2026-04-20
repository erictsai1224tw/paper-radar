# AI Paper Radar

每天早上自動抓 HuggingFace Daily Papers Top 8，用 Claude Sonnet 寫**三句話台灣口語繁中摘要**，整理成 Notion page，然後 Telegram 推到手機。目標使用者：需要每天花 5 分鐘掃 AI 圈動態的研究生 / 從業者。

> 本 agent 是 [`sdk_test`](../../) monorepo 裡 `agents/` 底下的第一個自動化服務。

## Flow

```
[cron 08:00]
     │
     ▼
  radar.py
     │
     ├─▶ fetch_papers()      HuggingFace daily_papers JSON API
     ├─▶ dedup()             SQLite 過濾已推過的 arxiv_id
     ├─▶ summarize()         claude -p 每篇 3 句繁中
     ├─▶ push_to_notion()    claude -p + Notion MCP connector，回傳 URL
     ├─▶ notify_telegram()   Telegram Bot API，附 Notion 連結
     └─▶ mark_seen()         成功後才寫 SQLite
```

**設計原則：** 單檔 orchestrator、最少抽象。錯誤 log 後 fail loud。`mark_seen` 只在 Notion + Telegram 都成功後呼叫，所以重跑安全。

## 檔案結構

```
agents/paper_radar/
├── radar.py           # orchestrator + 5 個 pipeline 函數 + main()
├── prompts.py         # SUMMARIZE_PROMPT, NOTION_PUSH_PROMPT
├── db.py              # SQLite dedup（init_db / get_seen_ids / mark_seen）
├── .env               # 你的 secret（不進 git）
├── .env.example       # secret 範本
├── CLAUDE.md          # 給 Claude Code 看的 context
├── verify/            # 各 step 手動 smoke script
│   ├── verify_fetch.py
│   ├── verify_summarize.py
│   ├── verify_notion.py
│   └── verify_telegram.py
├── cron/
│   └── paper_radar.crontab   # supercronic 讀的排程檔
├── db.sqlite          # runtime（gitignored）
├── summaries.json     # runtime（gitignored）
└── radar.log          # runtime（gitignored）
```

所有 runtime artifacts 都寫在 `agents/paper_radar/` 下（從 `__file__` 錨定絕對路徑），**跑的時候 cwd 在哪都沒差**。

Tests 在 repo 根的 `tests/agents/paper_radar/`。

## Setup

### 1. 安裝

Repo 根目錄已有 `uv` venv（`coding-cli-runtime` + `requests` + `python-dotenv`）。

```bash
source /venv/bin/activate
uv sync --active
```

### 2. Notion

1. 在你 Notion workspace 建一個 parent page（名字隨意，例如「AI Radar」）
2. 把 page URL 填到 `.env` 的 `NOTION_PARENT_PAGE_URL`
3. Claude Desktop / Claude Code 設定裡的 Connectors 要 enable Notion

確認 connector 連上：
```bash
claude mcp list | grep -i notion   # 要看到 ✓ Connected
```

> **環境 quirk**：此 container 的 Notion MCP tool namespace 是 `mcp__claude_ai_Notion__*`（以 connector 註冊名稱 "claude.ai Notion" 為準），不是一般文件寫的 `mcp__notion__*`。`radar.py` 已經用對的 namespace。

### 3. Telegram（5 分鐘）

1. Telegram 找 [`@BotFather`](https://t.me/BotFather)，輸入 `/newbot`，取名字 + username，拿到 `BOT_TOKEN`
2. **⚠️ 重要**：打開你剛建的 bot，按 `Start`（或隨便傳一句訊息）— bot 沒先收到訊息就沒法回你，會報 `chat not found`
3. 瀏覽器打開 `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`，找 **`chat.id`**（不是 `update_id` — 那兩個欄位都是數字很容易看錯）
4. 把 `BOT_TOKEN` 跟 `chat.id` 填進 `.env`

### 4. 建 `.env`

```bash
cp agents/paper_radar/.env.example agents/paper_radar/.env
$EDITOR agents/paper_radar/.env   # 填三個 secret
```

三個必填：
```
NOTION_PARENT_PAGE_URL=https://www.notion.so/your-workspace/AI-Radar-xxxxxxxx
TELEGRAM_BOT_TOKEN=8123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=1234567890
```

## 執行

```bash
python -m agents.paper_radar.radar
# 或
python agents/paper_radar/radar.py
```

cwd 在哪都行。正常輸出：

```
2026-04-20 08:00:01 INFO === AI Paper Radar starting ===
2026-04-20 08:00:02 INFO fetched 30 papers
2026-04-20 08:00:02 INFO after dedup: 8 fresh papers
2026-04-20 08:02:15 INFO summarized 8 papers
2026-04-20 08:08:47 INFO notion page: https://www.notion.so/...
2026-04-20 08:08:48 INFO === done ===
```

執行時間：大約 10 分鐘（8 篇 summarize + Notion multi-turn）。

手機 Telegram 會收到一則訊息，內容是每篇 paper 的標題 + 三句繁中摘要 + tags + upvotes，尾巴附 Notion 完整整理連結：

```
📚 AI Radar 2026-04-20 (8 篇)

1. Attention Is All You Need
這篇發明了 Transformer，完全靠注意力機制……
🏷️ transformer · attention  ⬆ 999

2. ...

👉 看 Notion 完整整理 → notion.so/...
```

### 自動排程（container 內跑 supercronic）

本 repo 用 [supercronic](https://github.com/aptible/supercronic)（rootless cron）在 container 裡跑排程。docker-entrypoint.sh 自動掃 `/app/agents/*/cron/*.crontab` 一起啟動。

paper_radar 的 crontab 在 [`cron/paper_radar.crontab`](cron/paper_radar.crontab)，預設：

```
0 22 * * * /venv/bin/python -m agents.paper_radar.radar
```

每天 22:00（Asia/Taipei，由 `docker-compose.yml` 的 `TZ=Asia/Taipei` 決定）。

想改時間直接改 crontab 檔，container 重啟 (`make up` 或 `docker-compose restart`) 後生效。要完全新建 image 才第一次生效：

```bash
make build         # 或 docker-compose build
make up
```

**Container 跑 log**：supercronic 的執行 log 在 container stdout（`docker-compose logs app | grep supercronic`）。Paper radar 本身的 log 在 `agents/paper_radar/radar.log`。

**Host 重啟後容器要不要自動起來**：`docker-compose.yml` 目前沒設 `restart`。要讓 host 重開機後 container 也自動 up，加：
```yaml
services:
  app:
    restart: unless-stopped
```

## 驗證 / 除錯

四個 step 有獨立 smoke script（真打 API，不上 CI）：

```bash
python agents/paper_radar/verify/verify_fetch.py       # HF API（免費）
python agents/paper_radar/verify/verify_summarize.py   # claude -p（小量 quota）
python agents/paper_radar/verify/verify_notion.py      # Notion MCP（會建 page）
python agents/paper_radar/verify/verify_telegram.py    # 推一則 dummy 到手機
```

單元測試（全 mock，離線，超快）：
```bash
pytest tests/agents/paper_radar/ -v
```

看 log：
```bash
tail -50 agents/paper_radar/radar.log
```

### 手動重置 dedup

想重跑今天某幾篇 / 全部：
```bash
# 刪今天的紀錄
sqlite3 agents/paper_radar/db.sqlite "DELETE FROM seen WHERE pushed_at LIKE '2026-04-20%'"

# 整張表清掉
sqlite3 agents/paper_radar/db.sqlite "DELETE FROM seen"
```

## 已知限制 / 環境 quirk

- **Notion MCP cron 兼容性** — 在 `claude -p` subprocess 底下實測 OK，但 cron 啟動的 process 繼承 session 行為沒驗過。若 cron 跑不動，改走 `notion-client` SDK（加 `NOTION_TOKEN` env var）當 fallback。
- **`claude -p --bare` 壞 auth** — 在此環境加這個 flag 會回 "Not logged in"，所以 `radar.py` 不加。升 CLI 版本時重驗。
- **Claude JSON response 會被 markdown fence 包** — 就算 prompt 明寫「只回 JSON」還是會出現 ` ```json...``` `。parser 有 fence-stripping 處理，改 parse 邏輯時要保留。
- **Telegram message 4096 字元上限** — 目前遠低於，之後加欄位注意。
- **Retry 是手刻 for loop**，不是 exponential backoff。v0 夠用。

## 不在 v0 範圍

- 個人化過濾（按研究領域 keyword 加權）
- Notion related-work DB 比對
- 多源整合（ArXiv RSS / Papers with Code）
- Email / LINE 備份通知
- 每週 digest
- 使用者反饋學習（thumbs up/down）

Spec 見 [`docs/plans/paper.md`](../../docs/plans/paper.md) §12 未來擴充清單。

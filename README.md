# AI Paper Radar

每天早上自動抓 HuggingFace Daily Papers，整理成 Notion database，推到 Telegram。附一隻 Q&A bot 讓你直接在 Telegram 深入追問單篇 paper（會自動吃 PDF 全文當 context）。單人用、個人化、可擴充。

> 本 agent 是 [`sdk_test`](../../) monorepo 裡 `agents/` 底下的第一個自動化服務。

## 在做什麼

- 🌅 **每日推播** — HF daily top 30 → 可選 `INTEREST_PROMPT` LLM rerank → top 8 → 結構化摘要（tldr / strengths / limitations / open questions / future work）→ Notion DB 17 欄 → Telegram 附圖片 + 按鈕
- 🤖 **Q&A bot** — 直接跟 Claude 或 Gemini 對話，問 `介紹 2604.16044` 或 `第 7 篇用什麼 dataset?`，自動把該篇 PDF 轉 markdown 塞進 prompt；沒快取的即時下載轉換
- 🔎 **主動搜尋** — `/search efficient diffusion`、`/similar <id>`、`/refs <id>`、`/watch <name> <query>` 持續訂閱，結果進對話 history 供後續追問
- 📓 **NotebookLM 轉接** — `/notebook <id>` 給你一包 URL + markdown 檔，直接餵 NotebookLM
- 🔊 **語音概覽** — optional 每日 podcast-style 繁中播報（edge-tts 免費）
- 👍 **學習你的偏好** — 每篇下面 👍/👎/🔖 按鈕，累積 20 筆後自動 rerank 明天的 paper
- 📚 **每週 digest** — 週日早上按主題 cluster 一週內推過的 paper
- ⭐ **Author watchlist** — `AUTHOR_WATCHLIST` 命中的 paper 標 ⭐

## 架構

```
┌─────────────────────────────────────────────────────────────────┐
│  cron                                                            │
├─────────────────────────────────────────────────────────────────┤
│ 22:00 daily  → radar.py          (HF → Notion → Telegram push)   │
│ 08:00 daily  → watch_runner.py   (跑所有 /watch 訂閱)            │
│ 09:00 sunday → weekly_rollup.py  (過去 7 天 theme clustering)    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  docker-compose services                                         │
├─────────────────────────────────────────────────────────────────┤
│ paper_radar_bot          bot.py         Q&A long-polling         │
│ paper_radar_notify_bot   notify_bot.py  👍👎🔖 callback collector │
└─────────────────────────────────────────────────────────────────┘

radar.py pipeline
  fetch_papers ─▶ dedup ─▶ rank_by_interest? ─▶ summarize
       │                                           │
       ▼                                           ▼
   papers_md/ ◀── paper_markdown           paper_s2 (venue/cites)
   papers_fig/◀── paper_figure
       │
       ▼
   push_to_notion (17 欄 database)
       │
       ▼
   notify_telegram (圖 + 按鈕 + 可選語音)
       │
       ▼
   mark_seen ─▶ archive to papers_archive.jsonl
```

## 檔案結構

```
agents/paper_radar/
├── radar.py                  # daily orchestrator + 5 pipeline functions
├── bot.py                    # Telegram Q&A long-poll process
├── notify_bot.py             # feedback-button callback collector
├── watch_runner.py           # /watch cron entry
├── weekly_rollup.py          # Sunday theme digest
│
├── prompts.py                # 所有 LLM prompt 模板
├── telegram_client.py        # sendMessage / sendPhoto / sendAudio / sendDocument
│
├── paper_markdown.py         # PDF → markdown（markitdown + 下載 + 清理 C0）
├── paper_figure.py           # 擷取 Figure 1 區域（PyMuPDF crop）
├── paper_s2.py               # Semantic Scholar: 元資料 / 推薦 / citation graph
├── paper_voice.py            # edge-tts MP3 合成
├── paper_arxiv_search.py     # arxiv Atom API 搜尋
├── rerank.py                 # tag-preference re-ranker
│
├── db.py                     # radar dedup: db.sqlite
├── chat_db.py                # Q&A bot: bot.sqlite (history + update offset)
├── feedback_db.py            # 👍👎🔖 records: feedback.sqlite
├── watch_db.py               # /watch persistence: watch.sqlite
│
├── verify/                   # 手動 smoke scripts（wet, 不上 CI）
├── cron/paper_radar.crontab  # 3 排程：daily radar + daily watches + weekly rollup
├── .env / .env.example
├── docker-compose.yml        # app + paper_radar_bot + paper_radar_notify_bot
│
├── papers_md/                # 每篇 paper 的 markdown（gitignored）
├── papers_fig/                # 每篇 Figure 1 PNG（gitignored）
├── papers_voice/              # 每日 MP3（gitignored）
├── papers_archive.jsonl       # weekly rollup + rerank 用（gitignored）
└── *.sqlite                   # 所有 DB runtime（gitignored）
```

所有 runtime artifacts 都寫在 `agents/paper_radar/` 下（從 `__file__` 錨定絕對路徑）— cwd 在哪都沒差。

Tests 在 repo 根的 `tests/agents/paper_radar/`，262+ 全 mocked 離線。

## Setup

### 1. Notion

1. Workspace 建一個 parent page（例如「AI Radar」）— bot 會在裡面建一個叫 "AI Paper Radar" 的 database
2. Page URL 填到 `.env` 的 `NOTION_PARENT_PAGE_URL`
3. Claude Desktop / Claude Code 設定裡的 Connectors 要 enable Notion

確認 connector：
```bash
claude mcp list | grep -i notion   # 要看到 ✓ Connected
```

> **環境 quirk**：此 container 的 Notion MCP tool namespace 是 `mcp__claude_ai_Notion__*`（以 connector 註冊名稱 "claude.ai Notion" 為準）。

### 2. 兩個 Telegram bot

一個負責推播、一個負責互動 Q&A。都在 [@BotFather](https://t.me/BotFather) `/newbot` 建立，各拿 token。

| 用途 | Token env | Chat env |
|---|---|---|
| Paper 推播（單向） | `TELEGRAM_NOTIFY_BOT_TOKEN` | `TELEGRAM_NOTIFY_CHAT_ID` |
| Q&A 互動 | `TELEGRAM_QA_BOT_TOKEN` | `TELEGRAM_AUTHORIZED_CHAT_IDS`（CSV） |

建完每個 bot 都要點 `Start`（或先傳一句訊息給它），不然 `getUpdates` 沒資料 → 抓不到 `chat_id`。

```
https://api.telegram.org/bot<TOKEN>/getUpdates
```
找 `message.chat.id`（數字），填到 `.env`。

### 3. `.env`

```bash
cp agents/paper_radar/.env.example agents/paper_radar/.env
$EDITOR agents/paper_radar/.env
```

最少要填：
```env
NOTION_PARENT_PAGE_URL=https://www.notion.so/your-workspace/AI-Radar-xxx
TELEGRAM_NOTIFY_BOT_TOKEN=...
TELEGRAM_NOTIFY_CHAT_ID=...
TELEGRAM_QA_BOT_TOKEN=...
TELEGRAM_AUTHORIZED_CHAT_IDS=<你的 chat_id>
```

可選個人化：
```env
SUMMARIZER=claude                  # or gemini
BOT_BACKEND=claude                 # Q&A bot 預設 backend
AUTHOR_WATCHLIST=Karpathy, DeepMind, Yann LeCun  # 命中就 ⭐
VOICE_OVERVIEW=true                # 每日附 3 分鐘 podcast
FEEDBACK_RERANK_MIN_SAMPLES=20     # 累積幾則 👍👎 才開始 rerank
INTEREST_PROMPT="I work on efficient diffusion and RL alignment. Not interested in tabular data."
```

### 4. 依賴

```bash
source /venv/bin/activate
uv sync --active
```

會裝 `markitdown[pdf]`、`pymupdf`、`edge-tts` 等。

## 執行

### 每日推播（手動跑）

```bash
python -m agents.paper_radar.radar
```

完整 log：
```
INFO === AI Paper Radar starting ===
INFO fetched 30 papers
INFO after dedup: 12 fresh candidates
INFO ranking by interest (236 chars of prompt)   [若有設 INTEREST_PROMPT]
INFO selected 8 papers for today
INFO summarized 8 papers
INFO s2[2604.16044] venue='NeurIPS 2024' cites=42/7
INFO caching paper markdowns to ...
INFO extracting Figure 1 images to ...
INFO figure[2604.16044]: 2604.16044.png  explain='訓練時 SNR 跟 timestep 強制綁定...'
INFO notion page: https://www.notion.so/...
INFO voice overview sent: 2026-04-20.mp3 (664 chars)   [若 VOICE_OVERVIEW=true]
INFO archived 8 papers to papers_archive.jsonl
INFO === done ===
```

實際耗時 10~15 分鐘（summarize × 8 + Notion multi-turn）。

### 自動排程

Container 內 `supercronic` 讀 `cron/paper_radar.crontab`：

```
0 22 * * *  /venv/bin/python -m agents.paper_radar.radar           # daily push
0 8 * * *   /venv/bin/python -m agents.paper_radar.watch_runner    # /watch 訂閱
0 9 * * 0   /venv/bin/python -m agents.paper_radar.weekly_rollup   # Sunday digest
```

時區由 `docker-compose.yml` 的 `TZ=Asia/Taipei` 決定。改完 crontab `docker-compose restart app`。

### 兩隻 bot（一直跑）

`docker-compose.yml` 自動帶起：
- `paper_radar_bot` — `python bot.py`（Q&A 長連線）
- `paper_radar_notify_bot` — `python notify_bot.py`（收 👍👎🔖 callback）

手動跑：
```bash
python bot.py         # 或 python verify/verify_bot.py
python notify_bot.py
```

## Q&A Bot 指令

打 `/help` 看完整列表。常用：

| 指令 | 用途 |
|---|---|
| 直接傳文字 | 用預設 backend 回答，帶對話歷史 |
| `/claude <q>` / `/gemini <q>` | 這則強制指定 backend |
| `介紹 2604.16044` / `介紹第一篇` | 自動載入該篇 PDF 全文當 context |
| `/search efficient diffusion` | arxiv 搜尋某領域最新 5 篇 |
| `/similar 2604.16044` | S2 語意相似推薦 5 篇 |
| `/refs 2604.16044` | S2 citation graph（引用 + 被引用） |
| `/watch rl-dialogue reinforcement learning AND dialogue` | 新增訂閱 |
| `/watches` / `/unwatch rl-dialogue` / `/watch_run rl-dialogue` | 管理 |
| `/notebook 2604.16044` | 拿 NotebookLM 用的 URL + markdown 檔 |
| `/backend` / `/reset` | 看 backend / 清歷史 |

Bot 會自動偵測下列 paper reference 並載入 markdown：
- `第 N 篇`（阿拉伯 / 中文數字，對應今日 batch）
- `2604.16044`（任何 arxiv id；沒快取的即時下載）
- 完整標題子字串（≥12 字元）

找不到 cache → 現場 `markitdown` 轉換 → 存 cache → 塞進 prompt。

## 驗證 / 除錯

### Smoke scripts（真打 API）

```bash
python agents/paper_radar/verify/verify_fetch.py
python agents/paper_radar/verify/verify_summarize.py
python agents/paper_radar/verify/verify_notion.py
python agents/paper_radar/verify/verify_telegram.py
python agents/paper_radar/verify/verify_bot.py       # 起 Q&A bot，用 Ctrl-C 收
```

### 單元測試（全 mock，離線）

```bash
pytest tests/agents/paper_radar/ -v
```

### Logs

```bash
tail -50 agents/paper_radar/radar.log       # daily pipeline
tail -50 agents/paper_radar/bot.log         # Q&A bot
tail -50 agents/paper_radar/notify_bot.log  # feedback collector
```

### 手動重置 dedup

想重推今天：
```bash
sqlite3 agents/paper_radar/db.sqlite "DELETE FROM seen WHERE pushed_at LIKE '2026-04-20%'"
```

或整張清掉：
```bash
sqlite3 agents/paper_radar/db.sqlite "DELETE FROM seen"
```

注意：會在 Notion DB 造成重複 row（要不要手動刪掉看你）。

### 看累積的 feedback

```bash
sqlite3 agents/paper_radar/feedback.sqlite "SELECT action, COUNT(*) FROM feedback GROUP BY action"
```

## 已知限制 / 環境 quirk

- **Telegram 沒有原生 LaTeX render**。Bot 的回答 prompt 被要求用 Unicode 符號（α β x̂_t）代替 `$...$`；markdown→HTML converter 會把 `$` 脫掉保留內容。要真 math 渲染得另加 codecogs 或 matplotlib 服務
- **markitdown 偶爾會吐 C0 控制字元**（null byte 會讓 subprocess argv 爆炸）。載入時有 sanitizer 會洗掉
- **Semantic Scholar 免費層 rate limit**（100 req / 5min / IP）— radar.py 同時打 8 次會被 429 擋掉一半。容忍失敗，cite 數可能偶爾空
- **arxiv API 3 秒 / request**。`/search` 有一次 retry-on-429，連續 `/search` 太快會整片失敗
- **OpenReview peer review 分數**沒做：API 現在要 auth
- **Claude JSON response 可能被 ```fence 包住**。所有 parser 都有 fence-stripping
- **Notion MCP cron 兼容性**：supercronic 底下跑 `claude -p` 的 session 行為沒徹底驗過。若真有問題，fallback 到 `notion-client` SDK

## Follow-up 候選

Research agent 還建議幾個沒做：
- arxiv v2/v3 revision diff（論文改版後重推「what changed」）
- HN + Reddit 熱度加權（社群 buzz score）
- OpenReview 分數（要 auth）
- Per-tag SVM 取代簡單 tag-preference rerank
- LaTeX 公式 → PNG rasterization

## 參考

- Feature 演進記錄看 git log（17 個 PR，從 v0 的 3 函數到現在 14 個 bot 指令 + 4 個 cron job）
- Sub-CLAUDE.md ([`CLAUDE.md`](CLAUDE.md)) 有修改時要注意的 invariants

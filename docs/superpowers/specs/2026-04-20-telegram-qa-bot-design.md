# Telegram Q&A Bot — Design

**Date:** 2026-04-20
**Agent:** paper_radar
**Status:** approved for planning

## Goal

Add a Telegram bot that lets the user chat with Claude Code (`claude -p`) or Gemini CLI (`gemini -p`) through Telegram — reusing the bot token already configured for paper_radar notifications. Bidirectional text Q&A, single user, long-polling.

## Non-Goals

- Multi-user / per-user quotas
- Streaming replies (Telegram lacks a good partial-edit UX)
- File / image / audio input
- Web search or arbitrary tool use inside the bot (single-shot text only)
- Rate limiting (single authorized user)

## Architecture

New process, separate lifecycle from `radar.py` (which is cron-driven). Deployed as a second docker-compose service `paper_radar_bot` with `restart: unless-stopped`.

```
bot.py (new)
├─ main()                         # long-poll loop
├─ poll_once(offset) -> updates   # wraps getUpdates
├─ handle_update(upd)             # dispatch: command vs free-form
├─ ask_llm(text, history, backend) -> str
└─ reply(chat_id, text)           # splits >4096 chars

telegram_client.py (new, shared with radar.py)
├─ send_message(token, chat_id, text, parse_mode=None, disable_preview=True)
├─ send_chat_action(token, chat_id, action)
└─ get_updates(token, offset, long_poll_timeout=30)

chat_db.py (new — kept separate from db.py to avoid mixing concerns)
├─ init_chat_db(path)
├─ append_turn(chat_id, role, text)      # role in {"user","assistant"}
├─ get_history(chat_id, limit) -> list[dict]
├─ clear_history(chat_id)
├─ get_offset() -> int                   # Telegram update_id cursor
└─ set_offset(offset)

prompts.py
└─ + BOT_SYSTEM_PROMPT

radar.py
└─ refactor: _send_telegram_message -> import from telegram_client
```

## Components

### `telegram_client.py`

Thin wrapper around the Telegram Bot API. Pure functions, no global state. Raises `requests.HTTPError` on non-2xx. Both `radar.py` and `bot.py` use it so HTTP plumbing lives in one place.

### `chat_db.py`

SQLite schema (separate file `bot.sqlite`, not shared with `db.sqlite`):

```sql
CREATE TABLE IF NOT EXISTS chat_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    TEXT NOT NULL,
    role       TEXT NOT NULL,              -- "user" | "assistant"
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_history_chat ON chat_history(chat_id, id);

CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
-- keys: "update_offset"
```

- `get_history(chat_id, limit)` returns most recent `limit` turns oldest-first for prompt assembly.
- `append_turn` does not enforce a cap in SQL; trimming happens at read-time via `LIMIT`.
- Follow `db.py`'s pattern: open + close connection per call, no pool.

### `bot.py`

Long-poll loop:

```python
def main() -> int:
    load_dotenv(ENV_PATH)
    configure_logging()
    init_chat_db(BOT_DB_PATH)
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    whitelist = load_whitelist()   # CSV from TELEGRAM_AUTHORIZED_CHAT_IDS, fallback to [TELEGRAM_CHAT_ID]
    offset = get_offset()
    while True:
        try:
            updates = get_updates(token, offset, long_poll_timeout=30)
        except requests.RequestException as exc:
            logger.warning("getUpdates failed: %s — sleeping 5s", exc)
            time.sleep(5)
            continue
        for upd in updates:
            try:
                handle_update(upd, token, whitelist)
            except Exception:
                logger.exception("handle_update crashed — skipping update %s", upd.get("update_id"))
            offset = upd["update_id"] + 1
            set_offset(offset)
```

Key invariants:
- `set_offset` runs *after* `handle_update`, even on handler exception. Poison messages must not block the queue.
- Unhandled exceptions in `handle_update` are caught and logged; the loop keeps running.
- Process-level crashes are handled by docker restart policy.

### Command dispatch

| Input | Behavior |
|---|---|
| `/start`, `/help` | Reply with command list |
| `/reset` | `clear_history(chat_id)`, reply "歷史已清空" |
| `/backend` | Reply with current `BOT_BACKEND` |
| `/claude <q>` | Force claude for this message only; skip saving `/claude ` prefix to history |
| `/gemini <q>` | Force gemini for this message only |
| plain text | Use `BOT_BACKEND` default, with history context |
| any command with empty body (e.g. bare `/claude`) | Reply "需要問題內容" |

### Prompt assembly

`BOT_SYSTEM_PROMPT` (in `prompts.py`):

```
你是使用者的 coding 助手，透過 Telegram 對話。
- 預設用繁體中文回答，除非問題本身是英文
- 程式碼用 ``` fence 包起來
- Telegram 訊息上限 4096 字元，回覆盡量精簡
- 不要編造 API、函式名、或檔案路徑
```

Final prompt passed to `claude -p` / `gemini -p`:

```
{BOT_SYSTEM_PROMPT}

--- 對話歷史 ---
user: {h1.text}
assistant: {h2.text}
...

--- 目前提問 ---
user: {current_text}
```

History is the last `BOT_HISTORY_TURNS * 2` rows (user+assistant pairs) for this `chat_id`, oldest-first.

### LLM invocation

Mirror `radar.py`'s `_run_claude_summarize` / `_run_gemini_summarize` exactly, but without the inner JSON contract (bot replies are free-form text, not structured). The outer JSON envelope still needs parsing:

- claude: `json.loads(stdout)["result"]`
- gemini: `json.loads(stdout)["response"]`

Keep `--max-turns 1` — single-shot Q&A is the design. No `--allowedTools` — bot is pure text, no MCP access.

Timeout: `BOT_LLM_TIMEOUT` env, default 120s (same as `LLM_TIMEOUT`).

### Reply delivery

- If reply > 4096 chars: split preferring (in order) the last `\n\n` before index 4096, else the last `\n`, else hard-split at 4096; send each chunk via `send_message`, 1s sleep between (mirrors `_TELEGRAM_MSG_DELAY`).
- `parse_mode=None` by default — bot replies are raw text; Markdown/HTML adds escaping bugs we don't need.

## Data Flow — Plain Text Question

1. `getUpdates(offset, long_poll=30s)` returns a message
2. `chat_id` ∉ whitelist → reply "unauthorized", log WARN, advance offset
3. Text starts with `/` → command dispatch (see above)
4. Else: `send_chat_action(chat_id, "typing")`
5. `history = get_history(chat_id, limit=BOT_HISTORY_TURNS * 2)`
6. Assemble prompt (system + history + current)
7. Shell out to `claude -p` / `gemini -p` (timeout 120s)
8. On success: parse outer JSON → reply text
9. `append_turn(chat_id, "user", text)` + `append_turn(chat_id, "assistant", reply)`
10. `reply(chat_id, text)` (chunked if needed)
11. Advance offset

## Error Handling

| Failure | Behavior |
|---|---|
| LLM subprocess timeout / non-zero exit | Reply "⏱️ 回覆失敗，請再試一次"; **advance offset**, **don't** append history. Avoids poison-message infinite retry. |
| LLM JSON parse error | Same as timeout — log `logger.exception`, user-visible reply is generic. |
| `send_message` fails | Retry 2× with 1s backoff; give up, log WARN, advance offset. User won't see a reply — acceptable tradeoff. |
| `getUpdates` network error | Log WARN, sleep 5s, retry. Do not advance offset. |
| Unauthorized chat_id | Reply "unauthorized", log WARN with chat_id, advance offset. Do not invoke LLM. |
| bot.py crash (unexpected) | Docker restart policy; offset recovered from `bot_state`. |

## Configuration

Additions to `.env.example`:

```
# === Telegram Q&A Bot ===
# 授權可用 bot 的 chat_id，CSV。未設時 fallback 到 TELEGRAM_CHAT_ID。
TELEGRAM_AUTHORIZED_CHAT_IDS=

# Bot default backend: claude (default) | gemini
BOT_BACKEND=claude

# 每輪帶入的對話對數（user+assistant = 1 輪）
BOT_HISTORY_TURNS=10

# LLM 呼叫 timeout (秒)
BOT_LLM_TIMEOUT=120
```

## Testing

### Unit tests — `tests/agents/paper_radar/test_bot.py`

Mock `subprocess.run` and `requests.post`/`requests.get`. Cover:

- `handle_update` dispatch: `/start`, `/help`, `/reset`, `/backend`, `/claude <q>`, `/gemini <q>`, plain text, unauthorized chat_id, bare command without body
- `ask_llm` backend selection (claude default, `/claude` override, `/gemini` override, unknown backend fallback)
- `reply` chunking: exactly 4096 chars, 4097 chars, 10000 chars, paragraph-boundary preference
- `chat_db`: append/get with `LIMIT`, `clear_history` per chat_id, offset round-trip
- Poison message: LLM subprocess raises `TimeoutExpired` → offset still advances, history not written
- `telegram_client.send_message` raises → bot continues to next update

### Smoke test — `verify/verify_bot.py`

Manual run. Starts `bot.py` in foreground for 60s, user sends `/help` + plain text + `/reset` from their Telegram client, verifies replies arrive. Not in CI (requires live Telegram).

### Refactor regression

Existing `tests/agents/paper_radar/test_notify.py` must keep passing after `_send_telegram_message` → `telegram_client.send_message` extraction.

## Deployment

New service in `docker-compose.yml`:

```yaml
paper_radar_bot:
  build: .
  command: python bot.py
  env_file: .env
  volumes:
    - ./:/app
  restart: unless-stopped
```

`paper_radar.crontab` unchanged — cron service still runs `radar.py` on schedule; bot runs continuously.

## Security

- Whitelist is hard-enforced before any LLM invocation. Unauthorized `chat_id` never triggers a subprocess.
- Bot token lives in `.env`, same as today. No new secret surface.
- No shell interpolation of user text — `claude -p` / `gemini -p` receive user text as a single argv element (like `radar.py` already does for summaries). Telegram messages cannot inject flags.
- User text *can* influence the LLM's output (obvious, by design) but cannot escape the argv boundary to execute shell commands.

## Open Questions

None at design time. User approved:
- `/claude` + `/gemini` per-message override: **yes**
- Default `BOT_HISTORY_TURNS=10`: **ok**

## Out of Scope / Follow-ups

- Streaming output (not supported cleanly by Telegram; skip)
- File / image input
- Multi-user auth with separate history namespaces (already namespaced by `chat_id`, just not allowed by whitelist)
- Observability beyond logs (metrics, tracing)

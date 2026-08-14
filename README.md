# Market Report Bot

Automated Telegram reports for **Gold Futures (GC=F)**, **Dow Jones (^DJI)**
and **Bitcoin (BTC-USD)** — daily session snapshots and weekly analytical
reports, with AI-generated summaries (Gemini) and dark-theme charts.

## How it works

Each `(asset, mode)` pair — e.g. `gold/daily`, `bitcoin/weekly` — is its
own GitHub Actions workflow with its own cron schedule. When a workflow
fires, it runs:

```bash
python -m bot.main --asset gold --mode daily
```

`main.py` never trusts the cron trigger blindly. It re-derives the *true*
target time using `zoneinfo` (which resolves America/New_York's EDT/EST
automatically). GitHub Actions cron is best-effort and can be delayed, so
each workflow runs repeatedly in a retry window. Python accepts a delayed
trigger for the target date (up to the configured catch-up window) and the
state store guarantees that a successful report is sent only once.

### Rules enforced by the code (not just the schedule)

- **News is editorial content, never an execution gate**: Gold and Dow
  **daily** reports look up today's high-impact USD news, and if any
  exists, the report includes a dedicated news section plus an
  AI-analyzed take on it. If there's no high-impact USD news that day —
  or the news source is temporarily unreachable — the report is still
  sent in full, simply without that section. **All three assets send a
  report every single due day, without exception.**
- **Bitcoin never calls the news filter at all** — not just "ignores
  it"; its code path never imports or invokes `news_filter`, so its
  reports structurally can never reference USD news.
- **Weekly reports** (for any asset) always include the week's
  high-impact USD news as informational content, independent of daily
  reports.
- **NYSE trading-day check**: Gold/Dow daily reports also skip on NYSE
  holidays (not just weekends), via `market_calendar.py`
  (`pandas_market_calendars`, with a safe weekday-only fallback if that
  package is unavailable).
- **Idempotency guard**: `state_store.py` records each completed job so
  a re-triggered/overlapping run won't re-send the same report.

## Schedule reference (as implemented)

| Job | Target (local) | Content behavior |
|---|---|---|
| Gold daily | 30 min before NYSE open (09:00 America/New_York) | Sent every NYSE trading day; includes a news section only if high-impact USD news exists that day |
| Dow daily | 15 min before NYSE open (09:15 America/New_York) | Sent every NYSE trading day; includes a news section only if high-impact USD news exists that day |
| Bitcoin daily | 21:00 Asia/Tehran | Sent every day; never includes a news section |
| Gold weekly | Saturday 17:00 Asia/Tehran | Always includes the week's high-impact USD news |
| Dow weekly | Saturday 18:00 Asia/Tehran | Always includes the week's high-impact USD news |
| Bitcoin weekly | Saturday 19:00 Asia/Tehran | Always includes the week's high-impact USD news |

> GitHub Actions cron expressions are UTC-based and therefore cannot
> represent New York DST directly. The workflows use 15-minute retry
> windows instead of relying on one exact cron minute. `is_due()` computes
> the actual target in `America/New_York` or `Asia/Tehran`, and the state
> store prevents duplicate sends.

All business-time calculations use `zoneinfo`; workflow YAML only defines
UTC retry windows for GitHub Actions.

## Weekly report contents

Per the spec, each weekly report includes: weekly OHLC, weekly range,
volatility (stddev of 1-minute log returns), average daily range,
strongest/weakest day (by close-open change), highest-volume day, most
active hour (UTC), a trend summary, and the week's important high-impact
USD news events — plus an AI-generated narrative summary and a dark
chart of the week's price action.

## Project layout

```
market-report-bot/
├── .github/workflows/          # 6 independent cron-triggered workflows
├── src/bot/
│   ├── main.py                 # CLI entrypoint (--asset --mode)
│   ├── config.py                # env-var settings (pydantic-settings)
│   ├── time_manager.py          # zoneinfo-based DST-safe time logic
│   ├── market_calendar.py       # NYSE trading-day detection
│   ├── state_store.py           # idempotency guard
│   ├── news_filter.py           # ForexFactory USD/High-impact filter
│   ├── market_data.py           # yfinance wrapper (interval=1m)
│   ├── statistical_analyzer.py  # pure daily/weekly analytics
│   ├── gemini_analyst.py        # google-genai summaries + model fallback
│   ├── chart_generator.py       # dark matplotlib charts
│   ├── message_formatter.py     # Telegram MarkdownV2 captions
│   ├── telegram_sender.py       # async python-telegram-bot delivery
│   ├── jobs.py                  # pipeline orchestration + schedule gate
│   ├── logger.py / retry.py / exceptions.py
├── data/state.json              # idempotency store (ephemeral in CI, see below)
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in real values.
3. In your GitHub repo, add these **Secrets**: `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`. Optionally add a repo/org
   **Variable** `GEMINI_MODEL` (e.g. `gemini-3.1-pro-preview`) — if
   unset, the built-in fallback chain in `config.py` is used.
4. Push. The six workflows in `.github/workflows/` run on their own
   schedules; each can also be triggered manually
   (`workflow_dispatch`, optional `force` input).

### GEMINI_MODEL resolution order

1. `GEMINI_MODEL` env var, if set.
2. `gemini-3.1-pro-preview`
3. `gemini-2.5-pro`
4. `gemini-2.5-flash`

`gemini_analyst.py` tries each in order and only fails the job if every
model in the chain fails.

### Persisting state across runs (optional enhancement)

`data/state.json` resets on every GitHub Actions run because runners
are ephemeral. This is a low-risk trade-off (each job fires at most
once, or twice for the EST/EDT pair — of which only one passes the
tolerance window — per day), but if you want cross-run persistence,
add an `actions/cache` step keyed on the file, or commit the file back
with `git commit` + `contents: write` permission at the end of each
workflow.

## Local run

```bash
export PYTHONPATH=src
python -m bot.main --asset gold --mode daily
python -m bot.main --asset bitcoin --mode weekly --force  # bypass time gate
```

## Testing

```bash
pip install pytest
pytest tests/
```

# Schedule bot

A Telegram bot that reads your Google Calendar and:

- sends a **daily brief** every morning (today's events + to-dos due today or overdue)
- sends a **week-ahead brief** on Monday morning, just before the daily one
- lets you **change your calendar in plain English** ("move lunch with Yan Han to 1pm", "add Parliament sitting Tue 1:30–7pm", "cancel tomorrow's 10am")
- keeps a **to-do list** (`/todo`, `/done 3`, `/drop 3`, or "remind me to file expenses by Friday")

It uses the same setup as your other bots: Python, Telegram, Railway and SQLite.

## Commands

| | |
|---|---|
| `/today`, `/tomorrow` | That day's plans |
| `/week` | Next 7 days |
| `/todo` | Show open to-dos |
| `/todo buy stamps` | Add a to-do (no date) |
| `/done 3`, `/drop 3` | Tick off or remove #3 |
| `/whoami` | Show your chat id (for setup) |
| any other text | Claude interprets it and edits your calendar or to-dos |

Deletions always ask you to confirm with a **Delete / Keep** button first. Creates and edits happen straight away, and the bot tells you exactly what it changed.

## Setup (about 20 minutes)

### 1. Telegram bot
Message **@BotFather**, send `/newbot`, and copy the token.

### 2. Google service account
The bot signs in to Google as a "robot" account that you share your calendar with, so there's no OAuth login flow to keep alive on a server.

1. Go to <https://console.cloud.google.com/> and create a project (e.g. `schedule-bot`).
2. **APIs & Services → Library**, find **Google Calendar API**, and click **Enable**.
3. **APIs & Services → Credentials → Create credentials → Service account**. Give it a name and skip the optional steps.
4. Open the service account, go to **Keys → Add key → Create new key → JSON**, and download the file.
5. Copy the service account's email (it looks like `schedule-bot@your-project.iam.gserviceaccount.com`).
6. In **Google Calendar** on the web, go to Settings, pick your calendar under **Settings for my calendars**, then **Share with specific people → Add**. Paste that email and choose **Make changes to events**.

For any other calendar you want in the briefs (e.g. a shared work calendar), share it with the same email as well. Read-only access is fine. You'll find its ID under **Integrate calendar → Calendar ID**.

### 3. Anthropic API key
Use the same key as your Sejarah bot, or make a new one at console.anthropic.com. This key is only used for free-text messages; the briefs and slash commands work without it.

### 4. Deploy on Railway
1. Push this folder to a GitHub repo and create a Railway service from it.
2. **Add a volume** mounted at `/app/data`. The to-do list lives there; without a volume it gets wiped on every redeploy.
3. Set these variables:

| Variable | Value |
|---|---|
| `TELEGRAM_TOKEN` | from BotFather |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | the **entire contents** of the downloaded JSON key file |
| `GOOGLE_CALENDAR_ID` | your Gmail address (your main calendar's ID) |
| `ANTHROPIC_API_KEY` | your key |
| `DB_PATH` | `/app/data/bot.db` |
| `GOOGLE_EXTRA_CALENDAR_IDS` | *(optional)* comma-separated IDs of other calendars to read |
| `DAILY_TIME` | *(optional)* default `07:30` |
| `WEEKLY_DAY` | *(optional)* `0` = Monday (default) … `6` = Sunday |
| `BOT_TIMEZONE` | *(optional)* default `Asia/Singapore` |

4. Deploy, then message your bot `/whoami`. Set `TELEGRAM_CHAT_ID` to the number it replies with and redeploy.

Once `TELEGRAM_CHAT_ID` is set, the bot only answers you and ignores messages from anyone else.

## Notes

- **Where edits go.** New events go on `GOOGLE_CALENDAR_ID`. Calendars in `GOOGLE_EXTRA_CALENDAR_IDS` show up in the briefs, but the bot won't edit them unless you share them with **Make changes to events**.
- **Recurring events.** Edits and deletions only change the single occurrence you name, never the whole series.
- **Context.** The bot remembers your last few messages, so a follow-up like "actually make it 4pm" works.
- **Local run.** `pip install -r requirements.txt`, export the variables above, then `python bot.py`.

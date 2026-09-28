"""Telegram scheduling bot: morning briefs, weekly overview, calendar edits, to-dos."""
import asyncio
import logging
import uuid
from datetime import date, datetime, time, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import config
import formatting as fmt
from gcal import Calendar
from todos import Todos

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("schedule-bot")

cal = Calendar()
todos = Todos()
agent = None
if config.ANTHROPIC_API_KEY:
    from agent import Agent
    agent = Agent(cal, todos)

HELP = (
    "<b>Commands</b>\n"
    "/today · /tomorrow — that day's plans\n"
    "/week — the next 7 days\n"
    "/todo — show the list · <code>/todo buy stamps</code> — add one\n"
    "/done 3 — tick off #3 · /drop 3 — remove #3\n\n"
    "Or just write, e.g. <i>move lunch with Yan Han to 1pm</i>, "
    "<i>add Parliament sitting Tue 1:30pm to 7pm</i>, "
    "<i>remind me to file expenses by Friday</i>, <i>cancel tomorrow's 10am</i>."
)


def _today() -> date:
    return datetime.now(config.TZ).date()


async def _events(start: date, days: int) -> list[dict]:
    s = datetime.combine(start, time.min, config.TZ)
    return await asyncio.to_thread(cal.list_events, s, s + timedelta(days=days))


async def daily_text(d: date) -> str:
    return fmt.daily_brief(d, await _events(d, 1), todos.open())


async def weekly_text(start: date) -> str:
    return fmt.weekly_brief(start, await _events(start, 7), todos.open(), _today())


async def send_html(bot, text: str):
    await bot.send_message(config.CHAT_ID, text[:4000], parse_mode=ParseMode.HTML)


# ---------- scheduled job ----------

async def morning_job(ctx: ContextTypes.DEFAULT_TYPE):
    today = _today()
    try:
        if today.weekday() == config.WEEKLY_DAY:
            await send_html(ctx.bot, await weekly_text(today))
        await send_html(ctx.bot, await daily_text(today))
    except Exception as exc:
        log.exception("morning brief failed")
        await ctx.bot.send_message(config.CHAT_ID, f"Morning brief failed: {exc}")


# ---------- commands ----------

async def whoami(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your chat id is {update.effective_chat.id}")


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP, parse_mode=ParseMode.HTML)


async def today_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await daily_text(_today()), parse_mode=ParseMode.HTML)


async def tomorrow_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await daily_text(_today() + timedelta(days=1)), parse_mode=ParseMode.HTML)


async def week_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await weekly_text(_today()), parse_mode=ParseMode.HTML)


async def todo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args:
        t = todos.add(" ".join(ctx.args))
        await update.message.reply_text(f"Added #{t['id']}: {t['text']}")
    else:
        await update.message.reply_text(fmt.todo_list(todos.open(), _today()), parse_mode=ParseMode.HTML)


async def _by_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action):
    if not ctx.args or not ctx.args[0].lstrip("#").isdigit():
        await update.message.reply_text("Give me the number, e.g. /done 3")
        return None
    return action(int(ctx.args[0].lstrip("#")))


async def done_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = await _by_id(update, ctx, todos.complete)
    if t:
        await update.message.reply_text(f"Done: {t['text']}")
    elif ctx.args:
        await update.message.reply_text("No open to-do with that number.")


async def drop_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ok = await _by_id(update, ctx, todos.delete)
    if ctx.args:
        await update.message.reply_text("Removed." if ok else "No to-do with that number.")


# ---------- free text ----------

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if agent is None:
        await update.message.reply_text("Free-text editing needs ANTHROPIC_API_KEY set. Commands still work — /help")
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        reply, pending = await agent.handle(update.message.text)
    except Exception as exc:
        log.exception("agent failed")
        reply, pending = f"Something went wrong: {exc}", []
    await update.message.reply_text(reply[:4000])

    for ev in pending:
        key = uuid.uuid4().hex[:10]
        ctx.bot_data.setdefault("pending", {})[key] = ev
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("Delete", callback_data=f"del:{key}"),
            InlineKeyboardButton("Keep", callback_data=f"keep:{key}"),
        ]])
        await update.message.reply_text(f"Delete “{ev['title']}” — {fmt.when(ev)}?", reply_markup=buttons)


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if update.effective_chat.id != config.CHAT_ID:
        await q.answer()
        return
    action, key = q.data.split(":", 1)
    ev = ctx.bot_data.get("pending", {}).pop(key, None)
    if ev is None:
        await q.answer("This confirmation has expired.")
        await q.edit_message_reply_markup(None)
        return
    if action == "del":
        try:
            await asyncio.to_thread(cal.delete_event, ev["id"], ev["calendar_id"])
            await q.edit_message_text(f"Deleted: {ev['title']} ({fmt.when(ev)})")
        except Exception as exc:
            await q.edit_message_text(f"Couldn't delete {ev['title']}: {exc}")
    else:
        await q.edit_message_text(f"Kept: {ev['title']}")
    await q.answer()


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=ctx.error)


def main():
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_error_handler(on_error)

    if config.CHAT_ID is None:
        log.warning("TELEGRAM_CHAT_ID is not set: only /whoami will respond.")
    else:
        me = filters.Chat(chat_id=config.CHAT_ID)
        app.add_handler(CommandHandler(["start", "help"], help_cmd, filters=me))
        app.add_handler(CommandHandler("today", today_cmd, filters=me))
        app.add_handler(CommandHandler("tomorrow", tomorrow_cmd, filters=me))
        app.add_handler(CommandHandler("week", week_cmd, filters=me))
        app.add_handler(CommandHandler("todo", todo_cmd, filters=me))
        app.add_handler(CommandHandler("done", done_cmd, filters=me))
        app.add_handler(CommandHandler("drop", drop_cmd, filters=me))
        app.add_handler(MessageHandler(me & filters.TEXT & ~filters.COMMAND, on_text))
        app.add_handler(CallbackQueryHandler(on_button))
        app.job_queue.run_daily(morning_job, time=config.DAILY_TIME, name="morning-brief")
        log.info("Morning brief scheduled for %s %s", config.DAILY_TIME.strftime("%H:%M"), config.TZ)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

"""Turns events and to-dos into Telegram messages (HTML parse mode)."""
from datetime import date, datetime, time, timedelta
from html import escape

import config


def _on_day(ev: dict, d: date) -> bool:
    start = datetime.combine(d, time.min, config.TZ)
    return ev["start"] < start + timedelta(days=1) and ev["end"] > start


def _time_label(ev: dict, d: date) -> str:
    if ev["all_day"]:
        return "All day"
    s, e = ev["start"], ev["end"]
    left = f"{s:%H:%M}" if s.date() == d else "…"
    right = f"{e:%H:%M}" if e.date() == d else "…"
    return f"{left}–{right}"


def _event_line(ev: dict, d: date) -> str:
    line = f"<code>{_time_label(ev, d):<11}</code> {escape(ev['title'])}"
    if ev.get("location"):
        line += f" <i>· {escape(ev['location'])}</i>"
    return line


def _todo_line(t: dict, today: date) -> str:
    line = f"#{t['id']} {escape(t['text'])}"
    if t["due"]:
        due = date.fromisoformat(t["due"])
        if due < today:
            line += f" <i>(overdue · {due:%a %d %b})</i>"
        elif due == today:
            line += " <i>(today)</i>"
        else:
            line += f" <i>({due:%a %d %b})</i>"
    return line


def when(ev: dict) -> str:
    """Short human description of an event's timing, for confirmations."""
    if ev["all_day"]:
        text = f"{ev['start']:%a %d %b} (all day)"
    else:
        text = f"{ev['start']:%a %d %b, %H:%M}"
    if ev.get("recurring"):
        text += " — this occurrence only"
    return text


def daily_brief(d: date, events: list[dict], open_todos: list[dict]) -> str:
    lines = [f"<b>{d:%A %d %B}</b>"]
    lines += [_event_line(e, d) for e in events if _on_day(e, d)] or ["Nothing on the calendar."]

    now = [t for t in open_todos if not t["due"] or date.fromisoformat(t["due"]) <= d]
    later = len(open_todos) - len(now)
    if now or later:
        lines += ["", "<b>To-do</b>"]
        lines += [_todo_line(t, d) for t in now]
        if later:
            lines.append(f"<i>+{later} due later — /todo to see all</i>")
    return "\n".join(lines)


def weekly_brief(start: date, events: list[dict], open_todos: list[dict], today: date) -> str:
    end = start + timedelta(days=6)
    lines = [f"<b>Week ahead: {start:%d %b} – {end:%d %b}</b>"]
    for i in range(7):
        d = start + timedelta(days=i)
        lines += ["", f"<b>{d:%a %d %b}</b>"]
        lines += [_event_line(e, d) for e in events if _on_day(e, d)] or ["—"]

    dated = [t for t in open_todos if t["due"] and date.fromisoformat(t["due"]) <= end]
    undated = [t for t in open_todos if not t["due"]]
    if dated or undated:
        lines += ["", "<b>To-do this week</b>"]
        lines += [_todo_line(t, today) for t in dated]
        if undated:
            lines.append(f"<i>+{len(undated)} with no date — /todo</i>")
    return "\n".join(lines)


def todo_list(open_todos: list[dict], today: date) -> str:
    if not open_todos:
        return "Nothing on the list."
    return "<b>To-do</b>\n" + "\n".join(_todo_line(t, today) for t in open_todos)

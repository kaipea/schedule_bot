"""Free-text handling: Claude reads your message and calls calendar / to-do tools."""
import asyncio
import json
from datetime import date, datetime, time, timedelta

from anthropic import AsyncAnthropic

import config

TOOLS = [
    {
        "name": "list_events",
        "description": "List calendar events between two dates, inclusive. Use it to find an event's id before updating or deleting it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "create_event",
        "description": "Create an event on the user's main calendar. Timed events default to 1 hour if no end is given.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string", "description": "YYYY-MM-DDTHH:MM in local time, or YYYY-MM-DD if all_day"},
                "end": {"type": "string", "description": "Same format as start. For all-day events this is the last day, inclusive."},
                "all_day": {"type": "boolean"},
                "location": {"type": "string"},
                "private": {"type": "boolean", "description": "Private events appear only as 'Busy' in the schedule shared with others"},
                "description": {"type": "string"},
            },
            "required": ["title", "start"],
        },
    },
    {
        "name": "update_event",
        "description": "Change an existing event. Only pass fields that change. Moving the start without an end keeps the event's length.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "calendar_id": {"type": "string", "description": "From list_events; omit for the main calendar"},
                "title": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "all_day": {"type": "boolean"},
                "location": {"type": "string"},
                "private": {"type": "boolean", "description": "Private events appear only as 'Busy' in the schedule shared with others"},
                "description": {"type": "string"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "delete_event",
        "description": "Stage an event for deletion. Nothing is deleted until the user taps a confirmation button.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}, "calendar_id": {"type": "string"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "list_todos",
        "description": "List open to-dos.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_todo",
        "description": "Add a to-do, optionally with a due date.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "due": {"type": "string", "description": "YYYY-MM-DD"}},
            "required": ["text"],
        },
    },
    {
        "name": "complete_todo",
        "description": "Mark a to-do as done.",
        "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
    {
        "name": "delete_todo",
        "description": "Remove a to-do without marking it done.",
        "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
]


def _event_out(e: dict) -> dict:
    out = {
        "id": e["id"],
        "calendar_id": e["calendar_id"],
        "title": e["title"],
        "all_day": e["all_day"],
        "location": e.get("location"),
        "recurring": e["recurring"],
        "private": e.get("private", False),
        "editable": e["calendar_id"] == config.WRITE_CALENDAR_ID,
    }
    if e["all_day"]:
        out["start"] = e["start"].date().isoformat()
        out["end"] = (e["end"] - timedelta(days=1)).date().isoformat()  # inclusive
    else:
        out["start"] = e["start"].isoformat(timespec="minutes")
        out["end"] = e["end"].isoformat(timespec="minutes")
    return out


class Agent:
    def __init__(self, calendar, todos):
        self.client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self.cal = calendar
        self.todos = todos
        self.history: list[tuple[str, str]] = []  # recent (role, text) turns, so "move it to 4pm" works
        self.lock = asyncio.Lock()

    def _system(self) -> str:
        now = datetime.now(config.TZ)
        return (
            "You manage the user's Google Calendar and to-do list through a Telegram chat.\n"
            f"It is now {now:%A %d %B %Y, %H:%M} ({config.TZ}). Interpret all times in this timezone.\n"
            "- To change or delete an event, find it with list_events first so you have its id.\n"
            "- If more than one event could match, or a time is unclear, ask instead of guessing.\n"
            "- delete_event only stages a deletion; tell the user to tap the button to confirm.\n"
            "- Events with editable=false are on read-only calendars; say so rather than trying to edit them.\n"
            "- For recurring events, changes apply to the single occurrence you edit.\n"
            "- The user's week is sent to family, friends and colleagues every week. Events marked "
            "private show to them only as 'Busy'. Set private when the user asks to hide an event.\n"
            "- Reply briefly in plain text (no markdown). Confirm what you changed, with day and time."
        )

    async def _tool(self, name: str, args: dict, pending: list):
        if name == "list_events":
            start = datetime.combine(date.fromisoformat(args["start_date"]), time.min, config.TZ)
            end = datetime.combine(date.fromisoformat(args["end_date"]), time.min, config.TZ) + timedelta(days=1)
            return [_event_out(e) for e in await asyncio.to_thread(self.cal.list_events, start, end)]
        if name == "create_event":
            return _event_out(await asyncio.to_thread(self.cal.create_event, **args))
        if name == "update_event":
            return _event_out(await asyncio.to_thread(self.cal.update_event, **args))
        if name == "delete_event":
            ev = await asyncio.to_thread(self.cal.get_event, args["event_id"], args.get("calendar_id"))
            pending.append(ev)
            return {"status": "staged; the user must tap Delete to confirm", "event": _event_out(ev)}
        if name == "list_todos":
            return self.todos.open()
        if name == "add_todo":
            return self.todos.add(args["text"], args.get("due"))
        if name == "complete_todo":
            return self.todos.complete(int(args["id"])) or {"error": "no open to-do with that id"}
        if name == "delete_todo":
            return {"deleted": self.todos.delete(int(args["id"]))}
        return {"error": f"unknown tool {name}"}

    async def handle(self, text: str) -> tuple[str, list[dict]]:
        """Returns (reply text, events staged for deletion)."""
        async with self.lock:
            messages = [{"role": r, "content": c} for r, c in self.history]
            messages.append({"role": "user", "content": text})
            pending: list[dict] = []
            reply = ""

            for _ in range(10):
                resp = await self.client.messages.create(
                    model=config.CLAUDE_MODEL, max_tokens=1024,
                    system=self._system(), tools=TOOLS, messages=messages,
                )
                messages.append({"role": "assistant", "content": resp.content})
                if resp.stop_reason != "tool_use":
                    reply = "".join(b.text for b in resp.content if b.type == "text").strip()
                    break
                results = []
                for block in resp.content:
                    if block.type != "tool_use":
                        continue
                    try:
                        out, is_error = await self._tool(block.name, block.input, pending), False
                    except Exception as exc:  # report back so Claude can recover or explain
                        out, is_error = {"error": f"{type(exc).__name__}: {exc}"}, True
                    results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": json.dumps(out, default=str), "is_error": is_error,
                    })
                messages.append({"role": "user", "content": results})
            else:
                reply = "That took too many steps. Could you break it into smaller requests?"

            reply = reply or "Done."
            self.history = (self.history + [("user", text), ("assistant", reply)])[-12:]
            return reply, pending

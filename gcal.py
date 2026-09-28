"""Thin wrapper around the Google Calendar API, using a service account."""
import json
import threading
from datetime import date, datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

import config

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _parse_dt(value: str) -> datetime:
    """Parse an ISO datetime; naive values are taken to be in the bot's timezone."""
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=config.TZ) if dt.tzinfo is None else dt


def _midnight(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), config.TZ)


def _normalise(raw: dict, calendar_id: str) -> dict:
    start, end = raw.get("start", {}), raw.get("end", {})
    all_day = "date" in start
    if all_day:
        s = _midnight(date.fromisoformat(start["date"]))
        e = _midnight(date.fromisoformat(end["date"]))  # Google's end date is exclusive
    else:
        s = datetime.fromisoformat(start["dateTime"]).astimezone(config.TZ)
        e = datetime.fromisoformat(end["dateTime"]).astimezone(config.TZ)
    return {
        "id": raw["id"],
        "calendar_id": calendar_id,
        "title": raw.get("summary") or "(no title)",
        "start": s,
        "end": e,
        "all_day": all_day,
        "location": raw.get("location"),
        "recurring": "recurringEventId" in raw,
        # Google's per-event "Private" visibility; shared schedules show these as "Busy".
        "private": raw.get("visibility") in ("private", "confidential"),
    }


def _time_fields(start: str, end: str | None, all_day: bool) -> dict:
    if all_day:
        s = date.fromisoformat(start[:10])
        e = date.fromisoformat((end or start)[:10])  # inclusive last day
        return {"start": {"date": s.isoformat()}, "end": {"date": (e + timedelta(days=1)).isoformat()}}
    s = _parse_dt(start)
    e = _parse_dt(end) if end else s + timedelta(hours=1)
    tz = str(config.TZ)
    return {
        "start": {"dateTime": s.isoformat(), "timeZone": tz},
        "end": {"dateTime": e.isoformat(), "timeZone": tz},
    }


class Calendar:
    def __init__(self):
        info = json.loads(config.GOOGLE_SA_JSON)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        self._svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
        # The Google client isn't thread-safe and we call it from worker threads.
        self._lock = threading.Lock()

    def _run(self, request):
        with self._lock:
            return request.execute()

    def list_events(self, start: datetime, end: datetime) -> list[dict]:
        events = []
        for cid in config.READ_CALENDAR_IDS:
            token = None
            while True:
                resp = self._run(self._svc.events().list(
                    calendarId=cid, timeMin=start.isoformat(), timeMax=end.isoformat(),
                    singleEvents=True, orderBy="startTime", maxResults=250, pageToken=token,
                ))
                events.extend(
                    _normalise(e, cid) for e in resp.get("items", []) if e.get("status") != "cancelled"
                )
                token = resp.get("nextPageToken")
                if not token:
                    break
        events.sort(key=lambda e: (e["start"], 0 if e["all_day"] else 1))
        return events

    def get_event(self, event_id: str, calendar_id: str | None = None) -> dict:
        cid = calendar_id or config.WRITE_CALENDAR_ID
        return _normalise(self._run(self._svc.events().get(calendarId=cid, eventId=event_id)), cid)

    def create_event(self, title: str, start: str, end: str | None = None, all_day: bool = False,
                     location: str | None = None, description: str | None = None,
                     private: bool = False) -> dict:
        body = {"summary": title, **_time_fields(start, end, bool(all_day))}
        if private:
            body["visibility"] = "private"
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        cid = config.WRITE_CALENDAR_ID
        return _normalise(self._run(self._svc.events().insert(calendarId=cid, body=body)), cid)

    def update_event(self, event_id: str, calendar_id: str | None = None, title: str | None = None,
                     start: str | None = None, end: str | None = None, all_day: bool | None = None,
                     location: str | None = None, description: str | None = None,
                     private: bool | None = None) -> dict:
        cid = calendar_id or config.WRITE_CALENDAR_ID
        raw = self._run(self._svc.events().get(calendarId=cid, eventId=event_id))
        cur = _normalise(raw, cid)

        if private is not None:
            raw["visibility"] = "private" if private else "default"
        if title:
            raw["summary"] = title
        if location is not None:
            raw["location"] = location
        if description is not None:
            raw["description"] = description

        if start or end or all_day is not None:
            to_all_day = cur["all_day"] if all_day is None else bool(all_day)
            if to_all_day:
                s = date.fromisoformat((start or cur["start"].date().isoformat())[:10])
                span_days = (cur["end"].date() - cur["start"].date()).days if cur["all_day"] else 1
                e = date.fromisoformat(end[:10]) if end else s + timedelta(days=max(span_days, 1) - 1)
                raw.update(_time_fields(s.isoformat(), e.isoformat(), True))
            else:
                s = _parse_dt(start) if start else cur["start"]
                duration = timedelta(hours=1) if cur["all_day"] else cur["end"] - cur["start"]
                e = _parse_dt(end) if end else s + duration  # moving an event keeps its length
                raw.update(_time_fields(s.isoformat(), e.isoformat(), False))

        return _normalise(self._run(self._svc.events().update(calendarId=cid, eventId=event_id, body=raw)), cid)

    def delete_event(self, event_id: str, calendar_id: str | None = None) -> None:
        cid = calendar_id or config.WRITE_CALENDAR_ID
        self._run(self._svc.events().delete(calendarId=cid, eventId=event_id))

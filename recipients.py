"""People who receive your weekly schedule. Stored in the same SQLite file as to-dos."""
import os
import sqlite3
from datetime import datetime

import config


class Recipients:
    def __init__(self, path: str = config.DB_PATH):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS recipients (
                   chat_id INTEGER PRIMARY KEY,
                   name TEXT NOT NULL,
                   added_at TEXT NOT NULL
               )"""
        )
        self.db.commit()

    def add(self, chat_id: int, name: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO recipients (chat_id, name, added_at) VALUES (?, ?, ?)",
            (chat_id, name, datetime.now(config.TZ).isoformat()),
        )
        self.db.commit()

    def remove(self, chat_id: int) -> dict | None:
        row = self.get(chat_id)
        if row:
            self.db.execute("DELETE FROM recipients WHERE chat_id = ?", (chat_id,))
            self.db.commit()
        return row

    def get(self, chat_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM recipients WHERE chat_id = ?", (chat_id,)).fetchone()
        return dict(row) if row else None

    def all(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM recipients ORDER BY added_at")]

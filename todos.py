"""To-do list stored in SQLite."""
import os
import sqlite3
from datetime import date, datetime

import config


class Todos:
    def __init__(self, path: str = config.DB_PATH):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS todos (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   text TEXT NOT NULL,
                   due TEXT,                 -- YYYY-MM-DD or NULL
                   done INTEGER NOT NULL DEFAULT 0,
                   created_at TEXT NOT NULL,
                   done_at TEXT
               )"""
        )
        self.db.commit()

    def add(self, text: str, due: str | None = None) -> dict:
        if due:
            due = date.fromisoformat(due[:10]).isoformat()  # validate
        cur = self.db.execute(
            "INSERT INTO todos (text, due, created_at) VALUES (?, ?, ?)",
            (text.strip(), due, datetime.now(config.TZ).isoformat()),
        )
        self.db.commit()
        return self.get(cur.lastrowid)

    def get(self, todo_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        return dict(row) if row else None

    def open(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM todos WHERE done = 0 ORDER BY due IS NULL, due, id"
        ).fetchall()
        return [dict(r) for r in rows]

    def complete(self, todo_id: int) -> dict | None:
        cur = self.db.execute(
            "UPDATE todos SET done = 1, done_at = ? WHERE id = ? AND done = 0",
            (datetime.now(config.TZ).isoformat(), todo_id),
        )
        self.db.commit()
        return self.get(todo_id) if cur.rowcount else None

    def delete(self, todo_id: int) -> bool:
        cur = self.db.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        self.db.commit()
        return cur.rowcount > 0

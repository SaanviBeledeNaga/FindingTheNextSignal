from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: str | Path = ".pharma"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.archive = self.root / "archive"
        self.archive.mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "research.db")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
            publisher TEXT NOT NULL, published TEXT NOT NULL, url TEXT NOT NULL,
            sha256 TEXT NOT NULL, archived TEXT NOT NULL, pages TEXT NOT NULL,
            demo INTEGER NOT NULL, UNIQUE(company,sha256));
        CREATE TABLE IF NOT EXISTS observations (
            id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
            company TEXT NOT NULL, period INTEGER NOT NULL, region TEXT NOT NULL,
            value TEXT NOT NULL, currency TEXT NOT NULL, unit TEXT NOT NULL,
            basis TEXT NOT NULL, definition TEXT NOT NULL, page INTEGER NOT NULL,
            quote TEXT NOT NULL, demo INTEGER NOT NULL,
            UNIQUE(source_id, period, region, basis, definition));
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, company TEXT NOT NULL, created TEXT NOT NULL,
            status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS challenges (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
            finding_id TEXT NOT NULL, created TEXT NOT NULL,
            question TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_states (
            id TEXT PRIMARY KEY, updated TEXT NOT NULL, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tool_cache (
            key TEXT PRIMARY KEY, created TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_meta (
            source_id TEXT PRIMARY KEY REFERENCES sources(id), payload TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def checkpoint(self, state):
        self.db.execute("INSERT OR REPLACE INTO agent_states VALUES (?,?,?)", (state["id"], now(), json.dumps(state)))
        self.db.commit()

    def agent_state(self, agent_id):
        row = self.db.execute("SELECT state FROM agent_states WHERE id=?", (agent_id,)).fetchone()
        if not row:
            raise ValueError("Unknown agent investigation ID.")
        return json.loads(row[0])

    def cache(self, key, value=None):
        if value is not None:
            self.db.execute("INSERT OR REPLACE INTO tool_cache VALUES (?,?,?)", (key, now(), json.dumps(value)))
            self.db.commit()
            return value
        row = self.db.execute("SELECT payload FROM tool_cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def metadata(self, source_id, value=None):
        if value is not None:
            self.db.execute("INSERT OR REPLACE INTO source_meta VALUES (?,?)", (source_id, json.dumps(value)))
            self.db.commit()
            return value
        row = self.db.execute("SELECT payload FROM source_meta WHERE source_id=?", (source_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def sources(self, company=None):
        if company:
            rows = self.db.execute("SELECT * FROM sources WHERE company=? ORDER BY published,id", (company.upper(),))
        else:
            rows = self.db.execute("SELECT * FROM sources ORDER BY company,published,id")
        return [dict(r) | {"pages": json.loads(r["pages"])} for r in rows]

    def observations(self, company):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM observations WHERE company=? ORDER BY period,region,id", (company.upper(),))]

    def save_run(self, run):
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)", (
            run["id"], run["company"], run["created"], run["status"], json.dumps(run)))
        self.db.commit()

    def run(self, run_id="latest"):
        row = self.db.execute("SELECT payload FROM runs ORDER BY created DESC LIMIT 1" if run_id == "latest"
                              else "SELECT payload FROM runs WHERE id=?", () if run_id == "latest" else (run_id,)).fetchone()
        if row is None:
            raise ValueError("Run not found. Start with: python -m pharma_scope demo")
        return json.loads(row[0])

    def challenges(self, run_id):
        return [dict(r) | {"payload": json.loads(r["payload"])} for r in self.db.execute(
            "SELECT * FROM challenges WHERE run_id=? ORDER BY created", (run_id,))]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

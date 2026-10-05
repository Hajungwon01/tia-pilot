"""SQLite 저장소: 분석 결과(작업)와 실제 LLM 호출 기록.

- 서버를 재시작해도 결과·호출 횟수가 유지된다(영구 볼륨에 DB 파일을 둔다).
- 작업은 소유자(owner)에 묶여, 다른 사용자가 job_id를 알아도 조회할 수 없다.
- 단일 인스턴스(또는 같은 볼륨을 공유하는 프로세스) 전제. 다중 서버로 확장하려면 Postgres 이전이 필요하다.
"""
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from app.state import ReportState

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    created_at REAL NOT NULL,
    state_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
CREATE TABLE IF NOT EXISTS llm_runs (
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_runs_ts ON llm_runs(ts);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)  # 명시적 트랜잭션 사용
        try:
            c.execute("PRAGMA journal_mode=WAL")
            yield c
        finally:
            c.close()


class SqliteJobStore:
    def __init__(self, db: Database, ttl_sec: int = 72 * 3600, max_items: int = 5000) -> None:
        self.db, self.ttl, self.max_items = db, ttl_sec, max_items

    def put(self, state: ReportState, owner: str, now: float | None = None) -> str:
        now = time.time() if now is None else now
        job_id = uuid.uuid4().hex
        with self.db.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM jobs WHERE created_at < ?", (now - self.ttl,))
            c.execute("INSERT INTO jobs(id, owner, created_at, state_json) VALUES (?,?,?,?)",
                      (job_id, owner, now, state.model_dump_json()))
            c.execute("DELETE FROM jobs WHERE id IN (SELECT id FROM jobs ORDER BY created_at DESC LIMIT -1 OFFSET ?)",
                      (self.max_items,))
            c.execute("COMMIT")
        return job_id

    def get(self, job_id: str, owner: str, now: float | None = None) -> ReportState | None:
        now = time.time() if now is None else now
        with self.db.conn() as c:
            row = c.execute("SELECT state_json, created_at FROM jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
        if not row or now - row[1] > self.ttl:
            return None
        return ReportState.model_validate_json(row[0])

    def count(self) -> int:
        with self.db.conn() as c:
            return c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


class LlmRunLog:
    """실제 LLM 분석의 시간당 횟수를 DB에 기록해 제한한다(재시작·여러 프로세스에도 유지)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def allow(self, limit: int, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self.db.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM llm_runs WHERE ts < ?", (now - 3600,))
            n = c.execute("SELECT COUNT(*) FROM llm_runs").fetchone()[0]
            if n >= limit:
                c.execute("COMMIT")
                return False
            c.execute("INSERT INTO llm_runs(ts) VALUES (?)", (now,))
            c.execute("COMMIT")
        return True

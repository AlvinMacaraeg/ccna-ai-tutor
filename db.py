"""
SQLite-backed progress tracker. No LLM calls in this file at all.

Schema v1 (current): topics are normalized into their own `topics` table,
referenced by `topic_id` foreign keys from `topic_progress` and `session_log`,
instead of repeating the topic name as a string in every row. Indexes exist on
the columns that get queried as your history grows. Schema version is tracked
via SQLite's built-in PRAGMA user_version, so future changes can add their own
migration step without ever touching your existing data.

Every public function below still takes/returns topic NAMES (strings), exactly
as before — the topic_id lookup happens internally, so nothing calling into
this file (main.py, ai.py) needed to change.
"""

import json
import sqlite3
from datetime import date, timedelta, datetime
from pathlib import Path

from topics import TOPICS, default_topic_row

DB_PATH = Path(__file__).parent / "progress.db"
SCHEMA_VERSION = 4


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Schema versioning & migration
# ---------------------------------------------------------------------------

def _get_schema_version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _set_schema_version(conn, version: int):
    conn.execute(f"PRAGMA user_version = {version}")


def _migrate_to_v1(conn):
    """
    v0 -> v1: normalizes the repeated 'topic' TEXT column into a proper `topics`
    table, with topic_progress/session_log referencing it by topic_id (foreign
    key). Adds indexes. Safe on a brand-new empty DB (nothing to migrate) or an
    existing v0 DB with real history (every row is preserved, just re-pointed).
    """
    cur = conn.cursor()

    old_topic_progress_exists = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='topic_progress'"
    ).fetchone() is not None

    is_old_schema = False
    if old_topic_progress_exists:
        cols = [r[1] for r in cur.execute("PRAGMA table_info(topic_progress)").fetchall()]
        is_old_schema = "topic" in cols and "topic_id" not in cols

    cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    if is_old_schema:
        # Collect every distinct topic name that's ever actually been used.
        old_names = {r[0] for r in cur.execute("SELECT DISTINCT topic FROM topic_progress")}
        if cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_log'"
        ).fetchone():
            old_names |= {r[0] for r in cur.execute("SELECT DISTINCT topic FROM session_log")}

        for name in old_names:
            cur.execute("INSERT OR IGNORE INTO topics (name) VALUES (?)", (name,))

        # Rebuild topic_progress with a topic_id FK, preserving every row.
        cur.execute("ALTER TABLE topic_progress RENAME TO topic_progress_old")
        cur.execute("""
            CREATE TABLE topic_progress (
                topic_id INTEGER PRIMARY KEY REFERENCES topics(id),
                ease REAL, interval_days INTEGER, reps INTEGER,
                last_seen TEXT, next_due TEXT, attempts INTEGER, correct INTEGER
            )
        """)
        cur.execute("""
            INSERT INTO topic_progress (topic_id, ease, interval_days, reps, last_seen, next_due, attempts, correct)
            SELECT topics.id, o.ease, o.interval_days, o.reps, o.last_seen, o.next_due, o.attempts, o.correct
            FROM topic_progress_old o JOIN topics ON topics.name = o.topic
        """)
        cur.execute("DROP TABLE topic_progress_old")

        # Rebuild session_log with a topic_id FK, preserving every row (including its original id).
        if cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_log'"
        ).fetchone():
            cur.execute("ALTER TABLE session_log RENAME TO session_log_old")
            cur.execute("""
                CREATE TABLE session_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_id INTEGER REFERENCES topics(id),
                    question TEXT, your_answer TEXT, score INTEGER, feedback TEXT, timestamp TEXT
                )
            """)
            cur.execute("""
                INSERT INTO session_log (id, topic_id, question, your_answer, score, feedback, timestamp)
                SELECT o.id, topics.id, o.question, o.your_answer, o.score, o.feedback, o.timestamp
                FROM session_log_old o JOIN topics ON topics.name = o.topic
            """)
            cur.execute("DROP TABLE session_log_old")
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS topic_progress (
                topic_id INTEGER PRIMARY KEY REFERENCES topics(id),
                ease REAL, interval_days INTEGER, reps INTEGER,
                last_seen TEXT, next_due TEXT, attempts INTEGER, correct INTEGER
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER REFERENCES topics(id),
                question TEXT, your_answer TEXT, score INTEGER, feedback TEXT, timestamp TEXT
            )
        """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mock_exam_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, total_questions INTEGER, correct_count INTEGER,
            partial_count INTEGER, score_percent REAL, elapsed_seconds INTEGER,
            domain_breakdown TEXT
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_session_log_topic_id ON session_log(topic_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_session_log_timestamp ON session_log(timestamp)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mock_exam_log_timestamp ON mock_exam_log(timestamp)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_topics_name ON topics(name)")

    conn.commit()
    _set_schema_version(conn, 1)


def _migrate_to_v2(conn):
    """v1 -> v2: adds a nullable `confidence` column to session_log, for confidence-calibration
    tracking (are you confidently wrong on certain topics?). Existing rows just get NULL — no
    data loss, nothing to backfill since confidence wasn't collected before this version."""
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(session_log)").fetchall()]
    if "confidence" not in cols:
        cur.execute("ALTER TABLE session_log ADD COLUMN confidence INTEGER")
    conn.commit()
    _set_schema_version(conn, 2)


def _migrate_to_v3(conn):
    """v2 -> v3: adds a lab_reflections table for the Packet Tracer guided lab feature.
    Kept separate from session_log since reflections are free-text self-report (no score),
    not graded Q&A."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lab_reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id),
            lab_brief TEXT,
            reflection TEXT,
            ai_response TEXT,
            timestamp TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lab_reflections_topic_id ON lab_reflections(topic_id)")
    conn.commit()
    _set_schema_version(conn, 3)


def _migrate_to_v4(conn):
    """v3 -> v4: adds lab_flags, where you record mistakes you caught in AI-generated labs,
    scenarios or grades. Recent notes get fed back into future lab generation as 'known
    pitfalls', so the same mistake isn't repeated."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lab_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id),
            mode TEXT,
            brief TEXT,
            note TEXT,
            timestamp TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lab_flags_topic_id ON lab_flags(topic_id)")
    conn.commit()
    _set_schema_version(conn, 4)


def _migrate_if_needed(conn):
    version = _get_schema_version(conn)
    if version < 1:
        _migrate_to_v1(conn)
        version = 1
    if version < 2:
        _migrate_to_v2(conn)
        version = 2
    if version < 3:
        _migrate_to_v3(conn)
        version = 3
    if version < 4:
        _migrate_to_v4(conn)
        version = 4
    # Future schema changes: add `if version < 5: _migrate_to_v5(conn)` etc. here.


def _get_or_create_topic_id(conn, name: str) -> int:
    row = conn.execute("SELECT id FROM topics WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO topics (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def init_db():
    conn = get_conn()
    _migrate_if_needed(conn)

    # Seed topics table + a topic_progress row for every topic in topics.py.
    # Also silently picks up topics added later (like when we added
    # "Troubleshooting Methodology") — no manual migration needed for that.
    for name in TOPICS:
        conn.execute("INSERT OR IGNORE INTO topics (name) VALUES (?)", (name,))
    conn.commit()

    existing_ids = {r["topic_id"] for r in conn.execute("SELECT topic_id FROM topic_progress")}
    for name in TOPICS:
        topic_id = conn.execute("SELECT id FROM topics WHERE name = ?", (name,)).fetchone()["id"]
        if topic_id not in existing_ids:
            row = default_topic_row(name)
            conn.execute(
                """INSERT INTO topic_progress
                   (topic_id, ease, interval_days, reps, last_seen, next_due, attempts, correct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (topic_id, row["ease"], row["interval_days"], row["reps"],
                 row["last_seen"], row["next_due"], row["attempts"], row["correct"]),
            )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Spaced repetition / progress
# ---------------------------------------------------------------------------

def get_due_topics():
    """Topics that are due for review today (or never studied), ordered by mastery ascending."""
    conn = get_conn()
    today = date.today().isoformat()
    rows = conn.execute(
        """SELECT topics.name AS topic, tp.* FROM topic_progress tp
           JOIN topics ON topics.id = tp.topic_id
           WHERE tp.next_due IS NULL OR tp.next_due <= ?
           ORDER BY
             CASE WHEN tp.attempts = 0 THEN 0 ELSE CAST(tp.correct AS FLOAT)/tp.attempts END ASC,
             tp.next_due ASC""",
        (today,),
    ).fetchall()
    conn.close()
    return rows


def get_all_progress():
    conn = get_conn()
    rows = conn.execute(
        """SELECT topics.name AS topic, tp.* FROM topic_progress tp
           JOIN topics ON topics.id = tp.topic_id
           ORDER BY topics.name ASC"""
    ).fetchall()
    conn.close()
    return rows


def update_after_answer(topic: str, score: int):
    """score: 0 (wrong), 1 (partially correct), 2 (correct) — a simplified SM-2 update."""
    conn = get_conn()
    topic_id = _get_or_create_topic_id(conn, topic)
    row = conn.execute("SELECT * FROM topic_progress WHERE topic_id = ?", (topic_id,)).fetchone()

    if row is None:  # defensive: topic added after this session's init_db() already ran
        default = default_topic_row(topic)
        conn.execute(
            """INSERT INTO topic_progress (topic_id, ease, interval_days, reps, last_seen, next_due, attempts, correct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (topic_id, default["ease"], default["interval_days"], default["reps"],
             default["last_seen"], default["next_due"], default["attempts"], default["correct"]),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM topic_progress WHERE topic_id = ?", (topic_id,)).fetchone()

    ease = row["ease"]
    reps = row["reps"]
    interval = row["interval_days"]

    if score == 0:
        reps = 0
        interval = 1
        ease = max(1.3, ease - 0.2)
    else:
        reps += 1
        if score == 1:
            ease = max(1.3, ease - 0.05)
            interval = max(1, round(interval * 1.2)) if interval else 1
        else:  # score == 2, fully correct
            ease = min(2.8, ease + 0.1)
            if reps == 1:
                interval = 1
            elif reps == 2:
                interval = 3
            else:
                interval = round(interval * ease)

    today = date.today()
    next_due = (today + timedelta(days=interval)).isoformat()

    conn.execute(
        """UPDATE topic_progress
           SET ease = ?, interval_days = ?, reps = ?, last_seen = ?, next_due = ?,
               attempts = attempts + 1, correct = correct + ?
           WHERE topic_id = ?""",
        (ease, interval, reps, today.isoformat(), next_due, 1 if score == 2 else 0, topic_id),
    )
    conn.commit()
    conn.close()


def log_session(topic: str, question: str, your_answer: str, score: int, feedback: str, confidence: int = None):
    conn = get_conn()
    topic_id = _get_or_create_topic_id(conn, topic)
    conn.execute(
        """INSERT INTO session_log (topic_id, question, your_answer, score, feedback, timestamp, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (topic_id, question, your_answer, score, feedback, date.today().isoformat(), confidence),
    )
    conn.commit()
    conn.close()


def get_past_mistakes(topic: str, limit: int = 3):
    """Most recent wrong/partial answers for a topic — feeds personalized re-teaching."""
    conn = get_conn()
    topic_id = _get_or_create_topic_id(conn, topic)
    rows = conn.execute(
        """SELECT question, your_answer, feedback FROM session_log
           WHERE topic_id = ? AND score < 2
           ORDER BY id DESC LIMIT ?""",
        (topic_id, limit),
    ).fetchall()
    conn.close()
    return rows


def get_mastery_level(topic: str) -> str:
    """Rough difficulty tier for question generation, based on track record."""
    conn = get_conn()
    topic_id = _get_or_create_topic_id(conn, topic)
    row = conn.execute("SELECT * FROM topic_progress WHERE topic_id = ?", (topic_id,)).fetchone()
    conn.close()
    if row is None or row["attempts"] == 0:
        return "beginner"
    accuracy = row["correct"] / row["attempts"]
    if row["reps"] >= 3 and accuracy >= 0.75:
        return "advanced"
    elif row["reps"] >= 1 and accuracy >= 0.5:
        return "intermediate"
    return "beginner"


def get_review_mistakes(limit: int = 20):
    """
    Every wrong/partial answer across ALL topics and modes (quiz, CLI practice,
    troubleshooting, scenarios), most recent first — powers the 'Review mistakes' menu.
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT topics.name AS topic, sl.question, sl.your_answer, sl.score, sl.feedback,
                  sl.timestamp, sl.confidence
           FROM session_log sl
           JOIN topics ON topics.id = sl.topic_id
           WHERE sl.score < 2
           ORDER BY sl.id DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Mock exams
# ---------------------------------------------------------------------------

def log_mock_exam(total_questions, correct_count, partial_count, score_percent,
                   elapsed_seconds, domain_breakdown: dict):
    conn = get_conn()
    conn.execute(
        """INSERT INTO mock_exam_log
           (timestamp, total_questions, correct_count, partial_count, score_percent,
            elapsed_seconds, domain_breakdown)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (date.today().isoformat(), total_questions, correct_count, partial_count,
         score_percent, elapsed_seconds, json.dumps(domain_breakdown)),
    )
    conn.commit()
    conn.close()


def get_mock_exam_history(limit: int = 10):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM mock_exam_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------

def get_calibration_report():
    """
    Compares self-rated confidence against actual accuracy — flags topics where you were
    confidently WRONG, which is a more dangerous failure mode than knowing you don't know.
    Returns None if no confidence data has been collected yet.
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT sl.confidence, sl.score, topics.name AS topic
           FROM session_log sl JOIN topics ON topics.id = sl.topic_id
           WHERE sl.confidence IS NOT NULL"""
    ).fetchall()
    conn.close()

    if not rows:
        return None

    by_confidence = {1: [], 2: [], 3: []}
    overconfident_topics = {}  # topic -> count of (confidence=3, score=0) instances

    for r in rows:
        by_confidence[r["confidence"]].append(r["score"])
        if r["confidence"] == 3 and r["score"] == 0:
            overconfident_topics[r["topic"]] = overconfident_topics.get(r["topic"], 0) + 1

    summary = {}
    for conf, scores in by_confidence.items():
        if scores:
            avg_accuracy = round((sum(scores) / (2 * len(scores))) * 100, 1)
            summary[conf] = {"count": len(scores), "avg_accuracy": avg_accuracy}

    return {"by_confidence": summary, "overconfident_topics": overconfident_topics}


def log_lab_reflection(topic: str, lab_brief: str, reflection: dict, ai_response: str):
    conn = get_conn()
    topic_id = _get_or_create_topic_id(conn, topic)
    conn.execute(
        """INSERT INTO lab_reflections (topic_id, lab_brief, reflection, ai_response, timestamp)
           VALUES (?, ?, ?, ?, ?)""",
        (topic_id, lab_brief, json.dumps(reflection), ai_response, date.today().isoformat()),
    )
    conn.commit()
    conn.close()


def get_lab_history(limit: int = 10):
    conn = get_conn()
    rows = conn.execute(
        """SELECT topics.name AS topic, lr.lab_brief, lr.reflection, lr.ai_response, lr.timestamp
           FROM lab_reflections lr JOIN topics ON topics.id = lr.topic_id
           ORDER BY lr.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def log_lab_flag(topic: str, mode: str, brief: str, note: str):
    """Record a mistake the student caught in a generated lab/scenario/grade."""
    conn = get_conn()
    topic_id = _get_or_create_topic_id(conn, topic)
    conn.execute(
        """INSERT INTO lab_flags (topic_id, mode, brief, note, timestamp)
           VALUES (?, ?, ?, ?, ?)""",
        (topic_id, mode, brief, note, date.today().isoformat()),
    )
    conn.commit()
    conn.close()


def get_known_pitfalls(topic: str, limit: int = 5):
    """
    Recent reported mistakes to warn the generators about: this topic's first, then the most
    recent from other topics (platform-level mistakes, like a command a switch model doesn't
    support, apply across topics). De-duplicated; at most `limit` entries.
    """
    conn = get_conn()
    topic_id = _get_or_create_topic_id(conn, topic)
    same = conn.execute(
        """SELECT topics.name AS topic, lf.note FROM lab_flags lf
           JOIN topics ON topics.id = lf.topic_id
           WHERE lf.topic_id = ? ORDER BY lf.id DESC LIMIT ?""",
        (topic_id, limit),
    ).fetchall()
    other = conn.execute(
        """SELECT topics.name AS topic, lf.note FROM lab_flags lf
           JOIN topics ON topics.id = lf.topic_id
           WHERE lf.topic_id != ? ORDER BY lf.id DESC LIMIT ?""",
        (topic_id, limit),
    ).fetchall()
    conn.close()

    seen, out = set(), []
    for r in list(same) + list(other):
        note = (r["note"] or "").strip()
        if note and note not in seen:
            seen.add(note)
            out.append(f"({r['topic']}) {note}")
        if len(out) >= limit:
            break
    return out


def get_flag_history(limit: int = 20):
    conn = get_conn()
    rows = conn.execute(
        """SELECT topics.name AS topic, lf.mode, lf.note, lf.timestamp
           FROM lab_flags lf JOIN topics ON topics.id = lf.topic_id
           ORDER BY lf.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def get_streak_info():
    """
    Current & longest study streaks, derived from days with any logged activity.
    No separate tracking table needed — it's inferred from session_log/mock_exam_log timestamps.
    """
    conn = get_conn()
    rows1 = conn.execute("SELECT DISTINCT timestamp FROM session_log").fetchall()
    rows2 = conn.execute("SELECT DISTINCT timestamp FROM mock_exam_log").fetchall()
    rows3 = conn.execute("SELECT DISTINCT timestamp FROM lab_flags").fetchall()  # flagging a lab is studying too
    conn.close()

    all_dates = sorted(
        {date.fromisoformat(r["timestamp"]) for r in rows1}
        | {date.fromisoformat(r["timestamp"]) for r in rows2}
        | {date.fromisoformat(r["timestamp"]) for r in rows3}
    )

    if not all_dates:
        return {"current_streak": 0, "longest_streak": 0, "studied_today": False}

    longest = 1
    run = 1
    for i in range(1, len(all_dates)):
        if all_dates[i] == all_dates[i - 1] + timedelta(days=1):
            run += 1
        else:
            run = 1
        longest = max(longest, run)

    today = date.today()
    studied_today = today in all_dates
    date_set = set(all_dates)
    cursor = today if studied_today else today - timedelta(days=1)
    current = 0
    while cursor in date_set:
        current += 1
        cursor -= timedelta(days=1)

    return {"current_streak": current, "longest_streak": longest, "studied_today": studied_today}


# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------

def export_backup(filepath: str):
    """Dumps the entire database (topics, progress, full session history, mock exams) to a JSON file."""
    conn = get_conn()
    data = {
        "schema_version": _get_schema_version(conn),
        "exported_at": datetime.now().isoformat(),
        "topics": [dict(r) for r in conn.execute("SELECT * FROM topics")],
        "topic_progress": [dict(r) for r in conn.execute(
            "SELECT topics.name AS topic, tp.* FROM topic_progress tp JOIN topics ON topics.id = tp.topic_id"
        )],
        "session_log": [dict(r) for r in conn.execute(
            "SELECT topics.name AS topic, sl.* FROM session_log sl JOIN topics ON topics.id = sl.topic_id"
        )],
        "mock_exam_log": [dict(r) for r in conn.execute("SELECT * FROM mock_exam_log")],
        "lab_reflections": [dict(r) for r in conn.execute(
            "SELECT topics.name AS topic, lr.* FROM lab_reflections lr JOIN topics ON topics.id = lr.topic_id"
        )],
        "lab_flags": [dict(r) for r in conn.execute(
            "SELECT topics.name AS topic, lf.* FROM lab_flags lf JOIN topics ON topics.id = lf.topic_id"
        )],
    }
    conn.close()
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def import_backup(filepath: str):
    """
    Restores a full backup created by export_backup(). This REPLACES all current
    data — the caller (main.py) is responsible for confirming with the user first.
    """
    with open(filepath) as f:
        data = json.load(f)

    conn = get_conn()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM session_log")
    conn.execute("DELETE FROM topic_progress")
    conn.execute("DELETE FROM mock_exam_log")
    conn.execute("DELETE FROM lab_reflections")
    conn.execute("DELETE FROM lab_flags")
    conn.execute("DELETE FROM topics")
    conn.commit()

    for t in data.get("topics", []):
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (t["id"], t["name"]))

    for tp in data.get("topic_progress", []):
        topic_id = conn.execute("SELECT id FROM topics WHERE name = ?", (tp["topic"],)).fetchone()["id"]
        conn.execute(
            """INSERT INTO topic_progress (topic_id, ease, interval_days, reps, last_seen, next_due, attempts, correct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (topic_id, tp["ease"], tp["interval_days"], tp["reps"], tp["last_seen"],
             tp["next_due"], tp["attempts"], tp["correct"]),
        )

    for sl in data.get("session_log", []):
        topic_id = conn.execute("SELECT id FROM topics WHERE name = ?", (sl["topic"],)).fetchone()["id"]
        conn.execute(
            """INSERT INTO session_log (id, topic_id, question, your_answer, score, feedback, timestamp, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (sl["id"], topic_id, sl["question"], sl["your_answer"], sl["score"], sl["feedback"],
             sl["timestamp"], sl.get("confidence")),  # .get() — older backups won't have this key
        )

    for me in data.get("mock_exam_log", []):
        conn.execute(
            """INSERT INTO mock_exam_log (id, timestamp, total_questions, correct_count, partial_count,
               score_percent, elapsed_seconds, domain_breakdown)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (me["id"], me["timestamp"], me["total_questions"], me["correct_count"], me["partial_count"],
             me["score_percent"], me["elapsed_seconds"], me["domain_breakdown"]),
        )

    for lr in data.get("lab_reflections", []):  # .get() — older backups won't have this table
        topic_id = conn.execute("SELECT id FROM topics WHERE name = ?", (lr["topic"],)).fetchone()["id"]
        conn.execute(
            """INSERT INTO lab_reflections (id, topic_id, lab_brief, reflection, ai_response, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (lr["id"], topic_id, lr["lab_brief"], lr["reflection"], lr["ai_response"], lr["timestamp"]),
        )

    for lf in data.get("lab_flags", []):  # .get() -- older backups won't have this table
        topic_id = conn.execute("SELECT id FROM topics WHERE name = ?", (lf["topic"],)).fetchone()["id"]
        conn.execute(
            """INSERT INTO lab_flags (id, topic_id, mode, brief, note, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (lf["id"], topic_id, lf["mode"], lf["brief"], lf["note"], lf["timestamp"]),
        )

    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()

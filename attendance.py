#!/usr/bin/env python3
"""Offline SQLite attendance register; no server or third-party dependencies."""
import argparse
import csv
from datetime import date
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


STATUSES = ("present", "late", "absent", "excused")
SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0)
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    held_on TEXT NOT NULL,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0)
);
CREATE TABLE IF NOT EXISTS attendance (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
    person_id TEXT NOT NULL REFERENCES people(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('present','late','absent','excused')),
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (session_id, person_id)
);
"""


def nonblank(value):
    value = value.strip()
    if not value or len(value) > 160 or any(ord(char) < 32 for char in value):
        raise argparse.ArgumentTypeError("must be 1–160 printable characters")
    return value


def valid_day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def parser_for_cli():
    parser = argparse.ArgumentParser(
        description="Local-first attendance tracking using a private SQLite file"
    )
    parser.add_argument(
        "--db", type=Path,
        default=Path(os.environ.get("ATTENDANCE_DB", "attendance.sqlite3")),
        help="database path (default: ./attendance.sqlite3 or ATTENDANCE_DB)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create a private database")

    person = sub.add_parser("add-person", help="add a participant")
    person.add_argument("--id", required=True, type=nonblank)
    person.add_argument("--name", required=True, type=nonblank)

    session = sub.add_parser("add-session", help="create a session")
    session.add_argument("--id", required=True, type=nonblank)
    session.add_argument("--date", required=True, type=valid_day)
    session.add_argument("--title", required=True, type=nonblank)

    mark = sub.add_parser("mark", help="record or change one attendance status")
    mark.add_argument("--session", required=True, type=nonblank)
    mark.add_argument("--person", required=True, type=nonblank)
    mark.add_argument("--status", required=True, choices=STATUSES)
    mark.add_argument("--note", default="", help="optional local-only note")

    sub.add_parser("people", help="list participants")
    sub.add_parser("sessions", help="list sessions")

    report = sub.add_parser("report", help="print counts and participant statuses")
    report.add_argument("--session", required=True, type=nonblank)

    export = sub.add_parser("export", help="export a session roster to CSV")
    export.add_argument("--session", required=True, type=nonblank)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--overwrite", action="store_true")
    return parser


def open_database(path):
    if path.is_symlink() or path.is_dir():
        raise ValueError("database path must not be a symlink or directory")
    if not path.parent.is_dir():
        raise ValueError(f"database parent directory does not exist: {path.parent}")
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    # Files contain participant names; prevent access by other local users on
    # POSIX machines, including when opening a previously permissive database.
    if os.name == "posix":
        os.chmod(path, 0o600)
    with connection:
        connection.executescript(SCHEMA)
    return connection


def session_roster(connection, session_id):
    session = connection.execute(
        "SELECT id, held_on, title FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    rows = connection.execute(
        """SELECT people.id AS person_id, people.name,
                  COALESCE(attendance.status, 'unmarked') AS status,
                  COALESCE(attendance.note, '') AS note
           FROM people
           LEFT JOIN attendance ON attendance.person_id = people.id
                               AND attendance.session_id = ?
           ORDER BY people.name COLLATE NOCASE, people.id""",
        (session_id,),
    ).fetchall()
    return session, rows


def save_csv(connection, session_id, output, overwrite, db_path):
    session, rows = session_roster(connection, session_id)
    if output.is_symlink() or output.is_dir() or output.resolve() == db_path.resolve():
        raise ValueError("unsafe CSV destination")
    if output.exists() and not overwrite:
        raise ValueError(f"CSV file exists (pass --overwrite to replace): {output}")
    if not output.parent.is_dir():
        raise ValueError("CSV destination parent directory does not exist")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="",
            dir=output.parent, prefix=".attendance-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(["session_id", "date", "title", "person_id", "name",
                             "status", "note"])
            for row in rows:
                # Quote fields through csv.writer. These are local notes, not
                # trusted spreadsheet formulas; prefix dangerous initial chars.
                safe = [
                    "'" + str(value) if str(value).startswith(("=", "+", "-", "@"))
                    else value for value in
                    (session["id"], session["held_on"], session["title"],
                     row["person_id"], row["name"], row["status"], row["note"])
                ]
                writer.writerow(safe)
            stream.flush()
            os.fsync(stream.fileno())
        # A second check protects against accidental re-use of an existing
        # report path; this is not a cross-process overwrite lock.
        if output.exists() and not overwrite:
            raise ValueError(f"CSV file appeared during export: {output}")
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Exported {len(rows)} participants to {output}")


def execute(args, connection):
    if args.command == "init":
        print(f"Initialized {args.db}")
    elif args.command == "add-person":
        with connection:
            connection.execute(
                "INSERT INTO people(id, name) VALUES (?, ?)", (args.id, args.name)
            )
        print(f"Added participant {args.id}")
    elif args.command == "add-session":
        with connection:
            connection.execute(
                "INSERT INTO sessions(id, held_on, title) VALUES (?, ?, ?)",
                (args.id, args.date, args.title)
            )
        print(f"Created session {args.id}")
    elif args.command == "mark":
        # Reject orphan status values rather than silently inventing a person
        # or a session.
        if connection.execute("SELECT 1 FROM people WHERE id=?", (args.person,)).fetchone() is None:
            raise ValueError(f"unknown participant: {args.person}")
        if connection.execute("SELECT 1 FROM sessions WHERE id=?", (args.session,)).fetchone() is None:
            raise ValueError(f"unknown session: {args.session}")
        with connection:
            connection.execute(
                """INSERT INTO attendance(session_id, person_id, status, note)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(session_id, person_id) DO UPDATE
                   SET status=excluded.status, note=excluded.note""",
                (args.session, args.person, args.status, args.note),
            )
        print(f"Recorded {args.person}: {args.status}")
    elif args.command == "people":
        for row in connection.execute("SELECT id, name FROM people ORDER BY name, id"):
            print(f"{row['id']}\t{row['name']}")
    elif args.command == "sessions":
        for row in connection.execute(
            "SELECT id, held_on, title FROM sessions ORDER BY held_on DESC, id"
        ):
            print(f"{row['id']}\t{row['held_on']}\t{row['title']}")
    elif args.command == "report":
        session, rows = session_roster(connection, args.session)
        counts = {status: 0 for status in (*STATUSES, "unmarked")}
        print(f"{session['held_on']} | {session['title']} ({session['id']})")
        for row in rows:
            counts[row["status"]] += 1
            print(f"{row['person_id']}\t{row['name']}\t{row['status']}")
        print(" | ".join(f"{key}: {value}" for key, value in counts.items()))
    elif args.command == "export":
        save_csv(connection, args.session, args.output, args.overwrite, args.db)


def main(argv=None):
    parser = parser_for_cli()
    args = parser.parse_args(argv)
    try:
        connection = open_database(args.db)
        try:
            execute(args, connection)
        finally:
            connection.close()
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

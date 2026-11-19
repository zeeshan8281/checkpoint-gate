"""Bounded SQL execution. No candidate code is evaluated by Python."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

from .common import canonical

FUNCTIONS = {
    "count", "sum", "total", "avg", "min", "max", "abs", "round", "lower", "upper",
    "length", "coalesce", "ifnull", "nullif", "typeof", "date", "strftime",
    "row_number", "rank", "dense_rank", "like", "glob", "substr", "substring", "trim",
}


def _authorize(action, arg1, arg2, database, source):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class SQLiteTool:
    def __init__(self, path: Path, *, timeout_s=0.25, max_rows=100,
                 max_vm_steps=200_000, max_bytes=32_768):
        self.path = path
        self.timeout_s = timeout_s
        self.max_rows = max_rows
        self.max_vm_steps = max_vm_steps
        self.max_bytes = max_bytes

    def execute(self, sql: str) -> dict:
        if not isinstance(sql, str) or not sql.strip() or len(sql.encode()) > 8192:
            return {"error": "invalid_sql_size"}
        started = time.monotonic()
        con = sqlite3.connect(self.path.absolute().as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            con.enable_load_extension(False)
            con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, self.max_bytes)
            con.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 8192)
            con.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 32)
            con.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 40)
            con.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 10)
            con.execute("PRAGMA query_only=ON")
            con.set_authorizer(_authorize)
            ticks = 0

            def progress():
                nonlocal ticks
                ticks += 100
                return int(ticks > self.max_vm_steps or
                           time.monotonic() - started > self.timeout_s)

            con.set_progress_handler(progress, 100)
            cursor = con.execute(sql)
            rows = [list(row) for row in cursor.fetchmany(self.max_rows + 1)]
            if len(rows) > self.max_rows:
                return {"error": "row_limit", "limit": self.max_rows}
            result = {"columns": [c[0] for c in cursor.description], "rows": rows}
            if len(canonical(result).encode()) > self.max_bytes:
                return {"error": "result_byte_limit"}
            return result
        except (sqlite3.Error, ValueError, TypeError) as exc:
            # Error text is useful feedback; database contains only generated public data.
            return {"error": "sql_error", "detail": str(exc)[:240]}
        finally:
            con.close()


def _cell(value):
    if value is None:
        return ("null", None)
    if type(value) is bool:
        return ("bool", value)
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite result")
        # SQL integers and exactly equivalent floats compare equal; strings do not.
        return ("number", value)
    if isinstance(value, str):
        return ("text", value)
    raise ValueError("Unsupported cell")


def equivalent(actual, expected, ordered: bool) -> bool:
    try:
        if not isinstance(actual, list) or not all(isinstance(r, list) for r in actual):
            return False
        a = [tuple(_cell(x) for x in row) for row in actual]
        b = [tuple(_cell(x) for x in row) for row in expected]
        return a == b if ordered else Counter(a) == Counter(b)
    except (ValueError, TypeError, OverflowError):
        return False


def parse_action(text: str, *, allow_outer_fence=False) -> dict:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    if len(text.encode()) > 32_768:
        raise ValueError("Action too large")
    if allow_outer_fence:
        fence = re.fullmatch(r"```(?:json)?[ \t]*\n(.*?)\n```", text.strip(), flags=re.DOTALL)
        if fence:
            text = fence.group(1)
    try:
        action = json.loads(text, object_pairs_hook=unique_keys,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite")))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Expected one JSON object") from exc
    if not isinstance(action, dict):
        raise ValueError("Expected an object")
    if set(action) == {"sql"} and isinstance(action["sql"], str):
        return action
    if set(action) == {"answer"} and isinstance(action["answer"], list):
        return action
    raise ValueError('Use exactly {"sql":"..."} or {"answer":[[...]]}')

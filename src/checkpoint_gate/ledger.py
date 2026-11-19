"""Conservative reservations, persisted BEFORE dispatch; no automatic retry."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from .common import canonical, digest


class StopCampaign(RuntimeError):
    """No more remote operations may be dispatched."""


class Ledger:
    def __init__(self, path: Path, config: dict):
        rates, caps = config["rates_per_million"], config["token_caps"]
        if set(rates) != {"train", "prefill", "sample"} or set(caps) != set(rates):
            raise ValueError("Require all three token categories")
        for value in rates.values():
            rate = Decimal(str(value))
            if not rate.is_finite() or rate <= 0:
                raise ValueError("Rates must be finite and positive")
        if any(type(n) is not int or n <= 0 for n in caps.values()):
            raise ValueError("Token ceilings must be positive integers")
        cap = Decimal(str(config["compute_cap_usd"]))
        if not cap.is_finite() or cap <= 0:
            raise ValueError("Compute ceiling must be finite and positive")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.config = path, config
        with self.connection() as con:
            con.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ops(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
                    reserved INTEGER NOT NULL, units TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    receipt TEXT, created REAL NOT NULL
                );
            """)
            con.execute("BEGIN IMMEDIATE")
            old = con.execute("SELECT value FROM meta WHERE key='config'").fetchone()
            if old and old[0] != canonical(config):
                raise StopCampaign("Cannot change a campaign's frozen budget/config")
            con.execute("INSERT OR IGNORE INTO meta VALUES('config',?)", (canonical(config),))
            con.execute("INSERT OR IGNORE INTO meta VALUES('deadline',?)",
                        (str(time.time() + config["max_seconds"]),))
            # A process could have died after dispatch but before saving its receipt.
            con.execute("UPDATE ops SET state='unknown' WHERE state='reserved'")
            con.commit()

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        con.execute("PRAGMA synchronous=FULL")
        try:
            yield con
        finally:
            con.close()

    def price(self, units: dict) -> int:
        # Nanodollars avoid binary floating point overspending at the boundary.
        total = Decimal(0)
        for kind, n in units.items():
            if kind not in self.config["rates_per_million"] or type(n) is not int or n < 0:
                raise ValueError("Invalid token reservation")
            total += Decimal(str(self.config["rates_per_million"][kind])) * n * 1000
        return int(total.to_integral_value(rounding=ROUND_CEILING))

    def reserve(self, op_id: str, kind: str, units: dict, payload) -> None:
        amount = self.price(units)
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM ops WHERE id=?", (op_id,)).fetchone():
                raise StopCampaign(f"Operation already exists; do not replay: {op_id}")
            if con.execute("SELECT 1 FROM ops WHERE state IN ('reserved','unknown')").fetchone():
                raise StopCampaign("Pending or unknown remote operation requires reconciliation")
            deadline = float(con.execute("SELECT value FROM meta WHERE key='deadline'").fetchone()[0])
            if time.time() >= deadline:
                raise StopCampaign("Campaign wall-clock deadline reached")
            used = con.execute("SELECT COALESCE(SUM(reserved),0) FROM ops").fetchone()[0]
            cap = int(Decimal(str(self.config["compute_cap_usd"])) * 1_000_000_000)
            if used + amount > cap:
                raise StopCampaign("Compute reservation ceiling reached")
            totals = {k: 0 for k in self.config["token_caps"]}
            for row in con.execute("SELECT units FROM ops"):
                import json
                for k, n in json.loads(row[0]).items():
                    totals[k] += n
            for k, n in units.items():
                if totals[k] + n > self.config["token_caps"][k]:
                    raise StopCampaign(f"{k} token ceiling reached")
            con.execute("INSERT INTO ops VALUES(?,?,?,?,?,?,?,?)",
                        (op_id, kind, "reserved", amount, canonical(units), digest(payload), None, time.time()))
            con.commit()

    def finish(self, op_id: str, receipt, *, unknown=False) -> None:
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            cursor = con.execute("UPDATE ops SET state=?,receipt=? WHERE id=? AND state='reserved'",
                                 ("unknown" if unknown else "committed", canonical(receipt), op_id))
            if cursor.rowcount != 1:
                raise StopCampaign("Invalid reservation transition")
            con.commit()

    def dispatch(self, op_id: str, kind: str, units: dict, payload, fn):
        self.reserve(op_id, kind, units, payload)
        try:
            result = fn()
        except BaseException as exc:
            self.finish(op_id, {"exception_type": type(exc).__name__}, unknown=True)
            raise
        self.finish(op_id, {"acknowledged": True})
        return result

    def snapshot(self) -> dict:
        with self.connection() as con:
            rows = con.execute("SELECT state,COUNT(*),SUM(reserved) FROM ops GROUP BY state").fetchall()
        return {
            "states": {state: {"operations": n, "reserved_usd": cost / 1e9} for state, n, cost in rows},
            "conservative_reserved_usd": sum(r[2] for r in rows) / 1e9,
            "compute_cap_usd": self.config["compute_cap_usd"],
            "billing_note": "Upper reservations at configured rates, NOT an invoice. Successful reservations are not released.",
        }

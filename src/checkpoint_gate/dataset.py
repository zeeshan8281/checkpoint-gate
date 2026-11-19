"""Generated schema/query families, with gold files kept outside model inputs."""
from __future__ import annotations

import random
import sqlite3
from pathlib import Path

from .common import canonical, digest, file_hash, read_json, write_json
from .verifier import SQLiteTool

FAMILIES = {
    "train": ["filter", "group_sum", "missing_child", "join_filter"],
    "dev": ["conditional_count", "group_having", "top_ties", "correlated_exists"],
    "test": ["latest_window", "relational_division", "anti_null", "distinct_pairs"],
}
VOCAB = {
    "train": ("customers", "orders", "region", "amount", "status"),
    "dev": ("teams", "tickets", "zone", "points", "stage"),
    "test": ("laboratories", "readings", "sector", "value", "label"),
}


def _construct(path: Path, split: str, family: str, seed: int):
    rng = random.Random(seed)
    base = VOCAB[split]
    suffix = rng.randrange(100, 999)
    p, c, group, value, state = [f"{x}_{suffix}" for x in base]
    schema = (
        f"CREATE TABLE {p}(id INTEGER PRIMARY KEY, name TEXT, {group} TEXT);\n"
        f"CREATE TABLE {c}(id INTEGER PRIMARY KEY, parent_id INTEGER, {value} INTEGER, "
        f"{state} TEXT, tick INTEGER);"
    )
    parents = [(i, f"item-{i:02}", rng.choice(["north", "south", None])) for i in range(1, 13)]
    # Parent 12 has no children; NULL values and duplicate logical events are intentional.
    children = [(i, rng.choice(list(range(1, 12)) + [None]),
                 rng.choice([None, 0, 2, 5, 10, 20, 35]),
                 rng.choice(["open", "closed", "hold", None]), rng.randint(1, 8))
                for i in range(1, 49)]
    children += [(49, 1, 10, "open", 9), (50, 1, 10, "open", 9),
                 (51, 1, 5, "closed", 10), (52, None, 35, "closed", 10)]
    con = sqlite3.connect(path)
    con.executescript(schema)
    con.executemany(f"INSERT INTO {p} VALUES(?,?,?)", parents)
    con.executemany(f"INSERT INTO {c} VALUES(?,?,?,?,?)", children)
    con.commit()
    threshold = rng.choice([5, 10, 20])
    templates = {
        "filter": (
            f"Return id and {value} from {c} where {value} > {threshold}. Sort by id.",
            f"SELECT id,{value} FROM {c} WHERE {value}>{threshold} ORDER BY id"),
        "group_sum": (
            f"For each {state} in {c}, return {state} and the sum of {value}. Order does not matter.",
            f"SELECT {state},SUM({value}) FROM {c} GROUP BY {state}"),
        "missing_child": (
            f"Return parent id and name for rows in {p} with no matching {c}. Sort by parent id.",
            f"SELECT p.id,p.name FROM {p} p LEFT JOIN {c} c ON c.parent_id=p.id WHERE c.id IS NULL ORDER BY p.id"),
        "join_filter": (
            f"Return parent name and child {value} for children labeled open whose parent {group} is north. Keep duplicates. Order does not matter.",
            f"SELECT p.name,c.{value} FROM {p} p JOIN {c} c ON p.id=c.parent_id WHERE p.{group}='north' AND c.{state}='open'"),
        "conditional_count": (
            f"For every parent in {p}, return its id and count of open children (including zero). Sort by parent id.",
            f"SELECT p.id,SUM(CASE WHEN c.{state}='open' THEN 1 ELSE 0 END) FROM {p} p LEFT JOIN {c} c ON p.id=c.parent_id GROUP BY p.id ORDER BY p.id"),
        "group_having": (
            f"Return non-NULL parent_id and total {value} from {c} for groups whose total exceeds {threshold * 3}. Sort by parent_id.",
            f"SELECT parent_id,SUM({value}) FROM {c} WHERE parent_id IS NOT NULL GROUP BY parent_id HAVING SUM({value})>{threshold * 3} ORDER BY parent_id"),
        "top_ties": (
            f"Return id and {value} of all rows tied for the maximum {value} in {c}. Sort by id.",
            f"SELECT id,{value} FROM {c} WHERE {value}=(SELECT MAX({value}) FROM {c}) ORDER BY id"),
        "correlated_exists": (
            f"Return id and name of parents with at least one closed child having {value}>{threshold}. Sort by parent id.",
            f"SELECT p.id,p.name FROM {p} p WHERE EXISTS(SELECT 1 FROM {c} c WHERE c.parent_id=p.id AND c.{state}='closed' AND c.{value}>{threshold}) ORDER BY p.id"),
        "latest_window": (
            f"For each non-NULL parent_id in {c}, return parent_id, id, and {value} of its latest row by tick; break ties with the largest id. Sort by parent_id.",
            f"SELECT parent_id,id,{value} FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY parent_id ORDER BY tick DESC,id DESC) AS rn FROM {c} WHERE parent_id IS NOT NULL) WHERE rn=1 ORDER BY parent_id"),
        "relational_division": (
            f"Return id and name of parents having both an open and a closed child in {c}. Sort by parent id.",
            f"SELECT p.id,p.name FROM {p} p WHERE EXISTS(SELECT 1 FROM {c} a WHERE a.parent_id=p.id AND a.{state}='open') AND EXISTS(SELECT 1 FROM {c} b WHERE b.parent_id=p.id AND b.{state}='closed') ORDER BY p.id"),
        "anti_null": (
            f"Return id and name of parents with no closed child in {c}. Include parents with no children. NULL parent_id does not match any parent. Sort by parent id.",
            f"SELECT p.id,p.name FROM {p} p WHERE NOT EXISTS(SELECT 1 FROM {c} c WHERE c.parent_id=p.id AND c.{state}='closed') ORDER BY p.id"),
        "distinct_pairs": (
            f"Return distinct parent {group} and child {state} pairs for matching parents and children where {value}>={threshold}. Keep NULL groups and labels. Order does not matter.",
            f"SELECT DISTINCT p.{group},c.{state} FROM {p} p JOIN {c} c ON p.id=c.parent_id WHERE c.{value}>={threshold}"),
    }
    question, sql = templates[family]
    expected = [list(row) for row in con.execute(sql)]
    con.close()
    checked = SQLiteTool(path).execute(sql)
    if checked.get("rows") != expected:
        raise RuntimeError(f"Verifier disagrees with generator: {family}: {checked}")
    return schema, question, sql, expected, "Order does not matter" not in question


def generate(root: Path, *, per_family=50, seed=20261119) -> dict:
    if root.exists():
        raise FileExistsError(f"Refusing to replace a frozen dataset: {root}")
    if per_family < 2 or per_family % 2:
        raise ValueError("per_family must be positive and even for balanced fault strata")
    root.mkdir(parents=True)
    (root / "databases").mkdir()
    (root / "private").mkdir(mode=0o700)
    tasks, gold, files = [], {}, {}
    for split_idx, (split, families) in enumerate(FAMILIES.items()):
        for family_idx, family in enumerate(families):
            for i in range(per_family):
                task_id = f"{split}-{family}-{i:04}"
                db = root / "databases" / f"{task_id}.sqlite"
                task_seed = seed + split_idx * 1_000_000 + family_idx * 10_000 + i
                schema, question, sql, rows, ordered = _construct(db, split, family, task_seed)
                tasks.append({
                    "id": task_id, "split": split, "family": family, "schema": schema,
                    "question": question, "ordered": ordered,
                    "fault": "transient_first_call" if i % 2 else "none",
                    "db": f"databases/{task_id}.sqlite", "db_sha256": file_hash(db),
                })
                gold[task_id] = {"sql": sql, "rows": rows}
                files[str(db.relative_to(root))] = file_hash(db)
    write_json(root / "tasks.json", tasks)
    write_json(root / "private" / "gold.json", gold)
    (root / "private" / "gold.json").chmod(0o600)
    files["tasks.json"] = file_hash(root / "tasks.json")
    files["private/gold.json"] = file_hash(root / "private" / "gold.json")
    manifest = {
        "version": 1, "seed": seed, "per_family": per_family, "families": FAMILIES,
        "tasks": len(tasks), "files": files,
        "limitation": "Synthetic two-table schemas; query families AND schema vocabulary held out. Not a real-world SQL benchmark.",
    }
    manifest["sha256"] = digest(manifest)
    write_json(root / "manifest.json", manifest)
    return manifest


def load(root: Path, split: str | None = None):
    manifest = read_json(root / "manifest.json")
    checksum = manifest.pop("sha256")
    if digest(manifest) != checksum:
        raise ValueError("Manifest was modified")
    manifest["sha256"] = checksum
    for name, expected in manifest["files"].items():
        if file_hash(root / name) != expected:
            raise ValueError(f"Frozen input changed: {name}")
    tasks = read_json(root / "tasks.json")
    return [t for t in tasks if split is None or t["split"] == split], read_json(root / "private/gold.json"), manifest

"""Saved queries, kept like Navicat's: one .sql file per query, grouped by connection and database.

Files live in ~/.config/dbprofile/queries/<connection id>/<database>/<query name>.sql
(names are percent-encoded so any database or query name is a valid file name).
"""
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, unquote

from .config import CONFIG_DIR

QUERIES_DIR = os.path.join(CONFIG_DIR, "queries")
EXT = ".sql"


@dataclass
class SavedQuery:
    name: str
    modified: datetime
    size: int


def _encode(name: str) -> str:
    # quote() leaves "." alone; encode a leading one so "." / ".." can't escape the folder
    encoded = quote(name, safe=" ")
    return "%2E" + encoded[1:] if encoded.startswith(".") else encoded


def _db_dir(conn_id: str, database: str) -> str:
    return os.path.join(QUERIES_DIR, conn_id, _encode(database))


def query_path(conn_id: str, database: str, name: str) -> str:
    return os.path.join(_db_dir(conn_id, database), _encode(name) + EXT)


def validate_name(name: str) -> str | None:
    """Return an error message for an unusable query name, or None."""
    if not name.strip():
        return "The query name cannot be empty."
    if len(_encode(name.strip()).encode()) + len(EXT) > 255:
        return "The query name is too long."
    return None


def list_queries(conn_id: str, database: str) -> list[SavedQuery]:
    folder = _db_dir(conn_id, database)
    try:
        entries = list(os.scandir(folder))
    except FileNotFoundError:
        return []
    result = []
    for e in entries:
        if e.is_file() and e.name.endswith(EXT):
            st = e.stat()
            result.append(SavedQuery(unquote(e.name[:-len(EXT)]), datetime.fromtimestamp(st.st_mtime), st.st_size))
    return sorted(result, key=lambda q: q.name.lower())


def exists(conn_id: str, database: str, name: str) -> bool:
    return os.path.isfile(query_path(conn_id, database, name))


def load(conn_id: str, database: str, name: str) -> str:
    with open(query_path(conn_id, database, name), encoding="utf-8") as f:
        return f.read()


def save(conn_id: str, database: str, name: str, sql: str) -> None:
    path = query_path(conn_id, database, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(sql)
    os.replace(tmp, path)


def rename(conn_id: str, database: str, old: str, new: str) -> None:
    if new != old and exists(conn_id, database, new):
        raise FileExistsError(f"A query named “{new}” already exists.")
    os.replace(query_path(conn_id, database, old), query_path(conn_id, database, new))


def delete(conn_id: str, database: str, name: str) -> None:
    os.remove(query_path(conn_id, database, name))


def delete_connection(conn_id: str) -> None:
    """Remove every saved query of a deleted connection."""
    shutil.rmtree(os.path.join(QUERIES_DIR, conn_id), ignore_errors=True)


def count_for_connection(conn_id: str) -> int:
    root = os.path.join(QUERIES_DIR, conn_id)
    return sum(f.endswith(EXT) for _, _, files in os.walk(root) for f in files)

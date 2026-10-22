"""Thin layer over PyMySQL: connecting, splitting and running SQL."""
import time
from dataclasses import dataclass

import pymysql

from .config import ConnectionConfig

MAX_FETCH_ROWS = 10000


def connect(cfg: ConnectionConfig, database: str | None = None):
    return pymysql.connect(
        host=cfg.host,
        port=int(cfg.port),
        user=cfg.user,
        password=cfg.password,
        database=database or cfg.database or None,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=10,
    )


def quote_ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


@dataclass
class ResultSet:
    statement: str
    columns: list[str] | None  # None for statements that return no rows
    rows: list[tuple]
    rowcount: int
    elapsed: float
    truncated: bool = False


def split_statements(sql: str) -> list[str]:
    """Split a script on ';', ignoring semicolons in quotes and comments."""
    statements, buf = [], []
    i, n = 0, len(sql)
    quote = None
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if quote:
            buf.append(ch)
            if ch == "\\" and quote != "`" and nxt:
                buf.append(nxt)
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
        elif ch == "#" or (ch == "-" and nxt == "-" and (i + 2 >= n or sql[i + 2] in " \t\r\n")):
            end = sql.find("\n", i)
            end = n if end == -1 else end
            buf.append(sql[i:end])
            i = end
            continue
        elif ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            end = n if end == -1 else end + 2
            buf.append(sql[i:end])
            i = end
            continue
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    stmt = "".join(buf).strip()
    if stmt:
        statements.append(stmt)
    return statements


def execute(conn, statement: str, args=None, max_rows: int = MAX_FETCH_ROWS) -> ResultSet:
    conn.ping(reconnect=True)
    start = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(statement, args)
        if cur.description:
            columns = [d[0] for d in cur.description]
            rows = list(cur.fetchmany(max_rows))
            truncated = cur.fetchone() is not None
            # Drain any remaining rows so the connection stays usable.
            while truncated and cur.fetchmany(10000):
                pass
            rowcount = len(rows)
        else:
            columns, rows, truncated = None, [], False
            rowcount = cur.rowcount
    return ResultSet(statement, columns, rows, rowcount, time.perf_counter() - start, truncated)


def run_script(conn, sql: str) -> list[ResultSet | Exception]:
    """Run each statement; stop at the first error, which is returned in the list."""
    results = []
    for stmt in split_statements(sql):
        try:
            results.append(execute(conn, stmt))
        except Exception as e:  # noqa: BLE001 - surface any driver error to the UI
            e.statement = stmt
            results.append(e)
            break
    return results


def current_database(conn) -> str | None:
    return execute(conn, "SELECT DATABASE()").rows[0][0]


def list_databases(conn) -> list[str]:
    return [r[0] for r in execute(conn, "SHOW DATABASES").rows]


def list_tables(conn, database: str) -> list[tuple[str, str]]:
    """Return [(name, 'BASE TABLE' | 'VIEW'), ...]."""
    rs = execute(conn, f"SHOW FULL TABLES FROM {quote_ident(database)}")
    return [(r[0], r[1]) for r in rs.rows]


def primary_key(conn, database: str, table: str) -> list[str]:
    rs = execute(
        conn,
        "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND CONSTRAINT_NAME='PRIMARY' "
        "ORDER BY ORDINAL_POSITION",
        (database, table),
    )
    return [r[0] for r in rs.rows]

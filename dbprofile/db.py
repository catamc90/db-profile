"""Thin layer over PyMySQL: connecting, splitting and running SQL."""
import os
import re
import time
from dataclasses import dataclass

import pymysql

from .config import ConnectionConfig

MAX_FETCH_ROWS = 10000


def connect(cfg: ConnectionConfig, database: str | None = None):
    options = dict(host=cfg.host, port=int(cfg.port), user=cfg.user, password=cfg.password,
                   database=database or cfg.database or None, charset="utf8mb4", autocommit=True,
                   connect_timeout=10, ssl=ssl_context(cfg))
    if cfg.ssh_enabled:
        return _TunneledConnection(cfg, **options)
    return pymysql.connect(**options)


def ssl_context(cfg: ConnectionConfig):
    """The SSLContext for a connection with SSL enabled, or None."""
    if not cfg.ssl_enabled:
        return None
    import ssl
    verify = cfg.ssl_mode in ("verify_ca", "verify_identity")
    ctx = ssl.create_default_context(cafile=os.path.expanduser(cfg.ssl_ca) if cfg.ssl_ca else None)
    ctx.check_hostname = cfg.ssl_mode == "verify_identity"
    ctx.verify_mode = ssl.CERT_REQUIRED if verify else ssl.CERT_NONE
    if cfg.ssl_cert:
        ctx.load_cert_chain(os.path.expanduser(cfg.ssl_cert),
                            os.path.expanduser(cfg.ssl_key) if cfg.ssl_key else None)
    return ctx


class _TunneledConnection(pymysql.connections.Connection):
    """A MySQL connection whose socket goes through the connection's SSH tunnel.

    The host stays the real MySQL host, so SSL host name checks still verify the right name,
    and reconnects (ping(reconnect=True)) go through the tunnel again.
    """

    def __init__(self, cfg, **options):
        self._tunnel_cfg = cfg
        super().__init__(defer_connect=True, **options)
        self.connect()

    def connect(self, sock=None):
        if sock is None:
            from . import ssh_tunnel
            sock = ssh_tunnel.get_tunnel(self._tunnel_cfg).open_socket(self.connect_timeout)
        super().connect(sock)


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
    types: list[str] | None = None  # base type of each column, e.g. "int", "varchar", "set"


# MySQL protocol type codes -> type names, as shown under the column names in result grids
_TYPE_NAMES = {0: "decimal", 1: "tinyint", 2: "smallint", 3: "int", 4: "float", 5: "double", 6: "null",
               7: "timestamp", 8: "bigint", 9: "mediumint", 10: "date", 11: "time", 12: "datetime", 13: "year",
               14: "date", 16: "bit", 245: "json", 246: "decimal", 247: "enum", 248: "set", 255: "geometry"}
_SET_FLAG, _ENUM_FLAG, _BINARY_CHARSET = 2048, 256, 63


def column_type(field) -> str:
    """Base type of a result column from its protocol metadata (pymysql FieldDescriptorPacket)."""
    code, binary = field.type_code, field.charsetnr == _BINARY_CHARSET
    if code in (249, 250, 251, 252):  # tiny/medium/long/plain BLOB and TEXT share these codes
        return "blob" if binary else "text"
    if code in (15, 253, 254):  # VARCHAR, VAR_STRING, STRING (CHAR, ENUM and SET arrive as STRING)
        if field.flags & _SET_FLAG:
            return "set"
        if field.flags & _ENUM_FLAG:
            return "enum"
        if code == 254:
            return "binary" if binary else "char"
        return "varbinary" if binary else "varchar"
    return _TYPE_NAMES.get(code, "")


DELIMITER_RE = re.compile(r"[ \t]*DELIMITER[ \t]+(\S+)[ \t]*(?:\r?\n|$)", re.IGNORECASE)
TRAILING_COMMENT_RE = re.compile(r"[ \t]*((?:--[ \t]|#)[^\n]*|--$)")


@dataclass
class ScriptPart:
    """One piece of a script: a statement, or a ``DELIMITER`` line (then ``sql`` is the new delimiter)."""
    sql: str
    delimiter: str | None = None  # delimiter that ended the statement; None at the end of the script
    comment: str = ""  # a comment on the same line after the delimiter, e.g. "SELECT 1; -- note"
    is_delimiter_line: bool = False


def parse_script(sql: str) -> list[ScriptPart]:
    """Split a script into statements and DELIMITER lines.

    Delimiters inside quotes and comments are ignored, and mysql-client style
    ``DELIMITER $$`` lines are honoured so routines with BEGIN ... END bodies work.
    """
    parts, buf = [], []
    delimiter = ";"
    i, n = 0, len(sql)
    quote = None
    line_start = True

    def flush(ended_by=None):
        stmt = "".join(buf).strip()
        if stmt:
            parts.append(ScriptPart(stmt, ended_by))
        buf.clear()
        return bool(stmt)

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
            i += 1
            continue
        if line_start:
            m = DELIMITER_RE.match(sql, i)
            if m:
                flush()
                delimiter = m.group(1)
                parts.append(ScriptPart(delimiter, is_delimiter_line=True))
                i = m.end()
                continue
        line_start = ch == "\n"
        if ch in ("'", '"', "`"):
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
        elif sql.startswith(delimiter, i):
            i += len(delimiter)
            if flush(delimiter):
                # Keep "stmt; -- note" together instead of moving the note to the next statement.
                m = TRAILING_COMMENT_RE.match(sql, i)
                if m:
                    parts[-1].comment = m.group(1)
                    i = m.end(1)
            continue
        else:
            buf.append(ch)
        i += 1
    flush()
    return parts


def split_statements(sql: str) -> list[str]:
    """The statements of a script, without delimiters and DELIMITER lines."""
    return [p.sql for p in parse_script(sql) if not p.is_delimiter_line]


def estimated_rows(conn, database: str, table: str) -> int | None:
    """The server's quick row estimate (exact for MyISAM, approximate for InnoDB)."""
    rs = execute(conn, "SELECT TABLE_ROWS FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                 (database, table))
    return rs.rows[0][0] if rs.rows and rs.rows[0][0] is not None else None


def _read_result(cur, statement, start, max_rows) -> ResultSet:
    types = None
    if cur.description:
        columns = [d[0] for d in cur.description]
        fields = getattr(getattr(cur, "_result", None), "fields", None) or []
        if len(fields) == len(columns):
            types = [column_type(f) for f in fields]
        rows = list(cur.fetchmany(max_rows))
        truncated = cur.fetchone() is not None
        # Drain any remaining rows so the connection stays usable.
        while truncated and cur.fetchmany(10000):
            pass
        rowcount = len(rows)
    else:
        columns, rows, truncated = None, [], False
        rowcount = cur.rowcount
    return ResultSet(statement, columns, rows, rowcount, time.perf_counter() - start, truncated, types)


def execute(conn, statement: str, args=None, max_rows: int = MAX_FETCH_ROWS) -> ResultSet:
    conn.ping(reconnect=True)
    start = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(statement, args)
        result = _read_result(cur, statement, start, max_rows)
        while cur.nextset():  # discard extra result sets (e.g. from CALL)
            pass
    return result


def execute_all(conn, statement: str, max_rows: int = MAX_FETCH_ROWS) -> list[ResultSet]:
    """Execute one statement and return every result set it produces (CALL can return several)."""
    conn.ping(reconnect=True)
    start = time.perf_counter()
    results = []
    with conn.cursor() as cur:
        cur.execute(statement)
        while True:
            results.append(_read_result(cur, statement, start, max_rows))
            if not cur.nextset():
                break
            start = time.perf_counter()
    # A CALL ends with an empty status result; only keep it when nothing returned rows.
    with_rows = [r for r in results if r.columns is not None]
    return with_rows or results[-1:]


def run_script(conn, sql: str) -> list[ResultSet | Exception]:
    """Run each statement; stop at the first error, which is returned in the list."""
    results = []
    for stmt in split_statements(sql):
        try:
            results.extend(execute_all(conn, stmt))
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


# --- functions / procedures ---------------------------------------------------
def list_routines(conn, database: str, details: bool = False):
    """Return [(name, 'FUNCTION' | 'PROCEDURE'), ...], or full detail rows when details=True."""
    cols = "ROUTINE_NAME, ROUTINE_TYPE"
    if details:
        cols += (", DTD_IDENTIFIER, IS_DETERMINISTIC, SECURITY_TYPE, DEFINER, CREATED, LAST_ALTERED, "
                 "ROUTINE_COMMENT")
    rs = execute(conn, f"SELECT {cols} FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = %s "
                       "AND ROUTINE_TYPE IN ('FUNCTION', 'PROCEDURE') ORDER BY ROUTINE_NAME", (database,))
    return [tuple(r) for r in rs.rows]


def routine_definition(conn, database: str, name: str, rtype: str) -> str:
    rs = execute(conn, f"SHOW CREATE {rtype} {quote_ident(database)}.{quote_ident(name)}")
    definition = rs.rows[0][2] if rs.rows else None
    if definition is None:
        raise PermissionError(f"Not allowed to see the definition of {rtype.lower()} {name}.")
    return definition


def routine_params(conn, database: str, name: str, rtype: str) -> list[tuple[str, str, str]]:
    """Return [(mode, name, data type), ...]; mode is IN / OUT / INOUT (functions: IN)."""
    rs = execute(
        conn,
        "SELECT PARAMETER_MODE, PARAMETER_NAME, DTD_IDENTIFIER FROM information_schema.PARAMETERS "
        "WHERE SPECIFIC_SCHEMA = %s AND SPECIFIC_NAME = %s AND ROUTINE_TYPE = %s AND ORDINAL_POSITION > 0 "
        "ORDER BY ORDINAL_POSITION",
        (database, name, rtype),
    )
    return [(mode or "IN", pname, dtd) for mode, pname, dtd in rs.rows]


# --- users ---------------------------------------------------------------------
def list_users(conn) -> list[dict]:
    """Rows of mysql.user as dicts (column set differs between MySQL and MariaDB versions)."""
    rs = execute(conn, "SELECT * FROM mysql.user ORDER BY User, Host")
    return [dict(zip(rs.columns, row)) for row in rs.rows]


def grantee(user: str, host: str) -> str:
    """The GRANTEE string used by information_schema privilege tables."""
    return "'" + user.replace("'", "''") + "'@'" + host.replace("'", "''") + "'"


def user_privileges(conn, user: str, host: str):
    """Return (global privileges, grant option, {database: privileges})."""
    g = grantee(user, host)
    rows = execute(conn, "SELECT PRIVILEGE_TYPE, IS_GRANTABLE FROM information_schema.USER_PRIVILEGES "
                         "WHERE GRANTEE = %s", (g,)).rows
    global_privs = {p for p, _ in rows if p != "USAGE"}
    grant_option = any(grantable == "YES" for _, grantable in rows)
    per_db: dict[str, set[str]] = {}
    for schema, priv in execute(conn, "SELECT TABLE_SCHEMA, PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES "
                                      "WHERE GRANTEE = %s", (g,)).rows:
        per_db.setdefault(schema, set()).add(priv)
    return global_privs, grant_option, per_db

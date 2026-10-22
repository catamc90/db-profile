"""Beautify SQL: reindent statements and upper-case keywords, like Navicat's "Beautify SQL"."""
import re

from . import db

try:
    import sqlparse
except ImportError:  # optional dependency; the Beautify action explains how to install it
    sqlparse = None

# Stored programs are kept as written: reformatting a BEGIN ... END body tends to make it harder to read.
COMPOUND_RE = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:DEFINER\s*=\s*\S+\s+)?(?:AGGREGATE\s+)?"
    r"(?:PROCEDURE|FUNCTION|TRIGGER|EVENT)\b", re.IGNORECASE)


def available() -> bool:
    return sqlparse is not None


def format_statement(sql: str) -> str:
    if COMPOUND_RE.match(sqlparse.format(sql, strip_comments=True)):
        return sql
    text = sqlparse.format(sql, reindent=True, keyword_case="upper", indent_width=4,
                           use_space_around_operators=True).strip()
    return _drop_blank_after_comments(_upper_word_operators(text))


def _upper_word_operators(sql: str) -> str:
    """sqlparse's keyword_case skips word operators such as LIKE and REGEXP."""
    tokens = sqlparse.parse(sql)[0].flatten() if sql else []
    return "".join(t.value.upper() if t.ttype in sqlparse.tokens.Operator.Comparison and t.value.isalpha()
                   else t.value for t in tokens)


def _drop_blank_after_comments(sql: str) -> str:
    """sqlparse puts an empty line after a full-line comment; keep the comment next to its code."""
    lines = sql.split("\n")
    keep = [line for i, line in enumerate(lines)
            if line.strip() or i == 0 or not lines[i - 1].lstrip().startswith(("--", "#"))]
    return "\n".join(keep)


def beautify(sql: str) -> str:
    """Format every statement of a script; DELIMITER lines and stored routines are left unchanged."""
    if sqlparse is None:
        raise RuntimeError("Beautify needs the sqlparse package: .venv/bin/pip install sqlparse")
    out = []
    for part in db.parse_script(sql):
        if part.is_delimiter_line:
            out.append(f"DELIMITER {part.sql}")
            continue
        text = format_statement(part.sql) + (part.delimiter or "")
        if part.comment:
            text += " " + part.comment
        out.append(text)
    # A blank line between statements, none around DELIMITER lines.
    result = ""
    for i, text in enumerate(out):
        if i:
            tight = text.startswith("DELIMITER ") or out[i - 1].startswith("DELIMITER ")
            result += "\n" if tight else "\n\n"
        result += text
    return result + ("\n" if sql.endswith("\n") and result else "")

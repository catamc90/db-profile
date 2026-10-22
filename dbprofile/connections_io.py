"""Import / export saved connections: Navicat .ncx files and DB Profile .json files.

Navicat stores connection passwords encrypted with fixed, publicly documented keys:
Navicat 12 and later use AES-128-CBC, Navicat 11 and older a Blowfish variant.
"""
import hashlib
import json
import warnings
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

from . import APP_NAME, APP_VERSION
from .config import ConnectionConfig

try:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, modes
    from cryptography.hazmat.primitives.ciphers.algorithms import AES
    with warnings.catch_warnings():  # Blowfish is deprecated, but Navicat 11 files need it
        warnings.simplefilter("ignore")
        try:  # moved to the "decrepit" module in cryptography 43
            from cryptography.hazmat.decrepit.ciphers.algorithms import Blowfish
        except ImportError:
            from cryptography.hazmat.primitives.ciphers.algorithms import Blowfish
except ImportError:  # passwords can't be decrypted, connections still import
    Cipher = None

AES_KEY = b"libcckeylibcckey"
AES_IV = b"libcciv libcciv "
BLOWFISH_KEY = hashlib.sha1(b"3DC5CA39").digest()
MYSQL_TYPES = {"MYSQL", "MARIADB"}
TYPE_NAMES = {"POSTGRESQL": "PostgreSQL", "ORACLE": "Oracle", "SQLITE": "SQLite", "SQLSERVER": "SQL Server",
              "MSSQL": "SQL Server", "MONGODB": "MongoDB", "REDIS": "Redis", "SNOWFLAKE": "Snowflake"}


# --- Navicat password encryption -------------------------------------------------------------
def _aes_decrypt(data: bytes) -> str:
    dec = Cipher(AES(AES_KEY), modes.CBC(AES_IV)).decryptor()
    padded = dec.update(data) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")


def _aes_encrypt(text: str) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(text.encode("utf-8")) + padder.finalize()
    enc = Cipher(AES(AES_KEY), modes.CBC(AES_IV)).encryptor()
    return enc.update(padded) + enc.finalize()


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _blowfish_decrypt(data: bytes) -> str:
    """Navicat 11: Blowfish-ECB with an XOR chain seeded by encrypting 0xFF * 8."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cipher = Cipher(Blowfish(BLOWFISH_KEY), modes.ECB())

    def ecb(block, encrypt):
        ctx = cipher.encryptor() if encrypt else cipher.decryptor()
        return ctx.update(block) + ctx.finalize()

    cv = ecb(b"\xff" * 8, True)
    out = b""
    full = len(data) - len(data) % 8
    for i in range(0, full, 8):
        block = data[i:i + 8]
        out += _xor(ecb(block, False), cv)
        cv = _xor(cv, block)
    if len(data) % 8:
        out += _xor(data[full:], ecb(cv, True))
    return out.decode("utf-8")


def navicat_decrypt(value: str) -> str | None:
    """Decrypt a Navicat password attribute. Returns None when it can't be decrypted."""
    if not value:
        return ""
    if Cipher is None:
        return None
    try:
        data = bytes.fromhex(value)
    except ValueError:
        return None
    for decrypt in (_aes_decrypt, _blowfish_decrypt):
        try:
            text = decrypt(data)
        except Exception:  # noqa: BLE001 - wrong algorithm for this value
            continue
        if text.isprintable():
            return text
    return None


def navicat_encrypt(text: str) -> str:
    return _aes_encrypt(text).hex().upper() if text else ""


# --- import --------------------------------------------------------------------------------
@dataclass
class ImportedConnection:
    config: ConnectionConfig
    source_type: str = "MYSQL"
    supported: bool = True
    password_ok: bool = True
    notes: list[str] = field(default_factory=list)


def _bool(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def read_ncx(path: str) -> list[ImportedConnection]:
    root = ET.parse(path).getroot()
    if root.tag != "Connections":
        raise ValueError("This is not a Navicat connections file (.ncx).")
    result = []
    for node in root.iter("Connection"):
        a = node.attrib
        ctype = (a.get("ConnType") or "MYSQL").upper()
        try:
            port = int(a.get("Port") or 3306)
        except ValueError:
            port = 3306
        cfg = ConnectionConfig(
            name=a.get("ConnectionName") or a.get("Host") or "Navicat connection",
            host=a.get("Host") or "127.0.0.1",
            port=port,
            user=a.get("UserName") or "",
            database=a.get("Database") or "",
            save_password=_bool(a.get("SavePassword", "true")),
        )
        item = ImportedConnection(cfg, ctype, supported=ctype in MYSQL_TYPES)
        if not item.supported:
            item.notes.append(f"{TYPE_NAMES.get(ctype, ctype.title())} connections are not supported")
        password = navicat_decrypt(a.get("Password", ""))
        if password is None:
            item.password_ok = False
            item.notes.append("Password could not be decrypted; enter it after importing")
            cfg.password = ""
        else:
            cfg.password = password
        if not cfg.save_password:
            cfg.password = ""
        if _bool(a.get("SSH")):
            item.notes.append(f"Uses an SSH tunnel via {a.get('SSH_Host', '')}, which is not supported yet")
        if _bool(a.get("HTTP")):
            item.notes.append("Uses an HTTP tunnel, which is not supported")
        if _bool(a.get("SSL")):
            item.notes.append("SSL settings are not imported")
        result.append(item)
    return result


def read_json(path: str) -> list[ImportedConnection]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("connections", []) if isinstance(data, dict) else data
    fields = ConnectionConfig.__dataclass_fields__
    result = []
    for row in rows:
        values = {k: v for k, v in row.items() if k in fields and k != "id"}
        result.append(ImportedConnection(ConnectionConfig(**values)))
    return result


def read_file(path: str) -> list[ImportedConnection]:
    if path.lower().endswith(".ncx"):
        return read_ncx(path)
    if path.lower().endswith(".json"):
        return read_json(path)
    try:
        return read_ncx(path)
    except ET.ParseError:
        return read_json(path)


# --- export --------------------------------------------------------------------------------
def write_ncx(path: str, connections: list[ConnectionConfig], include_passwords=True) -> None:
    """Write a Navicat-compatible .ncx file (File → Import Connections in Navicat)."""
    root = ET.Element("Connections", Ver="1.5")
    for c in connections:
        save = include_passwords and c.save_password and bool(c.password)
        ET.SubElement(root, "Connection", {
            "ConnectionName": c.name, "ProjectUUID": "", "ConnType": "MYSQL", "OraConnType": "",
            "ServiceProvider": "Default", "Host": c.host, "Port": str(c.port), "Database": c.database,
            "OraServiceNameType": "", "TNS": "", "MSSQLAuthenMode": "", "MSSQLAuthenWindowsDomain": "",
            "DatabaseFileName": "", "UserName": c.user,
            "Password": navicat_encrypt(c.password) if save else "",
            "SavePassword": "true" if save else "false", "SettingsSavePath": "", "SessionLimit": "0",
            "Encoding": "65001", "Keepalive": "false", "KeepaliveInterval": "240", "MySQLCharacterSet": "true",
            "Compression": "false", "AutoConnect": "false", "NamedPipe": "false", "NamedPipeSocket": "",
            "SSL": "false", "SSH": "false", "HTTP": "false",
        })
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def write_json(path: str, connections: list[ConnectionConfig], include_passwords=True) -> None:
    rows = []
    for c in connections:
        row = asdict(c)
        row.pop("id", None)
        if not include_passwords or not c.save_password:
            row["password"] = ""
        rows.append(row)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"app": APP_NAME, "version": APP_VERSION, "connections": rows}, f, indent=2)


def can_decrypt() -> bool:
    return Cipher is not None

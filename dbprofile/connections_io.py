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
    # Whether the file contained the secret, so an update keeps a saved one when it didn't
    has_password: bool = False
    has_ssh_secret: bool = False


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
        item.has_password = bool(cfg.password)
        if _bool(a.get("SSH")):
            _read_ssh(a, cfg, item)
        if _bool(a.get("SSL")):
            _read_ssl(a, cfg, item)
        if _bool(a.get("HTTP")):
            item.notes.append("Uses an HTTP tunnel, which is not supported")
        result.append(item)
    return result


def _is_windows_path(path: str) -> bool:
    return len(path) > 2 and path[1] == ":" or "\\" in path


def _read_ssh(a, cfg, item):
    cfg.ssh_enabled = True
    cfg.ssh_host = a.get("SSH_Host", "")
    try:
        cfg.ssh_port = int(a.get("SSH_Port") or 22)
    except ValueError:
        cfg.ssh_port = 22
    cfg.ssh_user = a.get("SSH_UserName", "")
    cfg.ssh_auth = "key" if (a.get("SSH_AuthenMethod") or "").upper() == "PUBLICKEY" else "password"
    cfg.ssh_key_file = a.get("SSH_PrivateKey", "")
    cfg.ssh_save_password = _bool(a.get("SSH_SavePassword", "true")) or _bool(a.get("SSH_SavePassphrase", "false"))
    secret_attr = "SSH_Passphrase" if cfg.ssh_auth == "key" else "SSH_Password"
    secret = navicat_decrypt(a.get(secret_attr, ""))
    if secret is None:
        item.notes.append("SSH password could not be decrypted; enter it after importing")
        secret = ""
    if cfg.ssh_auth == "key":
        cfg.ssh_passphrase = secret
    else:
        cfg.ssh_password = secret
    item.has_ssh_secret = bool(secret)
    item.notes.append(f"SSH tunnel via {cfg.ssh_user + '@' if cfg.ssh_user else ''}{cfg.ssh_host}")
    if cfg.ssh_auth == "key" and _is_windows_path(cfg.ssh_key_file):
        item.notes.append(f"Private key path {cfg.ssh_key_file} is a Windows path; update it after importing")


def _read_ssl(a, cfg, item):
    cfg.ssl_enabled = True
    cfg.ssl_ca = a.get("SSL_CACert", "")
    if _bool(a.get("SSL_Authen")) or a.get("SSL_ClientCert"):
        cfg.ssl_cert = a.get("SSL_ClientCert", "")
        cfg.ssl_key = a.get("SSL_ClientKey", "")
    cfg.ssl_mode = "verify_ca" if cfg.ssl_ca else "require"
    item.notes.append("SSL" + (" with CA verification" if cfg.ssl_ca else ""))
    if any(_is_windows_path(p) for p in (cfg.ssl_ca, cfg.ssl_cert, cfg.ssl_key) if p):
        item.notes.append("SSL certificate paths are Windows paths; update them after importing")


def read_json(path: str) -> list[ImportedConnection]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("connections", []) if isinstance(data, dict) else data
    fields = ConnectionConfig.__dataclass_fields__
    result = []
    for row in rows:
        values = {k: v for k, v in row.items() if k in fields and k != "id"}
        cfg = ConnectionConfig(**values)
        result.append(ImportedConnection(cfg, has_password=bool(cfg.password),
                                         has_ssh_secret=bool(cfg.ssh_password or cfg.ssh_passphrase)))
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


# --- updating existing connections ---------------------------------------------------------
# What a changed field is called in "Updates host, password, SSH"
_FIELD_LABELS = {"name": "name", "host": "host", "port": "port", "user": "user", "password": "password",
                 "save_password": "password", "database": "database"}


def _field_label(name):
    return "SSH" if name.startswith("ssh_") else "SSL" if name.startswith("ssl_") else _FIELD_LABELS.get(name, name)


def find_existing(cfg: ConnectionConfig, existing: list[ConnectionConfig]):
    """The saved connection an imported one updates: the one with the same name (ignoring case)."""
    return next((e for e in existing if e.name.strip().lower() == cfg.name.strip().lower()), None)


def merge(item: ImportedConnection, old: ConnectionConfig) -> tuple[ConnectionConfig, list[str]]:
    """The updated connection and the labels of what changed (empty: already up to date).

    The imported settings win, except that secrets the file doesn't contain and local file paths
    the file only has as Windows paths are kept from the saved connection. The id is kept, so the
    connection keeps its saved queries.
    """
    new = ConnectionConfig(**{f: getattr(item.config, f) for f in ConnectionConfig.__dataclass_fields__})
    new.id = old.id
    if not item.has_password:
        new.password, new.save_password = old.password, old.save_password
    if not item.has_ssh_secret:
        new.ssh_password, new.ssh_passphrase = old.ssh_password, old.ssh_passphrase
        new.ssh_save_password = old.ssh_save_password
    for path_field in ("ssh_key_file", "ssl_ca", "ssl_cert", "ssl_key"):
        value = getattr(new, path_field)
        if value and _is_windows_path(value) and getattr(old, path_field):
            setattr(new, path_field, getattr(old, path_field))
    changed = []
    for name in ConnectionConfig.__dataclass_fields__:
        if name != "id" and getattr(new, name) != getattr(old, name):
            label = _field_label(name)
            if label not in changed:
                changed.append(label)
    return new, changed


# --- export --------------------------------------------------------------------------------
def write_ncx(path: str, connections: list[ConnectionConfig], include_passwords=True) -> None:
    """Write a Navicat-compatible .ncx file (File → Import Connections in Navicat)."""
    root = ET.Element("Connections", Ver="1.5")
    for c in connections:
        save = include_passwords and c.save_password and bool(c.password)
        ssh_save = include_passwords and c.ssh_save_password
        ssh_key = c.ssh_auth == "key"
        ET.SubElement(root, "Connection", {
            "ConnectionName": c.name, "ProjectUUID": "", "ConnType": "MYSQL", "OraConnType": "",
            "ServiceProvider": "Default", "Host": c.host, "Port": str(c.port), "Database": c.database,
            "OraServiceNameType": "", "TNS": "", "MSSQLAuthenMode": "", "MSSQLAuthenWindowsDomain": "",
            "DatabaseFileName": "", "UserName": c.user,
            "Password": navicat_encrypt(c.password) if save else "",
            "SavePassword": "true" if save else "false", "SettingsSavePath": "", "SessionLimit": "0",
            "Encoding": "65001", "Keepalive": "false", "KeepaliveInterval": "240", "MySQLCharacterSet": "true",
            "Compression": "false", "AutoConnect": "false", "NamedPipe": "false", "NamedPipeSocket": "",
            "SSL": _xml_bool(c.ssl_enabled), "SSL_Authen": _xml_bool(c.ssl_enabled and bool(c.ssl_cert)),
            "SSL_ClientKey": c.ssl_key, "SSL_ClientCert": c.ssl_cert, "SSL_CACert": c.ssl_ca,
            "SSH": _xml_bool(c.ssh_enabled), "SSH_Host": c.ssh_host, "SSH_Port": str(c.ssh_port),
            "SSH_UserName": c.ssh_user, "SSH_AuthenMethod": "PUBLICKEY" if ssh_key else "PASSWORD",
            "SSH_Password": navicat_encrypt(c.ssh_password) if ssh_save and not ssh_key else "",
            "SSH_SavePassword": _xml_bool(ssh_save and not ssh_key and bool(c.ssh_password)),
            "SSH_PrivateKey": c.ssh_key_file,
            "SSH_Passphrase": navicat_encrypt(c.ssh_passphrase) if ssh_save and ssh_key else "",
            "SSH_SavePassphrase": _xml_bool(ssh_save and ssh_key and bool(c.ssh_passphrase)),
            "HTTP": "false",
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
        if not include_passwords or not c.ssh_save_password:
            row["ssh_password"] = row["ssh_passphrase"] = ""
        rows.append(row)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"app": APP_NAME, "version": APP_VERSION, "connections": rows}, f, indent=2)


def _xml_bool(value) -> str:
    return "true" if value else "false"


def can_decrypt() -> bool:
    return Cipher is not None

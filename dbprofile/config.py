"""Saved connection profiles, stored as JSON in ~/.config/dbprofile/."""
import json
import os
import uuid
from dataclasses import asdict, dataclass, field

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "dbprofile"
)
CONNECTIONS_FILE = os.path.join(CONFIG_DIR, "connections.json")


@dataclass
class ConnectionConfig:
    name: str = "New connection"
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = ""
    save_password: bool = True
    # SSH tunnel: MySQL is reached through this SSH server; host/port above are as seen from it.
    ssh_enabled: bool = False
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_auth: str = "password"  # "password" or "key"
    ssh_password: str = ""
    ssh_key_file: str = ""  # empty: use the SSH agent and ~/.ssh default keys
    ssh_passphrase: str = ""
    ssh_save_password: bool = True
    # SSL: "require" encrypts only; "verify_ca" also checks the server certificate; "verify_identity" its host name too
    ssl_enabled: bool = False
    ssl_mode: str = "require"
    ssl_ca: str = ""
    ssl_cert: str = ""  # client certificate and key, for servers that require them
    ssl_key: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def address(self) -> str:
        """user@host:port, plus how it is reached, for tooltips."""
        text = f"{self.user}@{self.host}:{self.port}"
        if self.ssh_enabled:
            text += f" via SSH {self.ssh_user}@{self.ssh_host}:{self.ssh_port}"
        if self.ssl_enabled:
            text += " (SSL)"
        return text


def load_connections() -> list[ConnectionConfig]:
    try:
        with open(CONNECTIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    fields = ConnectionConfig.__dataclass_fields__
    return [ConnectionConfig(**{k: v for k, v in d.items() if k in fields}) for d in data]


def save_connections(connections: list[ConnectionConfig]) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data = []
    for c in connections:
        d = asdict(c)
        if not c.save_password:
            d["password"] = ""
        if not c.ssh_save_password:
            d["ssh_password"] = d["ssh_passphrase"] = ""
        data.append(d)
    tmp = CONNECTIONS_FILE + ".tmp"
    # File may contain passwords: keep it readable by the owner only.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CONNECTIONS_FILE)

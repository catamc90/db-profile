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
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


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
        data.append(d)
    tmp = CONNECTIONS_FILE + ".tmp"
    # File may contain passwords: keep it readable by the owner only.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CONNECTIONS_FILE)

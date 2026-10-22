"""SSH tunnels for MySQL connections (Navicat's SSH tab), using paramiko.

One SSH session per saved connection is shared by all of its MySQL connections: each one is a
"direct-tcpip" channel to the MySQL host and port as seen from the SSH server, relayed to PyMySQL
through a local socket pair (so no local port is opened).
"""
import logging
import os
import select
import socket
import threading

from .config import CONFIG_DIR

try:
    import paramiko
    # Failures are reported as SSHError; don't let paramiko also print them to stderr.
    logging.getLogger("paramiko").addHandler(logging.NullHandler())
    logging.getLogger("paramiko").propagate = False
except ImportError:  # SSH is optional; connecting with it explains how to install paramiko
    paramiko = None

KNOWN_HOSTS = os.path.join(CONFIG_DIR, "known_hosts")


class SSHError(Exception):
    pass


def _accept_new_policy():
    class AcceptNew(paramiko.MissingHostKeyPolicy):
        """Trust an unknown server's key and remember it, like ssh's "accept-new".

        A key that differs from the remembered one is still rejected by paramiko (BadHostKeyException).
        """

        def missing_host_key(self, client, hostname, key):
            client.get_host_keys().add(hostname, key.get_name(), key)
            client.save_host_keys(KNOWN_HOSTS)
    return AcceptNew()


def _signature(cfg):
    return (cfg.ssh_host, int(cfg.ssh_port), cfg.ssh_user, cfg.ssh_auth, cfg.ssh_password, cfg.ssh_key_file,
            cfg.ssh_passphrase, cfg.host, int(cfg.port))


class Tunnel:
    def __init__(self, cfg):
        if paramiko is None:
            raise SSHError("SSH tunnels need the paramiko package: .venv/bin/pip install paramiko")
        self.signature = _signature(cfg)
        self.remote = (cfg.host, int(cfg.port))
        where = f"{cfg.ssh_user}@{cfg.ssh_host}:{cfg.ssh_port}"
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if not os.path.exists(KNOWN_HOSTS):
            open(KNOWN_HOSTS, "a").close()
            os.chmod(KNOWN_HOSTS, 0o600)
        self.client.load_host_keys(KNOWN_HOSTS)
        self.client.set_missing_host_key_policy(_accept_new_policy())
        options = dict(hostname=cfg.ssh_host, port=int(cfg.ssh_port), username=cfg.ssh_user, timeout=10,
                       banner_timeout=10, auth_timeout=10)
        if cfg.ssh_auth == "key":
            key_file = os.path.expanduser(cfg.ssh_key_file) if cfg.ssh_key_file else None
            if key_file and not os.path.isfile(key_file):
                raise SSHError(f"SSH private key file not found: {key_file}")
            options.update(key_filename=key_file, passphrase=cfg.ssh_passphrase or None,
                           look_for_keys=key_file is None, allow_agent=True)
        else:
            options.update(password=cfg.ssh_password, look_for_keys=False, allow_agent=False)
        try:
            self.client.connect(**options)
        except paramiko.BadHostKeyException:
            raise SSHError(f"The host key of SSH server {cfg.ssh_host} has changed. If that is expected, "
                           f"remove its line from {KNOWN_HOSTS} (or ~/.ssh/known_hosts) and try again.") from None
        except paramiko.PasswordRequiredException:
            raise SSHError("The SSH private key is encrypted: enter its passphrase.") from None
        except paramiko.AuthenticationException:
            raise SSHError(f"SSH authentication failed for {where}.") from None
        except (paramiko.SSHException, OSError) as e:
            raise SSHError(f"Could not connect to SSH server {where}: {e}") from None
        self.transport = self.client.get_transport()
        self.transport.set_keepalive(30)
        self.where = where
        self.closed = False

    def active(self):
        return not self.closed and self.transport.is_active()

    def open_socket(self, timeout):
        """A socket connected through the tunnel to the MySQL server."""
        host, port = self.remote
        try:
            channel = self.transport.open_channel("direct-tcpip", self.remote, ("127.0.0.1", 0), timeout=timeout)
        except (paramiko.SSHException, OSError) as e:
            raise SSHError(f"The SSH server {self.where} could not connect to MySQL at {host}:{port}. "
                           f"Check the host and port on the General tab: they are as seen from the SSH server. "
                           f"({e})") from None
        mine, theirs = socket.socketpair()
        threading.Thread(target=self._relay, args=(theirs, channel), name="ssh-relay", daemon=True).start()
        return mine

    @staticmethod
    def _relay(sock, channel):
        try:
            while True:
                readable, _, _ = select.select([sock, channel], [], [])
                if sock in readable:
                    data = sock.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in readable:
                    data = channel.recv(65536)
                    if not data:
                        break
                    sock.sendall(data)
        except OSError:
            pass
        finally:
            channel.close()
            sock.close()

    def close(self):
        self.closed = True
        self.client.close()


_tunnels: dict[str, Tunnel] = {}
_lock = threading.Lock()


def get_tunnel(cfg) -> Tunnel:
    """The open tunnel for this connection; (re)connects when it dropped or its settings changed."""
    with _lock:
        tunnel = _tunnels.get(cfg.id)
        if tunnel is not None and (tunnel.signature != _signature(cfg) or not tunnel.active()):
            tunnel.close()
            tunnel = None
        if tunnel is None:
            tunnel = _tunnels[cfg.id] = Tunnel(cfg)
        return tunnel


def close(cfg_id: str) -> None:
    with _lock:
        tunnel = _tunnels.pop(cfg_id, None)
    if tunnel is not None:
        tunnel.close()


def close_all() -> None:
    for cfg_id in list(_tunnels):
        close(cfg_id)

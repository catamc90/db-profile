import os

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from . import db
from .config import ConnectionConfig

SSL_MODES = [
    ("require", "Require (encrypt only)"),
    ("verify_ca", "Verify CA certificate"),
    ("verify_identity", "Verify CA certificate and host name"),
]


class _FileField(QWidget):
    """A path field with a Browse… button."""

    def __init__(self, path, caption, file_filter="All files (*)", placeholder=""):
        super().__init__()
        self.caption, self.file_filter = caption, file_filter
        self.edit = QLineEdit(path)
        self.edit.setPlaceholderText(placeholder)
        browse = QPushButton("Browse…")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.edit, 1)
        row.addWidget(browse)

    def _browse(self):
        start = os.path.dirname(os.path.expanduser(self.edit.text())) or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, self.caption, start, self.file_filter)
        if path:
            self.edit.setText(path)

    def text(self):
        return self.edit.text().strip()


def _form_page():
    page = QWidget()
    form = QFormLayout(page)
    form.setContentsMargins(14, 14, 14, 10)
    form.setVerticalSpacing(8)
    return page, form


class ConnectionDialog(QDialog):
    def __init__(self, cfg: ConnectionConfig | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Connection" if cfg else "New MySQL Connection")
        self.cfg = cfg or ConnectionConfig()
        self.setMinimumWidth(460)
        c = self.cfg

        # General
        general, form = _form_page()
        self.name = QLineEdit(c.name)
        self.host = QLineEdit(c.host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(c.port))
        self.user = QLineEdit(c.user)
        self.password = QLineEdit(c.password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.save_password = QCheckBox("Save password")
        self.save_password.setChecked(c.save_password)
        self.database = QLineEdit(c.database)
        self.database.setPlaceholderText("optional")
        form.addRow("Connection name:", self.name)
        form.addRow("Host:", self.host)
        form.addRow("Port:", self.port)
        form.addRow("User name:", self.user)
        form.addRow("Password:", self.password)
        form.addRow("", self.save_password)
        form.addRow("Default database:", self.database)
        self.host_hint = QLabel("With an SSH tunnel, the host is as seen from the SSH server (e.g. localhost).")
        self.host_hint.setObjectName("muted")
        self.host_hint.setWordWrap(True)
        form.addRow("", self.host_hint)

        # SSL
        ssl_page, form = _form_page()
        self.ssl_enabled = QCheckBox("Use SSL")
        self.ssl_enabled.setChecked(c.ssl_enabled)
        self.ssl_mode = QComboBox()
        for key, label in SSL_MODES:
            self.ssl_mode.addItem(label, key)
        self.ssl_mode.setCurrentIndex(max(0, self.ssl_mode.findData(c.ssl_mode)))
        cert_filter = "Certificates (*.pem *.crt *.cer *.key);;All files (*)"
        self.ssl_ca = _FileField(c.ssl_ca, "CA Certificate", cert_filter, "system CAs when empty")
        self.ssl_cert = _FileField(c.ssl_cert, "Client Certificate", cert_filter, "optional")
        self.ssl_key = _FileField(c.ssl_key, "Client Key", cert_filter, "optional")
        form.addRow("", self.ssl_enabled)
        note = QLabel("Without this, the connection is still encrypted when the server supports it, "
                      "but SSL is not required and the server certificate is not checked.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        form.addRow("", note)
        form.addRow("Mode:", self.ssl_mode)
        form.addRow("CA certificate:", self.ssl_ca)
        client = QLabel("Client certificate and key, for servers that require them:")
        client.setObjectName("muted")
        form.addRow(client)
        form.addRow("Client certificate:", self.ssl_cert)
        form.addRow("Client key:", self.ssl_key)
        self.ssl_fields = [self.ssl_mode, self.ssl_ca, self.ssl_cert, self.ssl_key]
        self.ssl_enabled.toggled.connect(self._update_fields)
        self.ssl_mode.currentIndexChanged.connect(self._update_fields)

        # SSH
        ssh_page, form = _form_page()
        self.ssh_form = form
        self.ssh_enabled = QCheckBox("Use SSH tunnel")
        self.ssh_enabled.setChecked(c.ssh_enabled)
        self.ssh_host = QLineEdit(c.ssh_host)
        self.ssh_port = QSpinBox()
        self.ssh_port.setRange(1, 65535)
        self.ssh_port.setValue(int(c.ssh_port))
        self.ssh_user = QLineEdit(c.ssh_user)
        self.ssh_auth = QComboBox()
        self.ssh_auth.addItem("Password", "password")
        self.ssh_auth.addItem("Public Key", "key")
        self.ssh_auth.setCurrentIndex(max(0, self.ssh_auth.findData(c.ssh_auth)))
        self.ssh_password = QLineEdit(c.ssh_password)
        self.ssh_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.ssh_key_file = _FileField(c.ssh_key_file, "Private Key", "All files (*)",
                                       "empty: SSH agent and ~/.ssh keys")
        self.ssh_passphrase = QLineEdit(c.ssh_passphrase)
        self.ssh_passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        self.ssh_passphrase.setPlaceholderText("if the key is encrypted")
        self.ssh_save_password = QCheckBox("Save password")
        self.ssh_save_password.setChecked(c.ssh_save_password)
        form.addRow("", self.ssh_enabled)
        form.addRow("Host:", self.ssh_host)
        form.addRow("Port:", self.ssh_port)
        form.addRow("User name:", self.ssh_user)
        form.addRow("Authentication:", self.ssh_auth)
        form.addRow("Password:", self.ssh_password)
        form.addRow("Private key:", self.ssh_key_file)
        form.addRow("Passphrase:", self.ssh_passphrase)
        form.addRow("", self.ssh_save_password)
        self.ssh_fields = [self.ssh_host, self.ssh_port, self.ssh_user, self.ssh_auth, self.ssh_password,
                           self.ssh_key_file, self.ssh_passphrase, self.ssh_save_password]
        self.ssh_enabled.toggled.connect(self._update_fields)
        self.ssh_auth.currentIndexChanged.connect(self._update_fields)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("subTabs")
        self.tabs.addTab(general, "General")
        self.tabs.addTab(ssl_page, "SSL")
        self.tabs.addTab(ssh_page, "SSH")

        # Navicat layout: "Test Connection" bottom-left, OK / Cancel bottom-right
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        test = QPushButton("Test Connection")
        test.setAutoDefault(False)
        test.clicked.connect(self.test_connection)
        row = QHBoxLayout()
        row.setContentsMargins(12, 4, 12, 12)
        row.addWidget(test)
        row.addStretch(1)
        row.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)
        layout.addLayout(row)
        self._update_fields()

    def _update_fields(self):
        ssl = self.ssl_enabled.isChecked()
        for w in self.ssl_fields:
            w.setEnabled(ssl)
        ssh = self.ssh_enabled.isChecked()
        for w in self.ssh_fields:
            w.setEnabled(ssh)
        key = self.ssh_auth.currentData() == "key"
        for widget, visible in ((self.ssh_password, not key), (self.ssh_key_file, key), (self.ssh_passphrase, key)):
            self.ssh_form.setRowVisible(widget, visible)
        self.ssh_save_password.setText("Save passphrase" if key else "Save password")
        self.host_hint.setVisible(ssh)
        self.tabs.setTabText(1, "SSL ✓" if ssl else "SSL")
        self.tabs.setTabText(2, "SSH ✓" if ssh else "SSH")

    def result_config(self) -> ConnectionConfig:
        return ConnectionConfig(
            id=self.cfg.id,
            name=self.name.text().strip() or self.host.text().strip(),
            host=self.host.text().strip() or "127.0.0.1",
            port=self.port.value(),
            user=self.user.text().strip(),
            password=self.password.text(),
            database=self.database.text().strip(),
            save_password=self.save_password.isChecked(),
            ssh_enabled=self.ssh_enabled.isChecked(),
            ssh_host=self.ssh_host.text().strip(),
            ssh_port=self.ssh_port.value(),
            ssh_user=self.ssh_user.text().strip(),
            ssh_auth=self.ssh_auth.currentData(),
            ssh_password=self.ssh_password.text(),
            ssh_key_file=self.ssh_key_file.text(),
            ssh_passphrase=self.ssh_passphrase.text(),
            ssh_save_password=self.ssh_save_password.isChecked(),
            ssl_enabled=self.ssl_enabled.isChecked(),
            ssl_mode=self.ssl_mode.currentData(),
            ssl_ca=self.ssl_ca.text(),
            ssl_cert=self.ssl_cert.text(),
            ssl_key=self.ssl_key.text(),
        )

    def validate(self, cfg) -> str | None:
        if cfg.ssh_enabled and not (cfg.ssh_host and cfg.ssh_user):
            return "Enter the SSH host and user name on the SSH tab."
        if cfg.ssl_enabled and cfg.ssl_key and not cfg.ssl_cert:
            return "A client key needs its client certificate (SSL tab)."
        for label, path in (("CA certificate", cfg.ssl_ca), ("Client certificate", cfg.ssl_cert),
                            ("Client key", cfg.ssl_key)):
            if cfg.ssl_enabled and path and not os.path.isfile(os.path.expanduser(path)):
                return f"{label} file not found: {path}"
        return None

    def accept(self):
        error = self.validate(self.result_config())
        if error:
            QMessageBox.warning(self, "Connection", error)
            return
        super().accept()

    def test_connection(self):
        cfg = self.result_config()
        error = self.validate(cfg)
        if error:
            QMessageBox.warning(self, "Connection", error)
            return
        cfg.id = "test-" + cfg.id  # its own SSH tunnel, closed afterwards
        try:
            conn = db.connect(cfg)
            version = db.execute(conn, "SELECT VERSION()").rows[0][0]
            cipher = db.execute(conn, "SHOW SESSION STATUS LIKE 'Ssl_cipher'").rows
            conn.close()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Connection failed", str(e))
        else:
            lines = [f"Connected successfully.\nServer version: {version}"]
            if cfg.ssh_enabled:
                lines.append(f"Through SSH: {cfg.ssh_user}@{cfg.ssh_host}:{cfg.ssh_port}")
            if cipher and cipher[0][1]:
                lines.append(f"SSL cipher: {cipher[0][1]}")
            QMessageBox.information(self, "Connection OK", "\n".join(lines))
        finally:
            if cfg.ssh_enabled:
                from . import ssh_tunnel
                ssh_tunnel.close(cfg.id)

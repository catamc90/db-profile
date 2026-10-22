from PyQt6.QtWidgets import (
    QCheckBox, QHBoxLayout, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox, QPushButton, QSpinBox,
)

from . import db
from .config import ConnectionConfig


class ConnectionDialog(QDialog):
    def __init__(self, cfg: ConnectionConfig | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Connection" if cfg else "New MySQL Connection")
        self.cfg = cfg or ConnectionConfig()
        self.setMinimumWidth(380)

        self.name = QLineEdit(self.cfg.name)
        self.host = QLineEdit(self.cfg.host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(self.cfg.port))
        self.user = QLineEdit(self.cfg.user)
        self.password = QLineEdit(self.cfg.password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.save_password = QCheckBox("Save password")
        self.save_password.setChecked(self.cfg.save_password)
        self.database = QLineEdit(self.cfg.database)
        self.database.setPlaceholderText("optional")

        form = QFormLayout(self)
        form.addRow("Connection name:", self.name)
        form.addRow("Host:", self.host)
        form.addRow("Port:", self.port)
        form.addRow("User name:", self.user)
        form.addRow("Password:", self.password)
        form.addRow("", self.save_password)
        form.addRow("Default database:", self.database)

        # Navicat layout: "Test Connection" bottom-left, OK / Cancel bottom-right
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        test = QPushButton("Test Connection")
        test.setAutoDefault(False)
        test.clicked.connect(self.test_connection)
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.addWidget(test)
        row.addStretch(1)
        row.addWidget(buttons)
        form.addRow(row)

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
        )

    def test_connection(self):
        try:
            conn = db.connect(self.result_config())
            version = db.execute(conn, "SELECT VERSION()").rows[0][0]
            conn.close()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Connection failed", str(e))
        else:
            QMessageBox.information(self, "Connection OK", f"Connected successfully.\nServer version: {version}")

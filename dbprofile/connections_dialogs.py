"""Dialogs for importing and exporting saved connections (Navicat .ncx and DB Profile .json)."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from . import connections_io, icons, theme

DUPLICATE_ACTIONS = [
    ("Update it (keeps its saved queries and any saved password the file doesn't have)", "update"),
    ("Import it as a copy with a new name", "rename"),
    ("Skip it", "skip"),
]
STATUS_COL, NOTES_COL = 4, 5


class ImportConnectionsDialog(QDialog):
    """Pick a .ncx / .json file, review the connections found, import the checked ones."""

    def __init__(self, existing, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Connections")
        self.resize(860, 480)
        self.existing = existing
        self.items: list[connections_io.ImportedConnection] = []

        self.path = QLineEdit()
        self.path.setPlaceholderText("Navicat connections file (.ncx) or DB Profile export (.json)")
        self.path.returnPressed.connect(self._load)
        browse = QPushButton("Browse…")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        file_row = QHBoxLayout()
        file_row.addWidget(self.path, 1)
        file_row.addWidget(browse)

        hint = QLabel("In Navicat use <b>File → Export Connections…</b> and tick <b>Export Password</b>, "
                      "then open the .ncx file here.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)

        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Connection", "Host", "User", "Password", "Import", "Notes"])
        self.list.setRootIsDecorated(False)
        self.list.header().setSectionResizeMode(NOTES_COL, QHeaderView.ResizeMode.Stretch)
        self.list.itemChanged.connect(self._update_button)

        self.duplicates = QComboBox()
        for label, value in DUPLICATE_ACTIONS:
            self.duplicates.addItem(label, value)
        self.duplicates.currentIndexChanged.connect(self._update_status)
        options = QFormLayout()
        options.addRow("If a connection already exists:", self.duplicates)

        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Import")
        self.ok.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.summary, 1)
        bottom.addWidget(self.buttons)

        layout = QVBoxLayout(self)
        layout.addLayout(file_row)
        layout.addWidget(hint)
        layout.addWidget(self.list, 1)
        layout.addLayout(options)
        layout.addLayout(bottom)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Connections", os.path.expanduser("~"),
                                              "Connection files (*.ncx *.json);;Navicat (*.ncx);;DB Profile (*.json);;"
                                              "All files (*)")
        if path:
            self.path.setText(path)
            self._load()

    def load(self, path):
        self.path.setText(path)
        self._load()

    def _load(self):
        self.list.clear()
        self.items = []
        path = self.path.text().strip()
        if not path:
            return
        try:
            self.items = connections_io.read_file(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Import Connections", f"Cannot read the file:\n{e}")
            return
        self.list.blockSignals(True)
        for item in self.items:
            cfg = item.config
            notes = list(item.notes)
            if not item.password_ok:
                password = "Not decrypted"
            elif cfg.password:
                password = "Saved"
            else:
                password = "Ask when connecting" if not cfg.save_password else "Empty"
            row = QTreeWidgetItem([cfg.name, f"{cfg.host}:{cfg.port}", cfg.user, password, "", "; ".join(notes)])
            row.setData(3, Qt.ItemDataRole.UserRole, password)  # shown again when not updating
            row.setIcon(0, icons.icon("connection" if item.supported else "connection_closed"))
            if item.supported:
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                row.setCheckState(0, Qt.CheckState.Checked)
            else:
                row.setFlags(row.flags() & ~(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable))
            if notes:
                row.setToolTip(NOTES_COL, "\n".join(notes))
                row.setForeground(NOTES_COL, QColor(theme.MUTED))
            if not item.password_ok:
                row.setForeground(3, QColor("#c62828"))
            self.list.addTopLevelItem(row)
        self.list.blockSignals(False)
        self._update_status()
        for c in range(NOTES_COL):
            self.list.resizeColumnToContents(c)
            self.list.setColumnWidth(c, self.list.columnWidth(c) + 16)  # room for the header padding
        if not self.items:
            self.summary.setText("No connections found in this file.")

    def _status(self, item):
        """("new" | "update" | "unchanged" | "copy" | "skip", text for the Import column)."""
        old = connections_io.find_existing(item.config, self.existing)
        if old is None:
            return "new", "New"
        action = self.duplicates.currentData()
        if action == "skip":
            return "skip", "Exists, skipped"
        if action == "rename":
            return "copy", "Copy of existing"
        _, changed = connections_io.merge(item, old)
        if not changed:
            return "unchanged", "Up to date"
        return "update", "Updates " + ", ".join(changed)

    def _update_status(self, *_):
        self.list.blockSignals(True)
        for i, item in enumerate(self.items):
            row = self.list.topLevelItem(i)
            if not item.supported:
                row.setText(STATUS_COL, "Not supported")
                continue
            kind, text = self._status(item)
            # An update keeps what the file doesn't have: say so instead of "Empty" or "fix this path".
            old = connections_io.find_existing(item.config, self.existing) if kind in ("update", "unchanged") else None
            password = row.data(3, Qt.ItemDataRole.UserRole)
            if old is not None and not item.has_password and old.password:
                password = "Keeps saved"
            row.setText(3, password)
            notes = list(item.notes)
            if old is not None:
                merged, _ = connections_io.merge(item, old)
                kept = [n for n in notes if "Windows path" in n]
                if kept and any(getattr(merged, f) == getattr(old, f) and getattr(old, f)
                                for f in ("ssh_key_file", "ssl_ca", "ssl_cert", "ssl_key")):
                    notes = [n for n in notes if n not in kept] + ["Keeps your local key / certificate paths"]
            row.setText(NOTES_COL, "; ".join(notes))
            row.setToolTip(NOTES_COL, "\n".join(notes))
            row.setText(STATUS_COL, text)
            row.setToolTip(STATUS_COL, text)
            color = {"new": "#2e7d32", "update": theme.ACCENT}.get(kind, theme.MUTED)
            row.setForeground(STATUS_COL, QColor(color))
        self.list.blockSignals(False)
        self._update_button()

    def _checked(self):
        return [item for i, item in enumerate(self.items)
                if item.supported and self.list.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]

    def _update_button(self, *_):
        checked = self._checked()
        kinds = [self._status(item)[0] for item in checked]
        new = kinds.count("new") + kinds.count("copy")
        updated = kinds.count("update")
        self.ok.setEnabled(bool(new or updated))
        parts = [f"{new} new", f"{updated} updated"]
        if kinds.count("unchanged"):
            parts.append(f"{kinds.count('unchanged')} up to date")
        if kinds.count("skip"):
            parts.append(f"{kinds.count('skip')} skipped")
        unsupported = sum(1 for i in self.items if not i.supported)
        if unsupported:
            parts.append(f"{unsupported} not MySQL/MariaDB")
        self.summary.setText(" · ".join(parts))

    def result_plan(self):
        """[(config, existing config it updates or None)] for the checked connections that change something."""
        names = {c.name.lower() for c in self.existing}
        plan = []
        for item in self._checked():
            kind, _ = self._status(item)
            if kind in ("skip", "unchanged"):
                continue
            if kind == "update":
                old = connections_io.find_existing(item.config, self.existing)
                plan.append((connections_io.merge(item, old)[0], old))
                continue
            cfg = item.config
            base, n = cfg.name, 2
            while cfg.name.lower() in names:
                cfg.name = f"{base} ({n})"
                n += 1
            names.add(cfg.name.lower())
            plan.append((cfg, None))
        return plan


class ExportConnectionsDialog(QDialog):
    def __init__(self, connections, selected_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Connections")
        self.resize(560, 440)
        self.connections = connections
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Connection", "Host", "User"])
        self.list.setRootIsDecorated(False)
        for c in connections:
            row = QTreeWidgetItem([c.name, f"{c.host}:{c.port}", c.user])
            row.setIcon(0, icons.icon("connection"))
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Checked if selected_id in (None, c.id) else Qt.CheckState.Unchecked)
            self.list.addTopLevelItem(row)
        for col in range(3):
            self.list.resizeColumnToContents(col)
        self.list.itemChanged.connect(self._update_button)

        self.format = QComboBox()
        self.format.addItem("Navicat (.ncx) — can be imported into Navicat", "ncx")
        self.format.addItem("DB Profile (.json)", "json")
        self.passwords = QCheckBox("Export passwords")
        self.passwords.setChecked(True)
        self.passwords.setToolTip("Navicat files store passwords with Navicat's encryption; JSON files store them "
                                  "as plain text. Keep exported files private.")
        form = QFormLayout()
        form.addRow("Format:", self.format)
        form.addRow("", self.passwords)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Export…")
        buttons.accepted.connect(self._export)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list, 1)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._update_button()

    def _checked(self):
        return [c for i, c in enumerate(self.connections)
                if self.list.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]

    def _update_button(self, *_):
        self.ok.setEnabled(bool(self._checked()))

    def _export(self):
        fmt = self.format.currentData()
        default = os.path.expanduser(f"~/connections.{fmt}")
        path, _ = QFileDialog.getSaveFileName(self, "Export Connections", default,
                                              "Navicat connections (*.ncx)" if fmt == "ncx" else "JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith("." + fmt):
            path += "." + fmt
        try:
            self.export_to(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Export Connections", str(e))
            return
        self.saved_path = path
        self.accept()

    def export_to(self, path):
        writer = connections_io.write_ncx if self.format.currentData() == "ncx" else connections_io.write_json
        writer(path, self._checked(), self.passwords.isChecked())
        if self.passwords.isChecked():
            os.chmod(path, 0o600)  # the file contains passwords

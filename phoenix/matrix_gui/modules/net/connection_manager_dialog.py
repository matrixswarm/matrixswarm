# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals — Phoenix Commander Edition
from PyQt6 import QtWidgets
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QMessageBox,
    QAbstractItemView,
    QTableWidgetItem,
)
from PyQt6.QtCore import Qt

from matrix_gui.modules.net.connection_types.editors.registry import CONNECTION_EDITOR_REGISTRY
from matrix_gui.modules.net.connection_types.providers.registry import CONNECTION_PROVIDER_REGISTRY

from matrix_gui.modules.net.edit_connection_dialog import edit_connection_dialog
from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton


class ConnectionManagerDialog(QtWidgets.QDialog):
    """
    Completely refactored Connection Manager:
    - Editors handle editing
    - Providers handle table presentation
    - No per-proto if/else logic
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        try:

            self.setWindowTitle("Connection Manager")
            self.setMinimumSize(900, 500)

            # Registries
            self.editor_registry = CONNECTION_EDITOR_REGISTRY
            self.provider_registry = CONNECTION_PROVIDER_REGISTRY

            # Tabs keyed by proto
            self.tabs = QtWidgets.QTabWidget()
            self.tables = {}

            for proto, provider in self.provider_registry.items():
                table = QtWidgets.QTableWidget()
                cols = provider.get_columns()
                table.setColumnCount(len(cols) + 1)
                table.setHorizontalHeaderLabels(cols)

                table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                table.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                table.cellDoubleClicked.connect(self._edit_row)
                table.setColumnHidden(len(cols), True)
                self.tables[proto] = table
                self.tabs.addTab(table, proto.upper())

            # Buttons ------------------------------------------------------
            self.btn_add = QtWidgets.QPushButton("Add")
            self.btn_edit = QtWidgets.QPushButton("Edit")
            self.btn_delete = QtWidgets.QPushButton("Delete")
            self.btn_close = QtWidgets.QPushButton("Close")

            self.btn_add.clicked.connect(self._add_entry)
            self.btn_edit.clicked.connect(self._edit_row)
            self.btn_delete.clicked.connect(self._delete_row)
            self.btn_close.clicked.connect(self.accept)

            button_row = QtWidgets.QHBoxLayout()
            button_row.addWidget(self.btn_add)
            button_row.addWidget(self.btn_edit)
            button_row.addWidget(self.btn_delete)
            button_row.addStretch()
            button_row.addWidget(self.btn_close)

            layout = QtWidgets.QVBoxLayout(self)
            layout.addWidget(self.tabs)
            layout.addLayout(button_row)

            self.reload_all()

        except Exception as e:
            emit_gui_exception_log("ConnectionManagerDialog.__init__", e)

    # -------------------------------------------------------------
    # UTILITIES
    # -------------------------------------------------------------
    def _vault(self):
        """Always fetch the live vault snapshot."""
        return VaultCoreSingleton.get().read()

    def _connection_manager(self):
        v = self._vault()
        return v.setdefault("connection_manager", {})

    def _current_proto(self):
        idx = self.tabs.currentIndex()
        if idx < 0:
            return None
        return self.tabs.tabText(idx).lower()

    def _current_table(self):
        proto = self._current_proto()
        return proto, self.tables.get(proto)

    # -------------------------------------------------------------
    # DATA LOADING
    # -------------------------------------------------------------
    def reload_all(self):
        for proto in self.provider_registry:
            self._load_table(proto)

    def _load_table(self, proto):

        try:
            provider = self.provider_registry[proto]
            table = self.tables[proto]
            table.setRowCount(0)

            cm = self._connection_manager().get(proto, {})

            for conn_id, data in cm.items():
                used_in = self._find_usage(conn_id)

                row_data = provider.get_row(data, used_in)
                row = table.rowCount()
                table.insertRow(row)

                for col, value in enumerate(row_data):
                    table.setItem(row, col, QTableWidgetItem(str(value)))

                # Hidden real ID for easy retrieval
                item = QTableWidgetItem(conn_id)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                hidden_col = len(provider.get_columns())
                table.setItem(row, hidden_col, item)

        except Exception as e:
            emit_gui_exception_log("ConnectionManagerDialog._load_table", e)

    def _find_usage(self, conn_id):
        """Find deployments where connection is referenced."""

        try:
            used = []
            deployments = self._vault().get("deployments", {})

            for dep_id, dep in deployments.items():
                if not isinstance(dep, dict):
                    continue

                for agent in dep.get("agents", []):
                    for tag in agent.get("tags", []):
                        ct = tag.get("connection-tag")
                        if ct and ct.get("id") == conn_id:
                            used.append(dep_id)

            return used


        except Exception as e:
            emit_gui_exception_log("ConnectionManagerDialog._find_usage", e)

    # -------------------------------------------------------------
    # ADD ENTRY
    # -------------------------------------------------------------
    def _add_entry(self):

        try:
            proto = self._current_proto()
            if not proto:
                return

            # Launch editor dialog
            conn_id, data = edit_connection_dialog(self, default_proto=proto, data={}, new_conn=True)
            if not conn_id or not data or not isinstance(data, dict):
                return

            new_proto = data["proto"]  # user might switch proto while editing

            cm = self._connection_manager()
            cm.setdefault(new_proto, {})[conn_id] = data

            VaultCoreSingleton.get().patch("connection_manager", cm)
            self.reload_all()

        except Exception as e:
            emit_gui_exception_log("ConnectionManagerDialog._add_entry", e)

    # -------------------------------------------------------------
    # EDIT ENTRY
    # -------------------------------------------------------------
    def _edit_row(self, row=None, col=None):
        try:
            proto, table = self._current_table()
            if not table:
                return

            if row is None:
                row = table.currentRow()

            if row < 0:
                return

            # Retrieve conn_id from hidden last column
            real_id_item = table.item(row, table.columnCount() - 1)
            if not real_id_item:
                return

            conn_id = real_id_item.text()

            cm = self._connection_manager()
            existing = cm.get(proto, {}).get(conn_id)
            if not existing:
                return

            conn_id_new = None
            data = None

            try:
                # Open editor
                result = edit_connection_dialog(
                    self,
                    default_proto=existing.get("proto", proto),
                    data=existing,
                    conn_id=conn_id,
                    new_conn=False
                )

                # Ensure the result is a tuple with two elements or handle it safely
                if result and isinstance(result, tuple) and len(result) == 2:
                    conn_id_new, data = result
                else:
                    conn_id_new, data = None, None

            except Exception as e:
                emit_gui_exception_log("ConnectionManagerDialog._edit_row", e)

            if not conn_id_new:
                return

            # Update the existing record in place
            cm = self._connection_manager()
            cm[proto][conn_id] = data

            VaultCoreSingleton.get().patch("connection_manager", cm)
            self.reload_all()

        except Exception as e:
            emit_gui_exception_log("ConnectionManagerDialog._edit_row", e)

    # -------------------------------------------------------------
    # DELETE ENTRY
    # -------------------------------------------------------------
    def _delete_row(self):
        proto, table = self._current_table()
        if not table:
            return

        row = table.currentRow()
        if row < 0:
            return

        real_id_item = table.item(row, table.columnCount() - 1)
        if not real_id_item:
            return

        conn_id = real_id_item.text()

        used = self._find_usage(conn_id)
        if used:
            QMessageBox.warning(
                self, "Used Connection",
                f"This connection is referenced by deployments: {', '.join(used)}\n"
                f"Deleting won't break current deployments, but cannot be reassigned."
            )

        confirm = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete connection '{conn_id}'?"
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        cm = self._connection_manager()
        cm[proto].pop(conn_id, None)

        VaultCoreSingleton.get().patch("connection_manager", cm)
        self.reload_all()

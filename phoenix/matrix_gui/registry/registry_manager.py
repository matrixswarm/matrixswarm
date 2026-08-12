# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Commander Edition Registry Manager

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTabWidget, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.registry.object_classes import EDITOR_REGISTRY, PROVIDER_REGISTRY
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class RegistryManagerDialog(QDialog):
    """
    Commander Edition Registry Manager.
    Works in two modes:
        1) Full Mode – shows all object classes
        2) Class-Locked Mode – shows ONLY the requested class
    """
    def __init__(self, parent=None, class_lock=None, assign_callback=None):
        super().__init__(parent)
        self.class_lock = class_lock
        self.assign_callback = assign_callback
        self.setWindowTitle("Registry Manager")
        self.setMinimumSize(800, 600)

        vcs = VaultCoreSingleton.get()
        self.registry_store = vcs.get_store("registry")
        self._build_ui()
        self._populate_tabs()

    # ---------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # === Optional Class Dropdown (only for add mode) ===
        from PyQt6.QtWidgets import QComboBox
        if not self.class_lock:
            top_row = QHBoxLayout()
            top_row.addWidget(QLabel("Class:"))
            self.class_combo = QComboBox()
            self.class_combo.addItems(list(EDITOR_REGISTRY.keys()))
            top_row.addWidget(self.class_combo)
            layout.addLayout(top_row)
        else:
            self.class_combo = None

        # === Tabs ===
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # === Buttons ===
        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.edit_btn = QPushButton("Edit")
        self.del_btn = QPushButton("Delete")
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addStretch()

        # Assign button (if callback provided)
        if self.assign_callback:
            self.assign_btn = QPushButton("Assign to Agent")
            btn_row.addWidget(self.assign_btn)
            self.assign_btn.clicked.connect(self._assign)

        # Close button
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        # Wire up CRUD
        self.add_btn.clicked.connect(self._add)
        self.edit_btn.clicked.connect(self._edit)
        self.del_btn.clicked.connect(self._delete)

    # ---------------------------------------------------------
    def _populate_tabs(self):
        self.tabs.clear()

        if not self.class_lock and getattr(self, "class_combo", None):
            classes = [self.class_combo.currentText()]
        else:
            classes = [self.class_lock] if self.class_lock else list(EDITOR_REGISTRY.keys())

        for cls in classes:
            tab = QListWidget()
            tab.itemDoubleClicked.connect(self._assign_via_double_click)
            self._populate_class(cls, tab)
            self.tabs.addTab(tab, cls.upper())

    def _assign_via_double_click(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        cls, serial = data
        if not serial:
            return

        if self.assign_callback:
            self.assign_callback(cls, serial)
            self.accept()

    def _populate_class(self, cls, list_widget):
        list_widget.clear()

        provider = PROVIDER_REGISTRY.get(cls)
        if not provider:
            list_widget.addItem(f"❗ No provider for class: {cls}")
            return

        columns = provider.get_columns()

        # --- HEADER ROW (Chrome) ---
        header = "   |   ".join(columns)
        header_item = QListWidgetItem(header)
        header_item.setFlags(header_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        header_item.setForeground(QColor(128,128,128) )
        list_widget.addItem(header_item)

        # --- DATA ROWS ---
        ns = self.registry_store.get_namespace(cls)
        for serial, obj in ns.items():
            row = provider.get_row(obj)
            row_display = "   |   ".join(row)
            item = QListWidgetItem(row_display)
            item.setData(Qt.ItemDataRole.UserRole, (cls, serial))
            list_widget.addItem(item)

    def _edit_via_double_click(self, item):
        cls, serial = item.data(Qt.ItemDataRole.UserRole)
        self._edit_existing(cls, serial)

    def _edit_existing(self, cls, serial):
        provider = PROVIDER_REGISTRY.get(cls)
        editor_cls = EDITOR_REGISTRY.get(cls)
        if not editor_cls:
            QMessageBox.warning(self, "Missing Editor", f"No editor for {cls}")
            return

        ns = self.registry_store.get_namespace(cls)
        obj = ns.get(serial)
        if not obj:
            return

        editor = editor_cls(new_conn=False)
        editor._load_data(obj)

        if editor.exec():
            updated = editor.serialize()
            updated["class"] = cls
            updated["path"] = editor.get_directory_path()
            updated["serial"] = serial

            from datetime import datetime
            updated.setdefault("meta", {})
            updated["meta"]["modified"] = datetime.utcnow().isoformat() + "Z"

            ns[serial] = updated
            self.registry_store.commit()
            self._populate_tabs()

    def _current_selection(self):
        tab = self.tabs.currentWidget()
        if not tab:
            return None, None
        item = tab.currentItem()
        if not item:
            return None, None
        return item.data(Qt.ItemDataRole.UserRole)

    # ---------------------------------------------------------
    def _add(self):

        try:
            cls = self.class_lock or (
                self.class_combo.currentText() if self.class_combo else None
            )
            editor_cls = EDITOR_REGISTRY.get(cls)
            if not editor_cls:
                QMessageBox.warning(self, "Missing Editor", f"No editor for {cls}")
                return

            editor = editor_cls(new_conn=True)

            if editor.exec():
                serial = editor.get_serial()
                data = editor.serialize()
                data["class"] = cls
                data["path"] = editor.get_directory_path()

                # Add metadata
                from datetime import datetime
                data.setdefault("meta", {
                    "created": datetime.utcnow().isoformat() + "Z",
                    "modified": datetime.utcnow().isoformat() + "Z",
                    "version": 1
                })



                ns = self.registry_store.get_namespace(cls)
                ns[serial] = data

                print("Namespace object id:", id(ns))
                #print("Store registry obj id:", id(self.registry_store.get_data()["discord"]))
                self.registry_store.commit()
                self._populate_tabs()

        except Exception as e:
            emit_gui_exception_log("[RegistryManagerDialog][_add]:", e)


    def _edit(self):
        cls, serial = self._current_selection()
        if not serial:
            return

        data = self.registry_store.get_namespace(cls).get(serial)
        editor_cls = EDITOR_REGISTRY.get(cls)
        if not editor_cls:
            QMessageBox.warning(self, "Missing Editor", f"No editor for {cls}")
            return

        editor = editor_cls()
        editor.on_load(data)
        if editor.exec():
            new_data = editor.serialize()
            ns = self.registry_store.get_data().setdefault(cls, {})
            ns[serial] = new_data
            self.registry_store.commit()
            self._populate_tabs()

    def _delete(self):
        cls, serial = self._current_selection()
        if not serial:
            return
        confirmed = QMessageBox.question(self, "Delete?", f"Delete resource '{serial}' from {cls}?")
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        ns = self.registry_store.get_data().setdefault(cls, {})
        ns.pop(serial, None)
        self.registry_store.commit()
        self._populate_tabs()

    def _assign(self):
        cls, serial = self._current_selection()
        if serial and self.assign_callback:
            self.assign_callback(cls, serial)
            self.accept()

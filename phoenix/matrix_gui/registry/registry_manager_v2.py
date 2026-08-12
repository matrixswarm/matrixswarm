# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTabWidget, QMessageBox, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.registry.object_classes import EDITOR_REGISTRY, PROVIDER_REGISTRY
from matrix_gui.swarm_workspace.cls_lib.constraint.constraint_resolver import ConstraintResolver


class RegistryManagerDialogV2(QDialog):
    """
    Commander Edition – Registry Manager V2
    Dual-Mode:
      • Explorer Mode: full unlocked registry (from PhoenixControlPanel)
      • Assignment Mode: locked to one class (from Swarm Workspace)
    """
    def __init__(self, parent=None, class_lock=None, assign_callback=None):
        super().__init__(parent)

        # Mode detection
        self.class_lock = class_lock
        self.assign_callback = assign_callback
        self.is_explorer = not (class_lock or assign_callback)

        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self.setWindowTitle(
            "Registry Explorer" if self.is_explorer else f"Registry – {class_lock}"
        )
        self.setMinimumSize(900, 640)

        # Vault + store
        vcs = VaultCoreSingleton.get()
        self.registry_store = vcs.get_store("registry")

        self._build_ui()
        self._populate_tabs()


    # ---------------------------------------------------------
    # UI BUILD
    # ---------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ========== CLASS DROPDOWN (Explorer only) ==========
        if self.is_explorer:
            top_row = QHBoxLayout()
            top_row.addWidget(QLabel("Class:"))
            self.class_combo = QComboBox()

            live_classes = self.get_live_constraint_classes()
            self.class_combo.addItems(live_classes)
            top_row.addWidget(self.class_combo)
            layout.addLayout(top_row)

            self.class_combo.currentTextChanged.connect(self._on_class_changed)
        else:
            self.class_combo = None

        # ========== TABS ==========
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ========== BUTTON ROW ==========
        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.edit_btn = QPushButton("Edit")
        self.del_btn = QPushButton("Delete")
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addStretch()

        if not self.is_explorer and self.assign_callback:
            self.assign_btn = QPushButton("Assign to Agent")
            btn_row.addWidget(self.assign_btn)
            self.assign_btn.clicked.connect(self._assign)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        # Wire up CRUD
        self.add_btn.clicked.connect(self._add)
        self.edit_btn.clicked.connect(self._edit)
        self.del_btn.clicked.connect(self._delete)

        # Prime first live class immediately (Explorer mode)
        if self.is_explorer and self.class_combo and self.class_combo.count() > 0:
            first_cls = self.class_combo.itemText(0)
            self.class_combo.setCurrentText(first_cls)
            self._on_class_changed(first_cls)

    def get_live_constraint_classes(self):
        resolver = ConstraintResolver()
        live = []

        for cls in EDITOR_REGISTRY.keys():
            # must not be autogen
            if resolver.is_autogen(cls):
                continue

            # must have editor
            if not resolver.has_editor(cls):
                continue

            # must have provider (THIS is the missing gate)
            if cls not in PROVIDER_REGISTRY:
                continue

            live.append(cls)

        return sorted(live)

    # ---------------------------------------------------------
    # DATA POPULATION
    # ---------------------------------------------------------
    def _populate_tabs(self):
        self.tabs.clear()

        # Determine classes
        if self.is_explorer and self.class_combo:
            cls = self.class_combo.currentText()
            classes = [cls] if cls else []
        else:
            classes = [self.class_lock] if self.class_lock else []

        for cls in classes:
            self._build_class_tab(cls)

        if self.tabs.count() > 0:
            self.tabs.setCurrentIndex(0)
            self._on_tab_changed(0)

        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _build_class_tab(self, cls):
        if not cls:
            return
        tab = QListWidget()
        tab.itemDoubleClicked.connect(self._edit_via_double_click)
        self._populate_class(cls, tab)
        self.tabs.addTab(tab, cls.upper())

    def _edit_via_double_click(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        cls, serial = data
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

    def _on_class_changed(self, cls):
        if not cls:
            return
        self._populate_tabs()

    def _on_tab_changed(self, index):
        if index < 0:
            return
        tab = self.tabs.widget(index)
        if not tab:
            return
        cls = self.tabs.tabText(index).lower()
        self._populate_class(cls, tab)

    def _populate_class(self, cls, list_widget):
        list_widget.clear()
        provider = PROVIDER_REGISTRY.get(cls)
        if not provider:
            list_widget.addItem(f"❗ No provider for class: {cls}")
            return

        columns = provider.get_columns()
        header = "     ".join(columns)
        header_item = QListWidgetItem(header)
        header_item.setFlags(header_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        header_item.setForeground(QColor(128, 128, 128))
        list_widget.addItem(header_item)

        ns = self.registry_store.get_namespace(cls)
        for serial, obj in ns.items():
            row = provider.get_row(obj)
            row_display = "   |   ".join(row)
            item = QListWidgetItem(row_display)
            item.setData(Qt.ItemDataRole.UserRole, (cls, serial))
            list_widget.addItem(item)

    # ---------------------------------------------------------
    # CRUD
    # ---------------------------------------------------------
    def _current_selection(self):
        tab = self.tabs.currentWidget()
        if not tab:
            return None, None
        item = tab.currentItem()
        if not item:
            return None, None
        return item.data(Qt.ItemDataRole.UserRole)

    def _add(self):
        cls = self.class_lock or (self.class_combo.currentText() if self.class_combo else None)
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

            from datetime import datetime
            data.setdefault("meta", {
                "created": datetime.utcnow().isoformat() + "Z",
                "modified": datetime.utcnow().isoformat() + "Z",
                "version": 1
            })

            ns = self.registry_store.get_namespace(cls)
            ns[serial] = data
            self.registry_store.commit()
            self._populate_tabs()

    def _edit(self):
        cls, serial = self._current_selection()
        if not serial:
            return

        ns = self.registry_store.get_namespace(cls)
        data = ns.get(serial)
        editor_cls = EDITOR_REGISTRY.get(cls)
        if not editor_cls:
            QMessageBox.warning(self, "Missing Editor", f"No editor for {cls}")
            return

        editor = editor_cls()
        editor.on_load(data)
        if editor.exec():
            updated = editor.serialize()
            ns[serial] = updated
            self.registry_store.commit()
            self._populate_tabs()

    def _delete(self):
        cls, serial = self._current_selection()
        if not serial:
            return
        confirmed = QMessageBox.question(self, "Delete?", f"Delete resource '{serial}' from {cls}?")
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        ns = self.registry_store.get_namespace(cls)
        ns.pop(serial, None)
        self.registry_store.commit()
        self._populate_tabs()

    # ---------------------------------------------------------
    # ASSIGN CALLBACK
    # ---------------------------------------------------------
    def _assign(self):
        cls, serial = self._current_selection()
        if serial and self.assign_callback:
            self.assign_callback(cls, serial)
            self.accept()

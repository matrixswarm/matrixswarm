# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
"""Unified Phoenix registry explorer and constraint assignment dialog."""

from datetime import datetime
from copy import deepcopy

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.services.vault_core_singleton import (
    VaultCoreSingleton,
)
from matrix_gui.registry.object_classes import EDITOR_REGISTRY, PROVIDER_REGISTRY
from matrix_gui.swarm_workspace.cls_lib.constraint.constraint_resolver import (
    ConstraintResolver,
)


class RegistryManagerDialog(QDialog):
    """Manage registry objects in explorer or constraint-assignment mode.

    With no ``class_lock``, the category selector is visible and the operator
    can browse every live, registry-backed category. Supplying a
    ``class_lock`` hides the selector and exposes only that category, which is
    the mode used by a workspace constraint. An ``assign_callback`` adds the
    explicit assignment action without changing category visibility itself.
    Double-click always opens the selected object's editor in either mode.
    """

    def __init__(self, parent=None, class_lock=None, assign_callback=None, selected_serial=None):
        super().__init__(parent)

        self.class_lock = str(class_lock).strip() if class_lock else None
        self.assign_callback = assign_callback
        self.selected_serial = selected_serial

        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle(
            "Registry Explorer"
            if not self.class_lock
            else f"Registry – {self.class_lock}"
        )
        self.setMinimumSize(900, 640)

        vcs = VaultCoreSingleton.get()
        self.registry_store = vcs.get_store("registry")

        self._build_ui()
        self._populate_tabs()

    # ---------------------------------------------------------
    # UI
    # ---------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Both entry points use this same widget. A constraint lock merely
        # hides the category controls instead of selecting another dialog.
        self.category_row = QWidget(self)
        category_layout = QHBoxLayout(self.category_row)
        category_layout.setContentsMargins(0, 0, 0, 0)
        category_layout.addWidget(QLabel("Category:"))
        self.class_combo = QComboBox()
        self.class_combo.addItems(self.get_live_constraint_classes())
        category_layout.addWidget(self.class_combo)
        self.category_row.setVisible(not bool(self.class_lock))
        layout.addWidget(self.category_row)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        button_row = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.edit_btn = QPushButton("Edit")
        self.del_btn = QPushButton("Delete")
        self.install_ssh_btn = QPushButton("Install SSH Key…")
        button_row.addWidget(self.add_btn)
        button_row.addWidget(self.edit_btn)
        button_row.addWidget(self.del_btn)
        button_row.addWidget(self.install_ssh_btn)
        button_row.addStretch()

        self.assign_btn = None
        if self.assign_callback:
            self.assign_btn = QPushButton("Assign to Agent")
            self.assign_btn.clicked.connect(self._assign)
            button_row.addWidget(self.assign_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        button_row.addWidget(self.close_btn)
        layout.addLayout(button_row)

        self.add_btn.clicked.connect(self._add)
        self.edit_btn.clicked.connect(self._edit)
        self.del_btn.clicked.connect(self._delete)
        self.install_ssh_btn.clicked.connect(self._install_ssh_key)
        self.class_combo.currentTextChanged.connect(self._on_class_changed)

    def get_live_constraint_classes(self):
        """Return manual registry categories that have both UI components."""
        resolver = ConstraintResolver()
        live = []
        for class_name in EDITOR_REGISTRY:
            if resolver.is_autogen(class_name):
                continue
            if not resolver.has_editor(class_name):
                continue
            if class_name not in PROVIDER_REGISTRY:
                continue
            live.append(class_name)
        return sorted(live)

    # ---------------------------------------------------------
    # Population and selection
    # ---------------------------------------------------------
    def _active_class(self):
        if self.class_lock:
            return self.class_lock
        value = self.class_combo.currentText().strip()
        return value or None

    def _populate_tabs(self):
        self.tabs.clear()
        class_name = self._active_class()
        self.install_ssh_btn.setVisible(class_name == "ssh")
        if not class_name:
            return

        list_widget = QListWidget()
        list_widget.itemDoubleClicked.connect(self._edit_via_double_click)
        self._populate_class(class_name, list_widget)
        self.tabs.addTab(list_widget, class_name.upper())
        self.tabs.setCurrentIndex(0)

    def _populate_class(self, class_name, list_widget):
        list_widget.clear()
        provider = PROVIDER_REGISTRY.get(class_name)
        if not provider:
            list_widget.addItem(f"❗ No provider for category: {class_name}")
            return

        header = "   |   ".join(str(value) for value in provider.get_columns())
        header_item = QListWidgetItem(header)
        header_item.setFlags(
            header_item.flags() & ~Qt.ItemFlag.ItemIsSelectable
        )
        header_item.setForeground(QColor(128, 128, 128))
        list_widget.addItem(header_item)

        namespace = self.registry_store.get_namespace(class_name)
        for serial, obj in namespace.items():
            row = provider.get_row(obj)
            item = QListWidgetItem("   |   ".join(str(value) for value in row))
            item.setData(Qt.ItemDataRole.UserRole, (class_name, serial))
            list_widget.addItem(item)
            if self.class_lock == class_name and serial == self.selected_serial:
                list_widget.setCurrentItem(item)
                list_widget.scrollToItem(item)

    def _on_class_changed(self, _class_name):
        if not self.class_lock:
            self._populate_tabs()

    def _on_tab_changed(self, index):
        if index < 0:
            return
        list_widget = self.tabs.widget(index)
        class_name = self._active_class()
        if list_widget and class_name:
            self._populate_class(class_name, list_widget)

    def _edit_via_double_click(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self._edit_existing(*data)

    def _current_selection(self):
        list_widget = self.tabs.currentWidget()
        item = list_widget.currentItem() if list_widget else None
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        return data if data else (None, None)

    # ---------------------------------------------------------
    # CRUD
    # ---------------------------------------------------------
    @staticmethod
    def _stamp_record(data, class_name, serial, *, created=False):
        now = datetime.utcnow().isoformat() + "Z"
        data["class"] = class_name
        data["serial"] = serial
        metadata = data.setdefault("meta", {})
        if created:
            metadata.setdefault("created", now)
            metadata.setdefault("version", 1)
        metadata["modified"] = now
        return data

    def _add(self):
        try:
            class_name = self._active_class()
            editor_class = EDITOR_REGISTRY.get(class_name)
            if not editor_class:
                QMessageBox.warning(
                    self, "Missing Editor", f"No editor for {class_name}"
                )
                return

            editor = editor_class(new_conn=True)
            if not editor.exec():
                return

            serial = editor.get_serial()
            data = editor.serialize()
            data["path"] = editor.get_directory_path()
            self._stamp_record(data, class_name, serial, created=True)

            namespace = deepcopy(self.registry_store.get_namespace(class_name))
            namespace[serial] = data
            if not self._commit_namespace(class_name, namespace):
                return
            self._populate_tabs()
        except Exception as error:
            emit_gui_exception_log("RegistryManagerDialog._add", error)

    def _edit(self):
        class_name, serial = self._current_selection()
        if serial:
            self._edit_existing(class_name, serial)

    def _edit_existing(self, class_name, serial):
        try:
            editor_class = EDITOR_REGISTRY.get(class_name)
            if not editor_class:
                QMessageBox.warning(
                    self, "Missing Editor", f"No editor for {class_name}"
                )
                return

            namespace = deepcopy(self.registry_store.get_namespace(class_name))
            current = namespace.get(serial)
            if not current:
                return

            editor = editor_class(new_conn=False)
            editor._load_data(current)
            if not editor.exec():
                return

            updated = editor.serialize()
            updated["path"] = editor.get_directory_path()
            # Keep creation/version metadata while advancing modification time.
            updated["meta"] = dict(current.get("meta", {}))
            self._stamp_record(updated, class_name, serial)
            namespace[serial] = updated
            if not self._commit_namespace(class_name, namespace):
                return
            self._populate_tabs()
        except Exception as error:
            emit_gui_exception_log("RegistryManagerDialog._edit_existing", error)

    def _delete(self):
        class_name, serial = self._current_selection()
        if not serial:
            return

        confirmed = QMessageBox.question(
            self,
            "Delete?",
            f"Delete resource '{serial}' from {class_name}?",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return

        namespace = deepcopy(self.registry_store.get_namespace(class_name))
        namespace.pop(serial, None)
        if not self._commit_namespace(class_name, namespace):
            return
        self._populate_tabs()

    def _commit_namespace(self, class_name, namespace):
        """Do not display a successful CRUD operation after a rejected commit."""
        try:
            accepted = self.registry_store.set_namespace(class_name, namespace)
        except Exception:
            accepted = False
        if not accepted:
            QMessageBox.warning(
                self, "Registry Save Failed",
                "The registry change was not accepted. Your previous registry "
                "state has been restored. Review the entry and try again.",
            )
            return False
        return True

    def _install_ssh_key(self):
        """Open the dedicated Vault-backed installer for the SSH category."""
        if self._active_class() != "ssh":
            return
        _class_name, serial = self._current_selection()
        from matrix_gui.registry.ssh_key_install_dialog import (
            VaultSSHKeyInstallDialog,
        )

        dialog = VaultSSHKeyInstallDialog(self, selected_serial=serial)
        dialog.exec()
        if dialog.updated_profile:
            self._populate_tabs()

    # ---------------------------------------------------------
    # Constraint assignment
    # ---------------------------------------------------------
    def _assign(self):
        class_name, serial = self._current_selection()
        if serial and self.assign_callback:
            self.assign_callback(class_name, serial)
            self.accept()

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QDialog, QDialogButtonBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QCheckBox, QComboBox
)


class ListEditorDialog(QDialog):
    """Generic dialog for editing structured lists with type-aware columns (v2)."""
    def __init__(self, title, columns, data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.columns = []
        self.column_options = {}   # for dropdown support
        self.data = data or []

        # Normalize column definitions
        for col in columns:
            if isinstance(col, tuple):
                name, opts = col[0], col[1]
                self.columns.append(str(name))
                self.column_options[name] = opts
            else:
                self.columns.append(str(col))

        # Auto-detect boolean columns
        self.boolean_cols = {
            i for i, name in enumerate(self.columns)
            if name.lower() in (
                "recursive", "watch_dirs", "watch_files",
                "enabled", "active", "auto", "run_on_boot"
            )
        }

        layout = QVBoxLayout(self)

        # Table setup
        self.table = QTableWidget(len(self.data), len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        self.table.horizontalHeader().setStyleSheet(
            "QHeaderView::section { background-color: #777777; color: #fff; font-weight: bold; padding: 6px 8px; }"
        )

        # Populate
        for row_idx, row in enumerate(self.data):
            if not isinstance(row, dict):
                row = {self.columns[0]: str(row)}
            for col_idx, name in enumerate(self.columns):
                val = row.get(name, "")
                if col_idx in self.boolean_cols:
                    self._set_checkbox(row_idx, col_idx, self._truthy(val))
                elif name in self.column_options:
                    self._set_dropdown(row_idx, col_idx, val, self.column_options[name])
                else:
                    self.table.setItem(row_idx, col_idx, QTableWidgetItem(str(val)))

        # Buttons
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Row")
        del_btn = QPushButton("Delete Row")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        layout.addLayout(btn_row)
        add_btn.clicked.connect(self._add_row)
        del_btn.clicked.connect(self._del_row)

        # Save / Cancel
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------
    def _truthy(self, v):
        """Normalize truthy strings/bools."""
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        return s in ("1", "true", "yes", "on")

    def _set_checkbox(self, row, col, checked):
        box = QCheckBox()
        box.setChecked(bool(checked))
        box.setStyleSheet("margin-left:20px;")
        self.table.setCellWidget(row, col, box)

    def _set_dropdown(self, row, col, value, options):
        box = QComboBox()
        box.addItems([str(o) for o in options])
        if value in options:
            box.setCurrentText(str(value))
        self.table.setCellWidget(row, col, box)

    def _add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        # init checkboxes and dropdowns
        for col_idx, name in enumerate(self.columns):
            if col_idx in self.boolean_cols:
                self._set_checkbox(r, col_idx, False)
            elif name in self.column_options:
                self._set_dropdown(r, col_idx, "", self.column_options[name])

    def _del_row(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def get_data(self):
        results = []
        for r in range(self.table.rowCount()):
            row_dict = {}
            for c, name in enumerate(self.columns):
                widget = self.table.cellWidget(r, c)
                if c in self.boolean_cols and isinstance(widget, QCheckBox):
                    row_dict[name] = widget.isChecked()
                elif isinstance(widget, QComboBox):
                    row_dict[name] = widget.currentText()
                else:
                    item = self.table.item(r, c)
                    row_dict[name] = (item.text().strip() if item else "")
            results.append(row_dict)
        return results


class ListEditorMixin:
    """Mixin for agents that need editable list sections in config editors (v2)."""

    def _build_list_section(self, label, data, columns, attr_name):
        setattr(self, f"_{attr_name}_data", data)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        list_widget = QListWidget()
        list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

        # Summary fill
        for row in data or []:
            if isinstance(row, dict):
                summary = " | ".join(f"{k}:{v}" for k, v in row.items())
            else:
                summary = str(row)
            list_widget.addItem(summary)

        layout.addWidget(list_widget)

        # Edit button
        btn_row = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        btn_row.addWidget(edit_btn)
        layout.addLayout(btn_row)

        # Hook dialog
        edit_btn.clicked.connect(lambda: self._open_list_editor(label, columns, list_widget, attr_name))
        list_widget.itemDoubleClicked.connect(lambda _: self._open_list_editor(label, columns, list_widget, attr_name))

        self.layout.addRow(QLabel(label), container)
        setattr(self, attr_name, list_widget)

    def _open_list_editor(self, title, columns, list_widget, attr_name):
        current = getattr(self, f"_{attr_name}_data", []) or []
        dlg = ListEditorDialog(title, columns, current, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_data = dlg.get_data()
            setattr(self, f"_{attr_name}_data", new_data)
            list_widget.clear()
            for row in new_data:
                if isinstance(row, dict):
                    summary = " | ".join(f"{k}:{v}" for k, v in row.items())
                else:
                    summary = str(row)
                list_widget.addItem(summary)

    def _collect_list_data(self, attr_name):
        return getattr(self, f"_{attr_name}_data", [])

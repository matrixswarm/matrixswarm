import uuid
from PyQt5.QtWidgets import QDialog, QInputDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QListWidget, QHBoxLayout, QMessageBox, QApplication
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509 import NameOID, Name
from cryptography.x509.oid import ExtendedKeyUsageOID
from cryptography import x509
from datetime import datetime, timedelta
from matrix_gui.core.event_bus import EventBus
from matrix_gui.modules.vault.crypto.cert_factory import manufacture_cert_set_for_tags
from matrix_gui.modules.vault.utils.utils import sync_spki_pin_to_cert

class CertManagerDialog(QDialog):
    def __init__(self, vault_data=None, password=None, vault_path=None, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Cert Manager")
        self.setMinimumWidth(480)
        self.vault_data = vault_data or {}
        self.password = password
        self.vault_path = vault_path

        self.cert_store = self.vault_data.setdefault("vault", {}).setdefault("cert_store", {})

        layout = QVBoxLayout()

        self.label = QLabel("Enter label to generate new CERT_ID")
        layout.addWidget(self.label)

        self.label_input = QLineEdit()
        layout.addWidget(self.label_input)

        #self.generate_btn = QPushButton("Generate Cert Pair")
        #self.generate_btn.clicked.connect(self.generate_cert)
        #layout.addWidget(self.generate_btn)

        self.create_set_btn = QPushButton("Create Cert Set (Batch by Tag)")
        self.create_set_btn.clicked.connect(self.create_cert_set_by_tag)
        layout.addWidget(self.create_set_btn)

        self.cert_list = QListWidget()
        layout.addWidget(self.cert_list)
        self.cert_list.itemClicked.connect(self.copy_cert_id)

        btn_row = QHBoxLayout()
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self.delete_cert)
        btn_row.addStretch()
        btn_row.addWidget(self.delete_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)
        self.populate_cert_list()

    def generate_cert(self):
        label = self.label_input.text().strip()
        if not label:
            QMessageBox.warning(self, "Missing Label", "Please enter a label for the cert ID.")
            return

        cert_id = f"CERT_ID_{uuid.uuid4().hex[:8]}"

        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )

        subject = issuer = Name([
            x509.NameAttribute(NameOID.COMMON_NAME, label or cert_id)
        ])

        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.utcnow()
        ).not_valid_after(
            datetime.utcnow() + timedelta(days=3650)
        ).add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        ).add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        ).sign(key, algorithm=hashes.SHA256())

        privkey_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ).decode()

        cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()

        self.cert_store[cert_id] = {
            "label": label,
            "cert": cert_pem,
            "key": privkey_pem
        }
        self.label_input.clear()
        self.emit_vault_update()
        self.populate_cert_list()

    def create_cert_set_by_tag(self):
        # Prompt for comma-separated tags
        tags_str, ok = QInputDialog.getText(self, "Cert Tags", "Enter security-tags/roles (comma separated):")
        if not ok or not tags_str.strip():
            return
        tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]
        if not tags:
            QMessageBox.warning(self, "No Tags", "No tags entered.")
            return

        # Optionally, prompt for an operator pubkey (for remote_pubkey field)
        operator_pubkey, _ = QInputDialog.getMultiLineText(
            self, "Operator Pubkey (Optional)", "Paste operator (GUI) pubkey (PEM):", ""
        )
        operator_pubkey = operator_pubkey.strip() or None
        # Generate cert set
        cert_set = manufacture_cert_set_for_tags(tags, operator_pubkey)
        # Store each cert in cert_store, labeled by tag
        for tag, info in cert_set.items():
            cert_id = f"CERT_ID_{tag}_{uuid.uuid4().hex[:6]}"
            self.cert_store[cert_id] = {
                "label": tag,
                "cert": info["cert"],
                "key": info["privkey"],
                "remote_pubkey": info["remote_pubkey"],
            }

        self.emit_vault_update()
        self.populate_cert_list()
        QMessageBox.information(self, "Cert Set Created", f"Cert set for tags: {', '.join(tags)} created.")

    def populate_cert_list(self):
        self.cert_list.clear()
        for cert_id, data in self.cert_store.items():
            label = data.get("label", "")
            self.cert_list.addItem(f"{cert_id}    [{label}]")

    def copy_cert_id(self, item):
        cert_id = item.text().split()[0].strip()
        QApplication.clipboard().setText(cert_id)
        QMessageBox.information(self, "Cert ID Copied", f"{cert_id} copied to clipboard.")

    def delete_cert(self):
        selected_item = self.cert_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "No Selection", "Select a cert to delete.")
            return
        cert_id = selected_item.text().split()[0].strip()
        if cert_id in self.cert_store:
            del self.cert_store[cert_id]
            self.emit_vault_update()
            self.populate_cert_list()

    def emit_vault_update(self):
        sync_spki_pin_to_cert(self.vault_data)
        EventBus.emit(
            "vault.update",
            vault_path=self.vault_path,
            password=self.password,
            data=self.vault_data
        )

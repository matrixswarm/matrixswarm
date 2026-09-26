"""Prepare a MatrixD SSH session off the GUI thread; transfer only after exit."""
from copy import deepcopy
import threading
from PyQt6.QtCore import QThread, pyqtSignal
from matrix_gui.modules.railgun.ssh_support import connect_ssh_profile
from matrix_gui.modules.railgun.remote_shell import verify_remote_matrixd_stdin, send_boot_envelope
from matrix_gui.util.exception_diagnostics import log_exception_locations


class ControlSessionWorker(QThread):
    status = pyqtSignal(str)

    def __init__(self, profile, command, action, bundle, key, parent=None):
        super().__init__(parent)
        self.profile = deepcopy(profile)
        self.command, self.action = command, action
        self.bundle, self.key = deepcopy(bundle), key
        self.cancelled = threading.Event()
        self.result = None
        self.error = None
        self.dispatched = False

    def cancel(self):
        self.cancelled.set()

    def check_cancel(self):
        if self.cancelled.is_set():
            raise InterruptedError()

    def run(self):
        client = channel = None
        try:
            self.check_cancel()
            self.status.emit("Connecting to SSH…")
            client, _ = connect_ssh_profile(self.profile)
            self.check_cancel()
            if self.action != "stop":
                self.status.emit("Verifying sealed-stream capability…")
                verify_remote_matrixd_stdin(client)
                self.check_cancel()
            channel = client.get_transport().open_session(timeout=15)
            channel.settimeout(1)
            self.check_cancel()
            self.dispatched = True
            channel.exec_command(self.command)
            self.check_cancel()
            if self.action != "stop":
                self.status.emit("Uploading sealed boot envelope…")
                send_boot_envelope(channel, self.bundle, self.key, check_cancel=self.check_cancel)
            self.check_cancel()
            self.result = (client, channel)
            client = channel = None
        except Exception as error:
            log_exception_locations("MatrixD control preparation", error)
            outcome = "Remote outcome unknown; inspect the target before a new operation." if self.dispatched else "No remote command dispatched."
            self.error = f"[ERROR] Local operation stopped ({type(error).__name__}). {outcome}"
        finally:
            for resource in (channel, client):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception as error:
                        log_exception_locations("MatrixD preparation cleanup", error)
            self.profile = self.bundle = self.key = None

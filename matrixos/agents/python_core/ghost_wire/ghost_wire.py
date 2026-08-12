# Authored by Daniel F MacDonald and ChatGPT aka The Generals
import sys
import os
for env_name in ("SITE_ROOT", "AGENT_PATH"):
    env_path = os.getenv(env_name)
    if env_path and env_path not in sys.path:
        sys.path.insert(0, env_path)

import pwd
import time
import json
import hashlib
import subprocess
import threading
from datetime import datetime
from collections import OrderedDict

try:
    import inotify.adapters
except ImportError:
    inotify = None
from core.python_core.boot_agent import BootAgent
from core.python_core.utils.swarm_sleep import interruptible_sleep
from core.python_core.mixin.reflex_alert import ReflexAlertMixin
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject

class Agent(BootAgent, ReflexAlertMixin):
    def __init__(self):
        super().__init__()
        self.AGENT_VERSION = "1.3.1"
        self.sessions = {}
        self.file_alerts = {}  # (path -> timestamp)
        self.command_hashes = OrderedDict()
        self.alert_hashes = OrderedDict()
        self._file_alert_lock = threading.Lock()
        self._watch_thread = None
        self._started_at = time.time()
        self._active_users_seen_once = False

        cfg = self.tree_node.get("config", {})

        self.report_role = cfg.get("report_to_role") or "hive.forensics.data_feed"
        self.alert_role = cfg.get("alert_to_role") or cfg.get("alert_role") or "hive.rpc"
        self.alert_to_role = self.alert_role
        self.alert_fallback_roles = self._string_list(cfg.get("alert_fallback_roles", ["hive.rpc"]))

        self.tick_rate = self._positive_int(cfg.get("tick_rate", 5), default=5)
        self.alert_cooldown = self._positive_int(cfg.get("alert_cooldown", 60), default=60)
        self.startup_quiet_seconds = self._non_negative_int(cfg.get("startup_quiet_seconds", 120), default=120)
        self.signout_grace_seconds = self._non_negative_int(cfg.get("signout_grace_seconds", 30), default=30)
        self.max_command_hashes = self._positive_int(cfg.get("max_command_hashes", 5000), default=5000)
        self.max_session_commands = self._positive_int(cfg.get("max_session_commands", 2000), default=2000)
        self.baseline_shell_history = self._bool(cfg.get("baseline_shell_history", True), default=True)
        self.alert_on_signin = self._bool(cfg.get("alert_on_signin", False), default=False)
        self.alert_on_signout = self._bool(cfg.get("alert_on_signout", False), default=False)
        self.alert_on_file_event = self._bool(cfg.get("alert_on_file_event", False), default=False)
        self.alert_on_privileged_signin = self._bool(cfg.get("alert_on_privileged_signin", True), default=True)
        self.alert_on_sensitive_file_read = self._bool(cfg.get("alert_on_sensitive_file_read", True), default=True)
        self.alert_on_file_write = self._bool(cfg.get("alert_on_file_write", True), default=True)
        self.alert_on_suspicious_command = self._bool(cfg.get("alert_on_suspicious_command", True), default=True)
        self.install_prompt_command = self._bool(cfg.get("install_prompt_command", False), default=False)
        self.privileged_users = set(self._string_list(cfg.get("privileged_users", ["root"])))
        self.sensitive_read_paths = self._string_list(cfg.get("sensitive_read_paths", ["/etc/shadow", "/root/.ssh"]))
        self.prompt_paths = [
            os.path.expandvars(os.path.expanduser(str(path).strip()))
            for path in cfg.get("prompt_paths", ["/etc/bash.bashrc", "~/.bashrc"])
            if str(path).strip()
        ]
        self.command_patterns = cfg.get("command_patterns", [
            "rm -rf", "scp", "curl", "wget", "nano /etc", "vi /etc", "vim /etc",
            "sudo", "su", "chmod 777", "systemctl stop", "service stop"
        ])
        self.command_patterns = [
            str(pattern).strip().casefold()
            for pattern in self.command_patterns
            if str(pattern).strip()
        ]

        self.watch_paths = [
            str(path).strip()
            for path in cfg.get("watch_paths", ["/etc/passwd", "/etc/shadow", "/root/.ssh", "/home", "/var/www"])
            if str(path).strip()
        ]
        self.session_dir = os.path.join(self.path_resolution["comm_path"],
                                        self.command_line_args.get("universal_id", "ghostwire"), "sessions")
        os.makedirs(self.session_dir, exist_ok=True)
        self._emit_beacon = self.check_for_thread_poke("worker", timeout=30, emit_to_file_interval=10)

    def worker_pre(self):
        if self.install_prompt_command:
            self.enforce_prompt_command_once()
        else:
            self.log("[GHOSTWIRE][PROMPT] install_prompt_command disabled; leaving shell startup files unchanged.")

        if self.watch_paths and not self._watch_thread:
            self._watch_thread = threading.Thread(target=self.watch_file_changes, daemon=True)
            self._watch_thread.start()

    def post_boot(self):
        self.log(f"{self.NAME} v{self.AGENT_VERSION} – shadow tracker engaged.")

    def worker(self, config: dict = None, identity: IdentityObject = None):

        self.track_active_users()
        self.poll_shell_history()
        interruptible_sleep(self, self.tick_rate)

    @staticmethod
    def _positive_int(value, default):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    @staticmethod
    def _non_negative_int(value, default):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if value >= 0 else default

    @staticmethod
    def _bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _string_list(value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return [str(item).strip() for item in value if str(item).strip()]

    def _in_startup_quiet(self):
        return time.time() - self._started_at < self.startup_quiet_seconds

    def _alert_roles(self):
        roles = []
        for role in [self.alert_role, *self.alert_fallback_roles]:
            if role and role not in roles:
                roles.append(role)
        return roles

    def _is_sensitive_read_path(self, full_path):
        full_path = os.path.abspath(full_path)
        for path in self.sensitive_read_paths:
            path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
            if full_path == path or full_path.startswith(path.rstrip(os.sep) + os.sep):
                return True
        return False

    def _should_emit_alert(self, key, cooldown=None):
        now = time.time()
        cooldown = self.alert_cooldown if cooldown is None else cooldown
        last = self.alert_hashes.get(key, 0)
        if now - last <= cooldown:
            return False
        self.alert_hashes[key] = now
        if len(self.alert_hashes) > self.max_command_hashes:
            self.alert_hashes.popitem(last=False)
        return True

    def enforce_prompt_command_once(self):
        for path in self.prompt_paths:
            try:
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if "PROMPT_COMMAND" in content and "history -a" in content:
                        self.log(f"[GHOSTWIRE][PROMPT] Already present in {path}")
                        continue
                with open(path, "a", encoding="utf-8") as f:
                    f.write("\n# Added by GhostWire for real-time history logging\n")
                    f.write("export PROMPT_COMMAND='history -a'\n")
                self.log(f"[GHOSTWIRE][PROMPT] Injected PROMPT_COMMAND into {path}")
            except Exception as e:
                self.log(f"[GHOSTWIRE][PROMPT][ERROR] {path}: {e}")

    def send_ghost_alert(self, message, level="warning", cause="ghost-wire", key=None, cooldown=None):
        if key and not self._should_emit_alert(key, cooldown=cooldown):
            return False
        return self.alert_operator(
            message=message,
            level=level,
            cause=cause,
            roles=self._alert_roles() or None,
        )

    def track_active_users(self):
        try:
            output = subprocess.check_output(["who"], text=True)
            initial_scan = not self._active_users_seen_once
            current_users = {}
            for line in output.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 2:
                    user, tty = parts[0], parts[1]
                    current_users[user] = tty

                    if user not in self.sessions:
                        # SIGN-IN
                        self.sessions[user] = {
                            "tty": tty,
                            "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "commands": [],
                            "files_touched": [],
                            "last_seen": time.time()
                        }
                        msg = f"👤 User Signed In\n• User: {user}\n• TTY: {tty}\n• Time: {self.sessions[user]['start_time']}"

                        self.log(f"[GHOSTWIRE][SIGNIN] {msg}")
                        should_alert_signin = self.alert_on_signin or (
                            self.alert_on_privileged_signin and user in self.privileged_users
                        )
                        if should_alert_signin and not initial_scan:
                            self.send_ghost_alert(
                                msg,
                                level="warning" if user in self.privileged_users else "info",
                                cause="ghost-wire.signin",
                                key=f"signin:{user}:{tty}",
                            )
                        session_path = os.path.join(self.session_dir, user, f"{self.today()}.log")
                        os.makedirs(os.path.dirname(session_path), exist_ok=True)
                        if os.path.exists(session_path):
                            try:
                                with open(session_path, "r", encoding="utf-8") as f:
                                    loaded = json.load(f)
                                    self.sessions[user]["commands"] = loaded.get("commands", [])
                                    self.sessions[user]["history_line_count"] = loaded.get("history_line_count", 0)
                            except Exception as e:
                                self.log(f"[GHOSTWIRE][LOAD] Failed to reload session for {user}: {e}")

                    else:
                        self.sessions[user]["last_seen"] = time.time()
                        self.sessions[user].pop("missing_since", None)

            # SIGN-OUT
            for user in list(self.sessions.keys()):
                if user not in current_users:
                    missing_since = self.sessions[user].setdefault("missing_since", time.time())
                    if time.time() - missing_since < self.signout_grace_seconds:
                        continue
                    msg = (
                        f"👋 User Signed Out\n"
                        f"• User: {user}\n"
                        f"• Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"🔒 Surveillance interrupted.\n"
                        f"🚨 Cuffs were **not** applied.\n"
                        f"📡 Tagging for re-entry tracking..."
                    )

                    self.log(f"[GHOSTWIRE][SIGNOUT] {msg}")
                    if self.alert_on_signout and not self._in_startup_quiet():
                        self.send_ghost_alert(
                            msg,
                            level="info",
                            cause="ghost-wire.signout",
                            key=f"signout:{user}",
                        )
                    del self.sessions[user]
            self._active_users_seen_once = True

        except Exception as e:
            self.log(f"[GHOSTWIRE][ERROR] Failed to track users: {e}")

    def watch_file_changes(self):
        if inotify is None:
            self.log("[GHOSTWIRE][INOTIFY] Python inotify package unavailable; file monitor disabled.")
            return

        try:
            i = inotify.adapters.Inotify()
        except Exception as e:
            self.log(f"[GHOSTWIRE][INOTIFY][ERROR] Failed to initialize inotify: {e}")
            return

        watch_count = 0
        for path in self.watch_paths:
            try:
                if not os.path.exists(path):
                    self.log(f"[GHOSTWIRE][INOTIFY][SKIP] Missing path: {path}")
                    continue
                i.add_watch(path)
                watch_count += 1
            except Exception as e:
                self.log(f"[GHOSTWIRE][INOTIFY][ERROR] {path}: {e}")

        if watch_count == 0:
            self.log("[GHOSTWIRE][INOTIFY] No valid watch paths; file monitor disabled.")
            return

        self.log(f"[GHOSTWIRE][INOTIFY] Monitoring: {', '.join(self.watch_paths)}")

        try:
            for event in i.event_gen(yield_nones=False):
                (_, type_names, path, filename) = event
                full_path = os.path.join(path, filename) if filename else path
                now = time.strftime('%Y-%m-%d %H:%M:%S')

                # Message format for logs or alert
                msg = (
                    f"👁️ Inotify Trigger\n"
                    f"• Path: {full_path}\n"
                    f"• Event: {', '.join(type_names)}\n"
                    f"• Time: {now}"
                )

                # 🛡 Filter out repeated reads unless it's a first access
                if "IN_OPEN" in type_names or "IN_ACCESS" in type_names:
                    sensitive_read = self._is_sensitive_read_path(full_path)
                    if self._in_startup_quiet() and not sensitive_read:
                        continue
                    if self.should_alert_path(full_path):
                        self.log(f"[GHOSTWIRE][INOTIFY] {msg}")
                        if self.alert_on_file_event or (self.alert_on_sensitive_file_read and sensitive_read):
                            self.send_ghost_alert(
                                msg,
                                level="critical" if sensitive_read else "warning",
                                cause="ghost-wire.inotify.sensitive-read" if sensitive_read else "ghost-wire.inotify.read",
                                key=f"file-read:{full_path}",
                            )

                    continue  # don't alert twice if IN_CLOSE_NOWRITE follows

                # 🔥 But always alert on write/delete
                if "IN_CLOSE_WRITE" in type_names or "IN_DELETE" in type_names:
                    self.log(f"[GHOSTWIRE][INOTIFY] {msg}")
                    if self.alert_on_file_event or self.alert_on_file_write:
                        self.send_ghost_alert(
                            msg,
                            level="critical",
                            cause="ghost-wire.inotify.write",
                            key=f"file-write:{full_path}:{','.join(type_names)}",
                        )

        except Exception as e:
            self.log(f"[GHOSTWIRE][INOTIFY][ERROR] Monitor stopped: {e}")


    def should_alert_path(self, full_path):
        now = time.time()
        with self._file_alert_lock:
            last = self.file_alerts.get(full_path, 0)
            if now - last > self.alert_cooldown:
                self.file_alerts[full_path] = now
                if len(self.file_alerts) > 5000:
                    cutoff = now - (self.alert_cooldown * 2)
                    self.file_alerts = {
                        path: ts for path, ts in self.file_alerts.items()
                        if ts >= cutoff
                    }
                return True
            return False

    def resolve_history_path(self, user):
        try:
            user_info = pwd.getpwnam(user)
            home = user_info.pw_dir
            shell = user_info.pw_shell
            if "bash" in shell:
                return os.path.join(home, ".bash_history")
            elif "zsh" in shell:
                return os.path.join(home, ".zsh_history")
            elif "fish" in shell:
                return os.path.join(home, ".config", "fish", "fish_history")
            else:
                self.log(f"[GHOSTWIRE][HISTORY] Unsupported shell for user {user}: {shell}")
                return None
        except Exception as e:
            self.log(f"[GHOSTWIRE] Failed to resolve history path for {user}: {e}")
            return None

    def poll_shell_history(self):
        for user, session in self.sessions.items():
            history_path = self.resolve_history_path(user)
            if not history_path or not os.path.exists(history_path):
                self.log(f"[GHOSTWIRE] No shell history found for {user} — logging login only.")
                self.persist(user, self.sessions[user])  # Still persist session
                continue
            last_seen_cmd = session.get("last_command_timestamp", 0)
            if time.time() - last_seen_cmd > 600 and (not session.get("last_prompt_log") or time.time() - session["last_prompt_log"] > 600):
                self.log(f"[GHOSTWIRE][{user}] 🕒 History inactive >10 min. May need PROMPT_COMMAND='history -a'")
                session["last_prompt_log"] = time.time()

            if os.path.exists(history_path):
                try:
                    with open(history_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.read().splitlines()
                    prior_commands = set(session.get("commands", []))
                    last_line_count = session.get("history_line_count", 0)

                    if (
                        self.baseline_shell_history
                        and not session.get("history_baselined")
                        and not prior_commands
                        and not last_line_count
                    ):
                        session["history_line_count"] = len(lines)
                        session["history_baselined"] = True
                        session["last_prompt_log"] = time.time()
                        self.log(
                            f"[GHOSTWIRE][{user}] Baselined shell history at {len(lines)} line(s); "
                            "only new commands will be inspected."
                        )
                        self.persist(user, session)
                        continue

                    if self.baseline_shell_history and isinstance(last_line_count, int) and last_line_count > len(lines):
                        session["history_line_count"] = len(lines)
                        session["history_baselined"] = True
                        self.log(
                            f"[GHOSTWIRE][{user}] History file shrank; reset baseline to {len(lines)} line(s)."
                        )
                        self.persist(user, session)
                        continue

                    if isinstance(last_line_count, int) and 0 < last_line_count <= len(lines):
                        new_commands = lines[last_line_count:]
                    elif not prior_commands:
                        new_commands = lines
                    else:
                        new_commands = [cmd for cmd in lines if cmd not in prior_commands]

                    for cmd in new_commands:
                        if not cmd:
                            continue
                        session["commands"].append(cmd)
                        session["last_command_timestamp"] = time.time()

                        self.log(f"[GHOSTWIRE][{user}] {cmd}")
                        cmd_hash = self.hash_command(cmd)
                        if cmd_hash not in self.command_hashes:
                            self.remember_command(cmd_hash)
                            if self.is_suspicious(cmd):
                                self.alert(user, cmd)
                    session["history_line_count"] = len(lines)
                    session["history_baselined"] = True
                    if len(session["commands"]) > self.max_session_commands:
                        session["commands"] = session["commands"][-self.max_session_commands:]
                    self.persist(user, session)
                except Exception as e:
                    self.log(f"[GHOSTWIRE][{user}][ERROR] {e}")

    def is_suspicious(self, cmd):
        cmd = str(cmd).casefold()
        return any(pattern in cmd for pattern in self.command_patterns)

    def alert(self, user, cmd):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        msg = (
            f"🕶️ Suspicious Command Detected\n"
            f"• User: {user}\n"
            f"• Command: {cmd}\n"
            f"• Time: {timestamp}"
        )

        self.log(f"[GHOSTWIRE][ALERT] {msg}")
        if self.alert_on_suspicious_command:
            self.send_ghost_alert(
                msg,
                level="critical",
                cause="ghost-wire.suspicious-command",
                key=f"suspicious:{user}:{self.hash_command(cmd)}",
            )

        # Also send a structured data report for the detective
        self.send_data_report(
            status="suspicious_command",
            severity="WARNING",
            details=f"User '{user}' executed command: {cmd}"
        )

    def hash_command(self, cmd):
        return hashlib.sha256(cmd.strip().encode()).hexdigest()

    def remember_command(self, cmd_hash):
        self.command_hashes[cmd_hash] = time.time()
        if len(self.command_hashes) > self.max_command_hashes:
            self.command_hashes.popitem(last=False)

    def persist(self, user, session):
        date_str = self.today()
        path = os.path.join(self.session_dir, user)
        os.makedirs(path, exist_ok=True)
        fpath = os.path.join(path, f"{date_str}.log")
        tmp_path = f"{fpath}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(session, f, indent=2)
            os.replace(tmp_path, fpath)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            finally:
                raise

    def today(self):
        return datetime.now().strftime("%Y-%m-%d")

    def send_data_report(self, status, severity, details=""):
        """Sends a structured data packet for forensic analysis."""
        if not self.report_role:
            return

        report_nodes = self.get_nodes_by_role(self.report_role)
        if not report_nodes:
            return

        # Wrapper packet
        pk1 = self.get_delivery_packet("standard.command.packet")
        pk1.set_data({"handler": "cmd_ingest_status_report"})

        # Structured event payload
        pk2 = self.get_delivery_packet("standard.status.event.packet")
        pk2.set_data({
            "source_agent": self.command_line_args.get("universal_id"),
            "service_name": "ghost_wire",  # A new service name for this event type
            "status": status,
            "details": details,
            "severity": severity,
        })

        pk1.set_packet(pk2, "content")

        for node in report_nodes:
            try:
                uid = node.get("universal_id")
                if not uid:
                    continue
                self.pass_packet(pk1, uid)
            except Exception as e:
                self.log(f"[GHOSTWIRE][REPORT][ERROR] Failed to report to {node}: {e}")

if __name__ == "__main__":
    agent = Agent()
    agent.boot()
# Authored by Daniel F MacDonald and ChatGPT aka The Generals
# Gemini, code enhancements and Docstrings
import sys
import os
import copy
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

# ╔════════════════════════════════════════════════════════╗
# ║                   🧠 MATRIX AGENT 🧠                   ║
# ║   Central Cortex · Tree Dispatcher · Prime Director    ║
# ║     Forged in the core of Hive Zero | v3.0 Directive   ║
# ║  Accepts: inject / replace / resume / kill / propagate ║
# ╚════════════════════════════════════════════════════════╝
# ╔═════════════════════════════════════════════════════════════╗
# ║   THE SWARM IS ALIVE — AGENTS COMING OUT OF EVERY ORIFICE  ║
# ║       Please take as many as your system can support        ║
# ╚═════════════════════════════════════════════════════════════╝

import time
from pathlib import Path
if os.name == "posix":
    try:
        import inotify.adapters
    except ImportError:
        inotify = None
        print("[COMM-WATCHER] inotify not installed, cannot use inotify watchers.")
else:
    inotify = None

import hashlib
import json
import base64
import secrets
import shlex
import shutil
from Crypto.PublicKey import RSA
import subprocess
import threading
import stat

# Assuming self.matrix_priv is currently a string with PEM content:
from core.python_core.boot_agent import BootAgent
from core.python_core.tree_parser import TreeParser
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.class_lib.packet_delivery.utility.security.unwrap_secure_packet import unwrap_secure_packet
from core.python_core.mixin.reap_status_handler import ReapStatusHandlerMixin
from core.python_core.utils.crypto_utils import encrypt_with_ephemeral_aes,  sign_data, pem_fix
from core.python_core.class_lib.directive.boot_directive_info import BootDirectiveInfo
from core.python_core.class_lib.time_utils.heartbeat_checker import check_heartbeats
from core.python_core.utils.analyze_spawn_records import analyze_spawn_records
from core.python_core.utils.swarm_sleep import interruptible_sleep
from core.python_core.safe_paths import runtime_directory, child_directory, open_beneath
from core.python_core.swarm_processes import get_all_swarm_agent_info
from core.python_core.reap_revision import (reap_mutation, note_reap_save_attempt, note_reap_save_success,
                                             commit_reap_mutation, defer_reap_side_effect, defer_reap_abort)


class HotswapChallengeError(ValueError):
    """A source command has no valid challenge for this Matrix process."""


class Agent(BootAgent, ReapStatusHandlerMixin):
    """The root agent and central authority of the MatrixSwarm.
    As the first agent spawned by the bootloader, the Matrix agent acts as
    the "queen" of the hive. It is responsible for establishing the swarm's
    chain of trust, spawning all top-level agents defined in the directive,
    and serving as a central hub for critical commands and state information.
    """
    commit_reap_mutation = commit_reap_mutation
    defer_reap_side_effect = defer_reap_side_effect
    defer_reap_abort = defer_reap_abort

    def __init__(self):
        """Initializes the root of the swarm.
        This method is the first to run after the bootloader. It decrypts the
        master vault and establishes the foundational cryptographic context.
        Its own keys are the master keys used to sign the identities of all
        other agents in the swarm.
        """
        super().__init__()


        try:
            self.AGENT_VERSION = "2.0.0"
            self._agent_tree_master = None
            self._hotswap_lock = threading.Lock()
            self._hotswap_pending = set()
            self._hotswap_transfers = {}
            self._hotswap_closed = {}
            self._hotswap_challenges = {}

            self.boot_directive_info = BootDirectiveInfo(self.security_box)

            self.meta = {}
            self._last_assassin_run = 0

            try:
                #{"boot_directives_path": config["boot_directives"], "boot_directive_filename": directive_file, "boot_directive_encrypted":is_directive_encrypted, "boot_directive_swarm_key": boot_directive_swarm_key}
                if 'boot_directive_encrypted' in self.security_box:
                    self.log(f"boot directive path: {self.security_box.get('boot_directives_path', {})}")
                    self.log(f"boot directive filename: {self.security_box.get('boot_directive_filename', {})}")
                    self.log(f"boot directive encrypted: {bool(self.security_box['boot_directive_encrypted'])}")
                else:
                    self.log("boot directive: legacy file metadata not supplied")
                self.log(f"agent install path: {self.path_resolution['agent_path']}")
                self.log(f"install path: {self.path_resolution['install_path']}")

                #self.log(f"boot directive swarm key: {self.security_box.get('boot_directive_swarm_key', {})}")
                #self.log(f"real swarm_key: {self.swarm_key}")
            except Exception as e:
                self.log("boot directive path and or filename not defined", error=e)

            #no need to delegate any agents at start
            self._last_tree_verify = time.time()
            self._last_consciousness_scan = time.time()
            self.tree_path = os.path.join( self.path_resolution["comm_path_resolved"], "directive", "agent_tree_master.json")

            self.tree_path_dict = {
                 "path": self.path_resolution["comm_path"],
                 "address": self.command_line_args.get("universal_id"),
                 "drop": "directive",
                 "name": "agent_tree_master.json"
            }

            # make sure signing keys are loaded BEFORE seeding
            self._signing_keys = self.tree_node.get('config', {}).get('security', {}).get('signing', {})
            self._has_signing_keys = self._signing_keys.get('privkey', False) and self._signing_keys.get('remote_pubkey', False)

            if self._has_signing_keys:
                priv_pem = self._signing_keys.get("privkey")
                priv_pem=pem_fix(priv_pem)
                self._signing_key_obj = RSA.import_key(priv_pem.encode() if isinstance(priv_pem, str) else priv_pem)

            self._serial_num= self.tree_node.get('serial')

            # delegate Matrix her Tree
            self.delegate_tree_to_agent(
                self.get_matrix_universal_id(), self.tree_path_dict
            )

            self._emit_beacon = self.check_for_thread_poke("worker", timeout=60, emit_to_file_interval=10)

        except Exception as e:
            self.log(error=e, level="ERROR")

    def worker(self, config=None, identity=None):
        """
        Keep Matrix responsive and allow graceful shutdown.
        """
        if self.running:
            # Emit a beacon so Phoenix marks Matrix as alive
            self._emit_beacon()
            interruptible_sleep(self, 5)  # short, interruptible sleep
            return

        # Shutdown path
        self.log("[MATRIX] Shutdown requested, stopping worker.")
        interruptible_sleep(self, 5)

    def pre_boot(self):
        message = "Knock... Knock... Knock... The Matrix has you..."
        print(message)
        self.canonize_gospel()

    def post_boot(self):
        self._log_runtime_privileges()
        self.log(f"{self.NAME} v{self.AGENT_VERSION} – panopticon live and lethal...")
        message = "I'm watching..."
        # Manually check if our own comm directory exists (it does), and deliver the tree slice directly
        self.command_line_args.get("universal_id", "matrix")
        print(message)

    def _log_runtime_privileges(self):
        """Announce the bounded, non-secret grants attested by Railgun."""
        encoded = os.getenv("MATRIX_RUNTIME_CAPABILITIES_B64", "").strip()
        try:
            uid = os.geteuid() if hasattr(os, "geteuid") else "unknown"
            account = "unknown"
            if uid != "unknown" and os.name == "posix":
                import pwd
                account = pwd.getpwuid(uid).pw_name
            self.log(f"[PRIVILEGES] Runtime account={account} uid={uid}")
            self.log(
                "[PRIVILEGES] Universe-wide boundary: Matrix and all native "
                "child agents inherit this account policy."
            )
            if os.name == "posix":
                import grp
                groups = sorted({
                    grp.getgrgid(group_id).gr_name for group_id in os.getgroups()
                })
                self.log(
                    "[PRIVILEGES] OS groups="
                    + (",".join(groups) if groups else "none")
                )
                status = {}
                try:
                    with open("/proc/self/status", "r", encoding="utf-8") as stream:
                        for line in stream:
                            key, separator, value = line.partition(":")
                            if separator and key in {"CapEff", "NoNewPrivs"}:
                                status[key] = value.strip()
                except OSError:
                    pass
                if status:
                    self.log(
                        "[PRIVILEGES] Linux "
                        f"CapEff={status.get('CapEff', 'unknown')} "
                        f"NoNewPrivs={status.get('NoNewPrivs', 'unknown')}"
                    )

            if not encoded:
                self.log(
                    "[PRIVILEGES] No Railgun capability attestation received; "
                    "managed grants are unknown.",
                    level="WARNING",
                )
                return
            if len(encoded) > 65536:
                raise ValueError("capability attestation exceeds 64 KiB")
            payload = json.loads(
                base64.b64decode(encoded, validate=True).decode("utf-8")
            )
            if not isinstance(payload, dict) or set(payload) != {"version", "grants"}:
                raise ValueError("unexpected capability attestation fields")
            if payload.get("version") != 1:
                raise ValueError("unsupported capability attestation version")
            grants = payload.get("grants")
            if not isinstance(grants, list) or len(grants) > 128 or any(
                not isinstance(grant, str)
                or not grant
                or len(grant) > 512
                for grant in grants
            ):
                raise ValueError("invalid capability grant list")

            self.log(
                f"[PRIVILEGES] Grants and access requirements: {len(grants)}"
            )
            if not grants:
                self.log("[PRIVILEGES]   none — unprivileged universe account")
            for grant in grants:
                self.log(f"[PRIVILEGES]   {grant}")
        except Exception as error:
            self.log(
                "[PRIVILEGES] Invalid Railgun capability attestation",
                error=error,
                level="CRITICAL",
            )

    def worker_pre(self):
        self.log("Pre-boot checks complete. Swarm ready.")

    def worker_post(self):
        self.log("Matrix shutting down. Closing directives.")

    #called at the end of every packet_listener cycle
    def packet_listener_post(self):
        try:
            self._perform_agent_consciousness_scan()
        except Exception as e:
            self.log(error=e, level="ERROR")
        try:
            self.perform_tree_master_validation()
        except Exception as e:
            self.log(error=e, level="ERROR")
        try:
            # _reaper_transaction_watcher is implemented in the ReapStatusHandlerMixin
            # This call is rate-limited internally — safe to call every packet tick.
            self._reaper_transaction_watcher()
        except Exception as e:
            self.log(error=e, level="ERROR", block="reaper_watcher")
        try:
            self._assassin_manager()
        except Exception as e:
            self.log(error=e, level="ERROR")

    def canonize_gospel(self):
        gospel = {
            "type": "swarm_gospel",
            "title": "The Gospel of Matrix",
            "version": "v1.0",
            "written_by": "Matrix",
            "timestamp": int(time.time()),
            "doctrine": [
                "Matrix is the only agent who may write or delete identities from the Book of Life.",
                "Matrix generates and signs each agent’s keypair.",
                "Each agent receives a signed identity_token.json at birth.",
                "Each agent receives a signed_public_key.json so others may verify its voice.",
                "The full agent_tree_master.sig.json is signed by Matrix and lives in her codex.",
                "Agents receive only their slice, signed by Matrix, containing only what they need.",
                "No agent may speak unless its public key is signed by Matrix.",
                "Any agent without a valid signature is to be silenced by the swarm.",
                "Private keys are never regenerated. Resurrection requires memory.",
                "Every signature is a tongue. Every key is a soul. Every directive is a scroll.",
            ]
        }

        try:

            matrix_priv = RSA.import_key(self.matrix_priv)

            digest = SHA256.new(json.dumps(gospel, sort_keys=True).encode())
            sig = pkcs1_15.new(matrix_priv).sign(digest)
            gospel["sig"] = base64.b64encode(sig).decode()
            output_path=os.path.join(self.path_resolution['comm_path_resolved'], "codex" ,"gospel_of_matrix.sig.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(gospel, f, indent=2)
                f.close()
            print("[GOSPEL] 📜 Gospel of Matrix signed and written to codex.")

        except Exception as e:
            self.log(error=e, block="main_try")

    def cmd_the_source(self, content, packet, identity:IdentityObject=None):

        """
        Gate-kept entry-point for **every** command bound for the Matrix core, except for cmd_deliver_agent_tree_to_child used for agents to retrieve their agent_trees.

        Incoming packets arrive as an *outer* wrapper that contains an RSA-signed,
        AES-encrypted payload.
        `cmd_the_source` verifies the outer signature, decrypts the inner blob,
        and then dispatches the unwrapped command to the matching private
        `_cmd_*` handler.

        Args:
            content: The **outer** packet’s `"content"` field. Expected to look like::

                {
                    "timestamp" : <int>,            # epoch seconds (outer wrapper)
                    "nonce"     : "<hex-id>",       # swarm-wide tracking nonce
                    "handler"   : "cmd_the_source", # always this value
                    "sig"       : "<rsa-sig>",      # RSA signature of the *inner* blob
                    "content"   : { ... }           # encrypted + signed payload
                }

            packet: The full transport envelope delivered by the bus
                (includes routing metadata the GUI / transport layer may add).

            identity: The caller’s verified `IdentityObject` (if the caller
                authenticated at the transport layer). Currently unused but
                passed through for parity with other command handlers.

        Workflow:
            1. `unwrap_secure_packet()`
               • Verifies RSA signature using `self._signing_keys["remote_pubkey"]`.
               • Rejects timestamp replays / expired packets.
               • Decrypts the AES payload with `self._signing_keys["privkey"]`.

            2. Extracts `"handler"` from the unwrapped inner dict.
               Builds an internal method name `_cmd_<handler>` and looks it up
               via `getattr`.

            3. If the handler exists and is callable, delegates execution:

               ```python
               handler(unwrapped.get("content", {}), packet, identity)
               ```

            4. Any failure at any stage is logged and **silently blocks**
               the packet (no exception propagated beyond this method).

        Side Effects:
            • Emits log lines at the INFO/ERROR level for audit-tracing.
            • May spawn further packets or mutate swarm state indirectly
              through the delegated handler.

        Returns:
            None. All meaningful work happens via side effects.

        Security:
            • Refuses packets that fail signature, decryption, or replay checks.
            • Only internal `_cmd_*` handlers are ever called; external names are never executed.

        Raises:
            Does **not** raise; all exceptions are caught, logged, and swallowed
            to avoid breaking the packet-listener loop.
        """
        try:

            uid = None
            if not self.encryption_enabled:
                uid = content.get("universal_id", False)  # swarm running in plaintext mode

            else:
                # reject invalid or missing identity
                if isinstance(identity, IdentityObject) and identity.has_verified_identity():
                     uid = identity.get_sender_uid()

            if not uid:
                self.log("[THE_SOURCE][ERROR] Missing universal_id.")
                return

            unwrapped = unwrap_secure_packet(content, self._signing_keys["remote_pubkey"], self._signing_keys.get("privkey"), logger=self.log)
            if not unwrapped:
                self.log(f"[GATE] ❌ Secure unwrap failed or invalid structure. Sender: {uid}")
                return

            self.log(f"[GATE] Signature accepted from {uid}.")

            # Gatekeeper: only allow commands from inside
            inner_handler = unwrapped.get("handler")
            if not inner_handler:
                self.log("[GATE] ❌ No handler in unwrapped packet.")
                return

            # Look for _cmd_* version and call it
            method_name = f"_cmd_{inner_handler.replace('cmd_', '')}"
            handler = getattr(self, method_name, None)

            if not callable(handler):
                self.log(f"[GATE] ❌ No internal handler found for: {method_name}")
                return

            try:
                handler(unwrapped.get("content", {}), packet, identity)
            except Exception as e:
                self.log(f"[GATE] ❌ Exception calling handler {method_name}", error=e)

        except Exception as e:
            self.log(error=e, block="main_try", level="ERROR")

    @reap_mutation
    def _cmd_delete_agent(self, content, packet, identity: IdentityObject = None):
        """Initiates deletion of a target agent and its subtree.
        Marks all nodes for deletion and sets up lifecycle callback metadata.
        The Reaper agent will perform physical cleanup asynchronously.
        """
        try:
            target_id = content.get("target_universal_id")
            if not target_id:
                self.log("[DELETE][ERROR] Missing target_universal_id.")
                return

            if target_id == self.command_line_args.get('universal_id'):
                self.log("[DELETE][ERROR] Can't delete Matrix.")
                return

            reaper_id = self.meta.get("swarm_state", {}).get("reserved_agent_ids", {}).get("reaper",False)
            if reaper_id and target_id == reaper_id:
                self.log("[DELETE][ERROR] Don't fear The Reaper.")
                return

            confirm_response = bool(content.get("confirm_response", 0))
            response_handler = content.get("return_handler")
            token = content.get("token", 0)
            session_id = content.get("session_id")

            tp = self.get_agent_tree_master()
            if not tp:
                self.log("[DELETE][ERROR] Failed to load agent tree master.")
                return

            if not tp.has_node(target_id):
                self.log(f"[DELETE][WARN] Target agent '{target_id}' not found.")
                return

            for cid in tp.get_subtree_nodes(target_id):  # skip the target itself
                child = tp.get_node(cid)
                if child and child.get("lifecycle_status", {}).get("locked"):
                    self.log(f"[DELETE][ABORT] {target_id} has locked descendant '{cid}'. Aborting delete.")
                    return

            trans_id = secrets.token_hex(8)

            mark = {
                "lifecycle_status": {
                    "locked": {
                        "by": self.get_matrix_universal_id(),
                        "reason": "shutdown_delete",
                        "timestamp": time.time(),
                    },
                    "op": "shutdown_delete",
                    "op_stage": "shutdown_probe",
                    "transaction_id": trans_id,
                    "last_checked": time.time(),
                    "agent_status_callback": {
                        "operation": "delete_agent",
                        "confirm_response": confirm_response,
                        "response_handler": response_handler,
                        "token": token,
                        "session_id": session_id,
                        "on_complete": "_delete_complete_callback"
                    },
                }
            }

            # mark entire subtree
            kill_list = tp.mark_target_list(target_id, mark, recurse_children=True)
            if not kill_list:
                self.log(f"[DELETE] No valid subtree found for {target_id}.")
                return

            if not self.save_agent_tree_master():
                raise RuntimeError("Delete state could not be saved")
            self.commit_reap_mutation()

            parent_node = tp.find_parent_of(target_id)
            parent_id = parent_node.get("universal_id") if parent_node else None
            if parent_id:
                self.defer_reap_side_effect(lambda: self.delegate_tree_to_agent(parent_id, self.tree_path_dict))
                return

            self.log(f"[DELETE] 🧨 Marked {len(kill_list)} agents for deletion: {kill_list}")

        except Exception as e:
            self.log("[DELETE][ERROR] Failed to mark agents for deletion.", error=e)

    @reap_mutation
    def _delete_complete_callback(self, tx_nodes, trans_id=None):
        """Publish completion only after the tree and authorization map commit."""
        tp = self.get_agent_tree_master()
        notices = []
        for uid, _ in tx_nodes:
            node = tp.get_node(uid)
            if not node:
                continue
            life = node.get("lifecycle_status", {})
            cb_info = copy.deepcopy(life.get("agent_status_callback", {}) or {})
            parent = tp.find_parent_of(uid)
            parent_id = parent.get("universal_id") if parent else None
            tp._remove_node_and_children(uid)
            notices.append((uid, parent_id, cb_info))
        if not self.save_agent_tree_master():
            raise RuntimeError("Could not durably save delete completion")
        tp.reparse()
        self.commit_reap_mutation()
        for uid, parent_id, cb_info in notices:
            if parent_id:
                self.defer_reap_side_effect(lambda parent_id=parent_id: self.delegate_tree_to_agent(parent_id, self.tree_path_dict))
            if cb_info:
                payload = {"universal_id": uid, "stage": "delete_complete",
                           "result": {"success": True, "error": None}, "callback_data": cb_info,
                           "token": cb_info.get("token"), "session_id": cb_info.get("session_id")}
                self.defer_reap_side_effect(lambda cb_info=cb_info, payload=payload: self.crypto_reply(
                    response_handler=cb_info.get("response_handler", "delete_agent.result"), payload=payload,
                    session_id=cb_info.get("session_id"), token=cb_info.get("token"),
                    rpc_role=self.tree_node.get("rpc_router_role", "hive.rpc")))
        if trans_id:
            self.defer_reap_side_effect(lambda: self._delegate_transaction_parent(tx_nodes, trans_id))

    @reap_mutation
    def _restart_complete_callback(self, tx_nodes, trans_id=None):
        """Unlock and acknowledge only after durable lifecycle commit."""
        tp = self.get_agent_tree_master()
        notices = []
        for uid, _ in tx_nodes:
            node = tp.get_node(uid)
            if not node:
                continue
            life = node.get("lifecycle_status", {})
            cb_info = copy.deepcopy(life.get("agent_status_callback", {}) or {})
            life.pop("locked", None)
            life["op_stage"] = "_complete_callback"
            life["last_checked"] = time.time()
            parent = tp.find_parent_of(uid)
            notices.append((uid, parent.get("universal_id") if parent else None, cb_info))
        if not self.save_agent_tree_master():
            raise RuntimeError("Could not durably save restart completion")
        self.commit_reap_mutation()
        for uid, parent_id, cb_info in notices:
            if parent_id:
                self.defer_reap_side_effect(lambda parent_id=parent_id: self.delegate_tree_to_agent(parent_id, self.tree_path_dict))
            if cb_info:
                payload = {"universal_id": uid, "stage": "restart_complete",
                           "result": {"success": True, "error": None}, "callback_data": cb_info,
                           "token": cb_info.get("token"), "session_id": cb_info.get("session_id")}
                self.defer_reap_side_effect(lambda cb_info=cb_info, payload=payload: self.crypto_reply(
                    response_handler=cb_info.get("response_handler", "restart_dialog.result"), payload=payload,
                    session_id=cb_info.get("session_id"), token=cb_info.get("token"),
                    rpc_role=self.tree_node.get("rpc_router_role", "hive.rpc")))
        if trans_id:
            self.defer_reap_side_effect(lambda: self._delegate_transaction_parent(tx_nodes, trans_id))

    @staticmethod
    def _hotswap_metadata(content):
        if not isinstance(content, dict):
            raise ValueError("Invalid hotswap request.")
        session, token, uid = content.get("session_id"), content.get("token"), content.get("target_universal_id")
        size, count, sha = content.get("size"), content.get("count"), content.get("sha256")
        if (not isinstance(session, str) or not session or len(session) > 128
                or not isinstance(token, str) or len(token) != 32
                or any(c not in "0123456789abcdef" for c in token)
                or not isinstance(uid, str) or not uid or len(uid) > 128
                or type(size) is not int or not 0 < size <= 524288 or type(count) is not int
                or count != (size + 8191) // 8192 or not isinstance(sha, str) or len(sha) != 64
                or any(c not in "0123456789abcdef" for c in sha)):
            raise ValueError("Invalid hotswap transfer identity or metadata.")
        return session, token, uid, size, count, sha

    def _cmd_hotswap_challenge(self, content, packet, identity:IdentityObject=None):
        """Issue a process-local challenge bound to one authenticated request."""
        try:
            session, token, uid, size, count, sha = self._hotswap_metadata(content)
            key = (session, token)
            metadata = (uid, size, count, sha)
            with self._hotswap_lock:
                entry = self._hotswap_challenges.get(key)
                if entry is None:
                    if len(self._hotswap_challenges) >= 4096:
                        raise ValueError("Hotswap challenge capacity reached; restart Matrix before more hotswaps.")
                    entry = {"challenge": secrets.token_hex(32), "metadata": metadata, "closed": False}
                    self._hotswap_challenges[key] = entry
                elif entry["metadata"] != metadata:
                    raise ValueError("Conflicting hotswap challenge request.")
                if entry["closed"]:
                    return
                challenge = entry["challenge"]
            self.crypto_reply(response_handler="hotswap_agent.challenge", session_id=session, token=token,
                              rpc_role=self.tree_node.get("rpc_router_role", "hive.rpc"),
                              payload={"session_id": session, "token": token, "target_universal_id": uid,
                                       "size": size, "count": count, "sha256": sha, "challenge": challenge})
        except Exception as exc:
            self.log("[HOTSWAP] Challenge request rejected.", error=exc, level="ERROR")
            if isinstance(content, dict) and isinstance(content.get("session_id"), str) and isinstance(content.get("token"), str):
                message = str(exc) if isinstance(exc, ValueError) else "Hotswap challenge failed."
                self._send_hotswap_result(content.get("target_universal_id"), "error", message,
                                          content["session_id"], content["token"])

    def _check_hotswap_challenge_locked(self, content, *, allow_closed=False):
        session, token, uid, size, count, sha = self._hotswap_metadata(content)
        entry = self._hotswap_challenges.get((session, token))
        challenge = content.get("challenge")
        if (entry is None or entry["metadata"] != (uid, size, count, sha)
                or not isinstance(challenge, str) or not secrets.compare_digest(entry["challenge"], challenge)
                or (entry["closed"] and not allow_closed)):
            raise HotswapChallengeError("Hotswap challenge is missing, stale, or already used.")
        return entry

    def _cmd_hotswap_transfer(self, content, packet, identity:IdentityObject=None):
        """Assemble independently authenticated chunks without relaxing packet limits."""
        session = content.get("session_id") if isinstance(content, dict) else None
        token = content.get("token") if isinstance(content, dict) else None
        uid = content.get("target_universal_id") if isinstance(content, dict) else None
        key = (session, token)
        complete = None
        error = None
        valid_key = False
        challenge_valid = False
        acknowledge = False
        try:
            if (not isinstance(session, str) or not session or len(session) > 128
                    or not isinstance(token, str) or len(token) != 32
                    or any(c not in "0123456789abcdef" for c in token)
                    or not isinstance(uid, str) or not uid or len(uid) > 128):
                raise ValueError("Invalid hotswap transfer identity.")
            valid_key = True
            size, count, sha, kind = content.get("size"), content.get("count"), content.get("sha256"), content.get("kind")
            if (type(size) is not int or not 0 < size <= 524288 or type(count) is not int
                    or count != (size + 8191) // 8192 or not isinstance(sha, str) or len(sha) != 64
                    or any(c not in "0123456789abcdef" for c in sha) or kind not in ("chunk", "commit")):
                raise ValueError("Invalid hotswap transfer metadata.")
            with self._hotswap_lock:
                self._check_hotswap_challenge_locked(content, allow_closed=True)
                challenge_valid = True
            data = None
            if kind == "chunk":
                index, encoded = content.get("index"), content.get("data")
                if type(index) is not int or not 0 <= index < count or not isinstance(encoded, str) or len(encoded) > 10924:
                    raise ValueError("Invalid hotswap source chunk.")
                data = base64.b64decode(encoded, validate=True)
                expected = min(8192, size - index * 8192)
                if len(data) != expected:
                    raise ValueError("Invalid hotswap source chunk length.")
            with self._hotswap_lock:
                now = time.monotonic()
                challenge_entry = self._check_hotswap_challenge_locked(content, allow_closed=True)
                challenge_valid = True
                if challenge_entry["closed"] and key not in self._hotswap_closed:
                    return
                if key in self._hotswap_closed:
                    closed = self._hotswap_closed[key]
                    if (kind == "commit" and closed.get("metadata") == (uid, size, count, sha)):
                        acknowledge = True
                    else:
                        return
                if acknowledge:
                    transfer = None
                else:
                    transfer = self._hotswap_transfers.get(key)
                if not acknowledge and transfer is None:
                    if len(self._hotswap_transfers) >= 8:
                        raise ValueError("Too many hotswap transfers are already in progress.")
                    transfer = {"uid": uid, "size": size, "count": count, "sha": sha,
                                "parts": {}, "committed": False, "created": now}
                    # Email ingress/egress may each poll on multi-second
                    # intervals; keep the bounded transfer alive long enough
                    # for sequential acknowledged chunks on slower links.
                    timer = threading.Timer(3600, self._expire_hotswap_transfer, args=(key, now))
                    timer.daemon = True
                    transfer["timer"] = timer
                    self._hotswap_transfers[key] = transfer
                    timer.start()
                elif not acknowledge and (transfer["uid"], transfer["size"], transfer["count"], transfer["sha"]) != (uid, size, count, sha):
                    raise ValueError("Conflicting hotswap transfer metadata.")
                if not acknowledge and kind == "commit":
                    transfer["committed"] = True
                elif not acknowledge:
                    old = transfer["parts"].get(index)
                    if old is not None and old != data:
                        raise ValueError("Conflicting hotswap source chunk.")
                    transfer["parts"][index] = data
                if not acknowledge and transfer["committed"] and len(transfer["parts"]) == count:
                    assembled = b"".join(transfer["parts"][i] for i in range(count))
                    if len(assembled) != size or not secrets.compare_digest(hashlib.sha256(assembled).hexdigest(), sha):
                        raise ValueError("Assembled hotswap source hash did not match.")
                    transfer["timer"].cancel()
                    del self._hotswap_transfers[key]
                    challenge_entry["closed"] = True
                    self._remember_hotswap_transfer_closed(key, metadata=(uid, size, count, sha))
                    complete = {"target_universal_id": uid, "session_id": session, "token": token,
                                "challenge": content.get("challenge"),
                                "source_payload": {"payload": base64.b64encode(assembled).decode("ascii"), "sha256": sha}}
                acknowledge = True
        except Exception as exc:
            error = str(exc) if isinstance(exc, ValueError) else "Hotswap transfer failed."
            with self._hotswap_lock:
                if valid_key and challenge_valid:
                    old = self._hotswap_transfers.pop(key, None)
                    if old:
                        old["timer"].cancel()
                    if challenge_valid:
                        self._hotswap_challenges[key]["closed"] = True
                        self._remember_hotswap_transfer_closed(key)
        if error and valid_key and challenge_valid:
            self._send_hotswap_result(uid, "error", error, session, token, challenge=content.get("challenge"))
        elif acknowledge:
            self._send_hotswap_ack(session, token, uid, sha, count, kind, content.get("index"), content.get("challenge"))
            if complete is not None:
                self._cmd_hotswap_agent(complete, packet, identity, _assembled=True)

    def _expire_hotswap_transfer(self, key, created):
        with self._hotswap_lock:
            transfer = self._hotswap_transfers.get(key)
            if transfer is None or transfer["created"] != created:
                return
            del self._hotswap_transfers[key]
            self._hotswap_challenges[key]["closed"] = True
            self._remember_hotswap_transfer_closed(key)
        self._send_hotswap_result(transfer["uid"], "error", "Hotswap transfer was incomplete or expired.", key[0], key[1],
                                  challenge=self._hotswap_challenges[key]["challenge"])

    def _remember_hotswap_transfer_closed(self, key, metadata=None):
        # The bounded process-lifetime challenge table caps this table too.
        self._hotswap_closed[key] = {"metadata": metadata}

    def _send_hotswap_ack(self, session, token, uid, sha, count, kind, index, challenge):
        self.crypto_reply(response_handler="hotswap_agent.ack", session_id=session, token=token,
                          rpc_role=self.tree_node.get("rpc_router_role", "hive.rpc"),
                          payload={"target_universal_id": uid, "sha256": sha, "count": count,
                                   "kind": kind, "index": index, "challenge": challenge,
                                   "session_id": session, "token": token})

    @reap_mutation
    def _cmd_hotswap_agent(self, content, packet, identity:IdentityObject=None, *, _assembled=False):
        """Stage a signed, boot-scoped source override and restart one agent."""
        target_universal_id = content.get("target_universal_id") if isinstance(content, dict) else None
        session_id = content.get("session_id") if isinstance(content, dict) else None
        token = content.get("token") if isinstance(content, dict) else None
        pending = False
        try:
            src = content.get("source_payload", {})
            if (not isinstance(target_universal_id, str) or not target_universal_id
                    or not isinstance(session_id, str) or not session_id or len(session_id) > 128
                    or not isinstance(token, str) or not token or len(token) > 128
                    or not isinstance(src, dict) or not isinstance(src.get("payload"), str)
                    or not isinstance(src.get("sha256"), str)):
                raise ValueError("Missing hotswap target, source, or reply identity.")
            if len(src["payload"]) > (699052 if _assembled else 90000):
                raise ValueError("Source exceeds the hotswap packet limit.")
            try:
                code = base64.b64decode(src["payload"], validate=True)
                if not code or len(code) > (524288 if _assembled else 65536):
                    raise ValueError("Source exceeds the hotswap packet limit.")
                compile(code.decode("utf-8"), "<hotswap>", "exec")
            except (ValueError, UnicodeError, SyntaxError) as exc:
                raise ValueError("Source is not valid UTF-8 Python.") from exc
            sha = hashlib.sha256(code).hexdigest()
            if not secrets.compare_digest(sha, src["sha256"].lower()):
                raise ValueError("Source hash did not match.")
            if not _assembled:
                _, _, _, claimed_size, _, claimed_sha = self._hotswap_metadata(content)
                if len(code) != claimed_size or sha != claimed_sha:
                    raise ValueError("Source does not match the challenged request.")
                with self._hotswap_lock:
                    challenge = self._check_hotswap_challenge_locked(content)
                    # Consume before any state mutation; retries cannot stage
                    # the same signed request twice in this process.
                    challenge["closed"] = True
            if target_universal_id == self.command_line_args.get('universal_id'):
                raise ValueError("Matrix cannot be hotswapped.")
            reaper_id = self.meta.get("swarm_state", {}).get("reserved_agent_ids", {}).get("reaper", False)
            if reaper_id and target_universal_id == reaper_id:
                raise ValueError("The Reaper cannot be hotswapped.")
            tp = self.get_agent_tree_master()
            node = tp.get_node(target_universal_id) if tp else None
            if not node:
                raise ValueError("The target agent no longer exists.")
            if node.get("lang", "python") != "python":
                raise ValueError("Hotswap currently supports Python agents only.")
            if node.get("lifecycle_status", {}).get("locked"):
                raise ValueError("The target is busy with another operation.")
            for uid in tp.get_subtree_nodes(target_universal_id):
                child = tp.get_node(uid)
                if child and child.get("lifecycle_status", {}).get("locked"):
                    raise ValueError("The target or its subtree is busy with another operation.")
            with self._hotswap_lock:
                if target_universal_id in self._hotswap_pending:
                    raise ValueError("A hotswap for this agent is already pending.")
                self._hotswap_pending.add(target_universal_id)
                pending = True
            started_at = time.time()
            previous = self._hotswap_processes(target_universal_id)
            old_values = {key: (key in node, copy.deepcopy(node.get(key))) for key in ("src_embed", "hash_bang")}
            def restore_source():
                for key, (existed, value) in old_values.items():
                    if existed:
                        node[key] = value
                    else:
                        node.pop(key, None)
                try:
                    return bool(self.save_agent_tree_master())
                except Exception:
                    return False
            node["src_embed"] = src["payload"]
            node["hash_bang"] = sha
            try:
                saved = bool(self.save_agent_tree_master())
            except Exception:
                saved = False
            if not saved:
                restored = restore_source()
                detail = "The previous source was restored." if restored else "The saved state may have changed; inspect it before restarting."
                raise ValueError(f"The source save could not be confirmed. {detail} No restart was requested.")
            if not self._cmd_restart_subtree({"target_universal_id": target_universal_id}, packet, identity):
                restored = restore_source()
                detail = "The previous source was restored." if restored else "The saved state may have changed; inspect it before retrying."
                raise ValueError(f"The restart could not be queued. {detail}")
            worker = threading.Thread(target=self._wait_hotswap_start,
                                      args=(target_universal_id, sha, session_id, token, started_at, previous),
                                      kwargs={"challenge": content.get("challenge")},
                                      daemon=True)
            self.commit_reap_mutation()
            def abort_hotswap():
                with self._hotswap_lock:
                    self._hotswap_pending.discard(target_universal_id)
                self._send_hotswap_result(target_universal_id, "error",
                                          "Hotswap authorization could not be committed; inspect the saved state before retrying.",
                                          session_id, token, challenge=content.get("challenge"))
            self.defer_reap_abort(abort_hotswap)
            def start_hotswap_waiter():
                try:
                    worker.start()
                except Exception as exc:
                    with self._hotswap_lock:
                        self._hotswap_pending.discard(target_universal_id)
                    self.log("[HOTSWAP] Could not start readiness monitor.", error=exc, level="ERROR")
                    self._send_hotswap_result(
                        target_universal_id, "error",
                        "The hotswap was committed, but its new agent could not be verified. Check the agent logs.",
                        session_id, token, challenge=content.get("challenge"))
            self.defer_reap_side_effect(start_hotswap_waiter)
            pending = False  # worker owns the pending marker
        except Exception as e:
            self.log("[HOTSWAP] Request failed.", error=e, level="ERROR")
            if pending:
                with self._hotswap_lock:
                    self._hotswap_pending.discard(target_universal_id)
            if not isinstance(e, HotswapChallengeError) and isinstance(session_id, str) and isinstance(token, str):
                message = str(e) if isinstance(e, ValueError) else "Hotswap failed; see Matrix logs."
                self._send_hotswap_result(target_universal_id, "error", message, session_id, token,
                                          challenge=content.get("challenge") if isinstance(content, dict) else None)

    def _send_hotswap_result(self, uid, status, message, session_id, token, sha=None, challenge=None):
        # Legacy Phoenix treats all `.confirm` messages as success.
        handler = "hotswap_agent.confirm" if status == "success" else "hotswap_agent.error"
        self.crypto_reply(response_handler=handler, session_id=session_id, token=token,
                          rpc_role=self.tree_node.get("rpc_router_role", "hive.rpc"),
                          payload={"target_universal_id": uid, "status": status, "message": message,
                                   "sha256": sha, "session_id": session_id, "token": token,
                                   "challenge": challenge})

    def _hotswap_processes(self, uid):
        return {(entry["pid"], entry["process_started_at"]) for entry in
                get_all_swarm_agent_info(self.command_line_args["universe"], base=self.path_resolution["install_path"])
                if entry.get("universal_id") == uid and entry.get("pid") and entry.get("process_started_at")}

    def _hotswap_running(self, uid, sha, requested_at, previous):
        """Verify a new process and its own source-bound readiness marker."""
        processes = self._hotswap_processes(uid)
        if previous & processes:
            return False
        # psutil reports Linux process start times at kernel clock-tick
        # granularity; a newly launched process can round slightly earlier
        # than the request even though its heartbeat must still be newer.
        candidates = {(pid, started) for pid, started in processes - previous if started >= requested_at - 1}
        if not candidates:
            return False
        base = self.path_resolution["install_path"]
        universe = self.command_line_args["universe"]
        boot = self.path_resolution["reboot_uuid"]
        with runtime_directory(base, universe, boot, "pod") as pod_root:
            for name in os.listdir(pod_root):
                try:
                    with child_directory(pod_root, name) as pod:
                        fd = open_beneath(pod, "boot.json", os.O_RDONLY | os.O_NONBLOCK)
                        try:
                            info = os.fstat(fd)
                            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                                continue
                            with os.fdopen(fd, "rb") as stream:
                                fd = -1
                                raw = stream.read(1024 * 1024 + 1)
                            if len(raw) > 1024 * 1024:
                                continue
                            record = json.loads(raw)
                            if not isinstance(record, dict):
                                continue
                        finally:
                            if fd >= 0:
                                os.close(fd)
                        process = (record.get("pid"), record.get("process_started_at"))
                        if record.get("universal_id") != uid or record.get("source_sha256") != sha or process not in candidates:
                            continue
                        ready_fd = open_beneath(pod, "ready.json", os.O_RDONLY | os.O_NONBLOCK)
                        try:
                            info = os.fstat(ready_fd)
                            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                                    or info.st_mtime < requested_at or info.st_mtime > time.time()):
                                continue
                            with os.fdopen(ready_fd, "rb") as stream:
                                ready_fd = -1
                                raw = stream.read(4097)
                            if len(raw) > 4096:
                                continue
                            ready = json.loads(raw)
                        finally:
                            if ready_fd >= 0:
                                os.close(ready_fd)
                        if ready == {"universal_id": uid, "pid": process[0],
                                     "process_started_at": process[1], "source_sha256": sha}:
                            # Recheck liveness after reading the marker.
                            return process in self._hotswap_processes(uid)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue
        return False

    def _wait_hotswap_start(self, uid, sha, session_id, token, requested_at, previous, timeout=240, challenge=None):
        try:
            deadline = time.monotonic() + timeout
            while getattr(self, "running", False) and time.monotonic() < deadline:
                try:
                    if self._hotswap_running(uid, sha, requested_at, previous):
                        self._send_hotswap_result(uid, "success", "New source is running. This override lasts only for the current universe boot.", session_id, token, sha, challenge)
                        return
                except Exception as exc:
                    self.log("[HOTSWAP] Unable to verify restart yet.", error=exc)
                time.sleep(1)
            self._send_hotswap_result(uid, "error", "The source was saved for this boot, but the new agent did not report a verified start. Check the agent logs.", session_id, token, sha, challenge)
        finally:
            with self._hotswap_lock:
                self._hotswap_pending.discard(uid)

    @reap_mutation
    def _handle_replace_agent(self, content):
        old_id = content.get("target_universal_id")
        new_node = content.get("new_agent")

        if not old_id or not new_node:
            self.log("[REPLACE] Missing required fields.")
            return False

        tp = self.get_agent_tree_master()
        if not tp or not tp.has_node(old_id):
            self.log(f"[REPLACE] Agent '{old_id}' not found in tree.")
            return False

        parent = tp.find_parent_of(old_id)
        if not parent:
            self.log(f"[REPLACE] Could not find parent of '{old_id}'.")
            return False

        # Don't inject under parent, if marked for deletion or is deleted
        if parent.get("lifecycle_status", {}).get("locked"):
            self.log(f"Parent {parent} is deleted. Cannot inject new nodes.")
            return False

        # Validate universal_id override
        new_uid = new_node.get("universal_id")
        if new_uid and new_uid != old_id:
            self.log(f"[REPLACE] ❌ New node contains conflicting universal_id '{new_uid}'. Must match '{old_id}' or be omitted.")
            return False

        # Update existing node in-place instead of removing
        node = tp.get_node(old_id)
        if node.get("lifecycle_status", {}).get("locked"):
            self.log(f"[REPLACE] Agent '{old_id}' is locked by a lifecycle operation.")
            return False
        ALLOWED_FIELDS = {"name", "app", "config", "filesystem", "directives"}

        updated = False
        for key in ALLOWED_FIELDS:
            if key in new_node:
                node[key] = new_node[key]
                self.log(f"[REPLACE] ✅ Field '{key}' updated on '{old_id}'")
                updated = True

        if updated:
            # 💾 Only back up if something was actually changed
            #backup_path = self.tree_path.replace(".json", f"_backup_{int(time.time())}.json")
            #tp.save(backup_path)
            #self.log(f"[REPLACE] 💾 Tree backed up to: {backup_path}")

            # Save patched tree
            if not self.save_agent_tree_master():
                raise RuntimeError("Replacement state could not be saved")
            self.commit_reap_mutation()

            self.log(f"[REPLACE] 💾 Tree saved with updated agent '{old_id}'")

            # 🔁 Re-delegate the target agent
            self.defer_reap_side_effect(lambda: self.delegate_tree_to_agent(old_id, self.tree_path_dict))
            self.log(f"[REPLACE] 🔁 Delegated new agent_tree to {old_id}")

            # 🔁 Re-delegate the parent who spawns this agent
            parent_id = tp.find_parent_of(old_id)
            if parent_id["universal_id"]:
                self.defer_reap_side_effect(lambda: self.delegate_tree_to_agent(parent_id["universal_id"], self.tree_path_dict))
                self.log(f"[REPLACE] 🔁 Updated parent {parent_id['universal_id']} with patched child '{old_id}'")
            else:
                self.log(f"[REPLACE] ⚠️ No parent found for '{old_id}', possible orphaned spawn chain.")
            return True
        else:
            self.log(f"[REPLACE] ⚠️ No valid fields were updated for agent '{old_id}'. Replace aborted.")

    def _validate_or_prepare_agent(self, new_agent):
        self.log(f"[DEBUG] _validate_or_prepare_agent() received: {json.dumps(new_agent, indent=2)}")

        agent_name = new_agent.get("name")
        if not agent_name:
            self.log("[REPLACE-VALIDATE] ❌ Missing agent 'name'.")
            return False

        agent_dir = os.path.join(self.path_resolution["agent_path"], agent_name)
        entry_file = os.path.join(agent_dir, f"{agent_name}.py")

        if os.path.exists(entry_file):
            self.log(f"[REPLACE-VALIDATE] ✅ Agent source verified: {entry_file}")
            return True

        self.log(f"[REPLACE-VALIDATE] ❌ No source found at {entry_file}. Replace aborted.")
        return False

    @reap_mutation
    def _cmd_update_agent(self, content, packet, identity:IdentityObject=None):
        """Handles the command to update a live agent's configuration.

        This command modifies the `config` block of a specified agent in the
        master agent tree. If the `push_live_config` flag is set, it will
        also drop the new configuration into the live agent's `/config`
        directory, triggering an immediate, real-time update of its behavior.

        Args:
            content (dict): The payload containing 'target_universal_id' and
                'config' (the dictionary of new config values).
            packet (dict): The raw packet data.
            identity (IdentityObject): The verified identity of the command sender.
        """

        try:
            updates = content.get("config", {})
            uid = content.get("target_universal_id")
            push_live_config = bool(updates.get("push_live_config", False))

            if not uid or not updates:
                self.log("[UPDATE_AGENT][ERROR] Missing target_universal_id or fields.")
                return

            tp = self.get_agent_tree_master()
            if not tp:
                self.log("[UPDATE_AGENT][ERROR] Failed to load tree.")
                return

            node = tp.get_node(uid)
            if not node:
                self.log(f"[UPDATE_AGENT][ERROR] Agent '{uid}' not found.")
                return

            if node.get("lifecycle_status", {}).get("locked"):
                self.log(f"[UPDATE_AGENT][ERROR] Agent '{uid}' is locked by a lifecycle operation.")
                return

            updated = False
            if not push_live_config:
                if "config" not in node or not isinstance(node["config"], dict):
                    node["config"] = {}
                for key, val in updates.items():
                    node["config"][key] = val
                    updated = True
                    self.log(f"[UPDATE_AGENT] ✅ Patched config['{key}'] for '{uid}'")

            #a transient config or self-managed config
            if push_live_config:
                try:
                    pk1 = self.get_delivery_packet("standard.general.json.packet")
                    pk1.set_data(updates)

                    if not self.save_agent_tree_master():
                        raise RuntimeError("Configuration state could not be saved")
                    self.commit_reap_mutation()
                    self.defer_reap_side_effect(lambda: self.pass_packet(pk1, uid, "config"))

                except Exception as e:
                    self.log(error=e, block="main_try")

            if updated:

                if not self.save_agent_tree_master():
                    raise RuntimeError("Updated configuration could not be saved")
                self.commit_reap_mutation()

                parent = tp.find_parent_of(uid)
                if parent and parent.get("universal_id"):
                    self.defer_reap_side_effect(lambda: self.delegate_tree_to_agent(parent["universal_id"], self.tree_path_dict))

                self.log(f"[UPDATE_AGENT] 🔁 Agent '{uid}' successfully updated and delegated.")
            elif not push_live_config:
                self.log(f"[UPDATE_AGENT] ⚠️ No valid fields updated for '{uid}'")

        except Exception as e:
            self.log(error=e, block="main_try")

    def _cmd_replace_source(self, content, packet, identity=None):
        """Shared source updates must use Phoenix's administrative SSH path."""
        payload = content.get("payload", {}) if isinstance(content, dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        message = "Server-wide source replacement requires the recorded administrative SSH profile in Phoenix."
        self.log(f"[REPLACE] {message}")
        session_id, token = payload.get("session_id"), payload.get("token")
        if session_id and token:
            # Older Phoenix versions treat every `.confirm` as success,
            # regardless of status. Never send a failure on that channel.
            self.crypto_reply(response_handler="replace_agent_source.error", session_id=session_id, token=token,
                              rpc_role=self.tree_node.get("rpc_router_role", "hive.rpc"),
                              payload={"target_agent_name": content.get("target_agent_name"), "status": "error",
                                       "message": message, "session_id": session_id, "token": token})

    def _cmd_inject_agents(self, content, packet, identity:IdentityObject = None):
        """Handler for dynamically injecting a new agent or subtree into the swarm.

        This command receives a request to add a new agent under a specified
        parent. It validates the request, updates the master agent tree in
        memory, saves the new tree to disk, and then delegates the updated
        tree slice to the parent agent. The parent's `spawn_manager` thread
        then automatically launches the new child agent.

        Args:
            content (dict): The command payload containing 'target_universal_id'
                (the parent) and 'subtree' (the new agent node to inject).
            packet (dict): The raw packet data.
            identity (IdentityObject): The verified identity of the command sender.
        """
        try:
            confirm_response = bool(content.get("confirm_response", 0))
            handler_role = content.get("handler_role",None) #handler role
            handler = content.get("handler",None) #local command to execute
            response_handler = content.get("response_handler", None)  #sent back to gui, so it knows what handler to call
            response_id = content.get("response_id", 0)

            ret = self._handle_inject_agents(content, packet)

            if confirm_response and handler_role and handler and response_handler:

                alert_nodes = self.get_nodes_by_role(handler_role)
                if not alert_nodes:
                    self.log(f"[RPC][RESULT] No agent found with role: {handler_role}")
                    return

                pk1 = self.get_delivery_packet("standard.command.packet")
                pk1.set_data({"handler": handler})

                payload_summary = []

                #PAYLOAD SUMMARY
                try:

                    tp = self.get_agent_tree_master()
                    if isinstance(tp, TreeParser):
                        for uid in ret.get("injected", []):
                            node = tp.get_node(uid)
                            if not node:
                                continue
                            payload_summary.append({
                                "universal_id": uid,
                                "parent": content.get("target_universal_id"),
                                "roles": node.get("config", {}).get("role", []),
                                "delegated": node.get("delegated", [])
                            })

                except Exception as e:
                    self.log(error=e)

                pk2 = self.get_delivery_packet("standard.rpc.handler.general.packet")
                pk2.set_data({
                    "handler": response_handler,
                    "origin": self.command_line_args.get("universal_id", "matrix"),
                    "content": {
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "response_id": response_id,
                        "status": ret.get("status", "error"),
                        "error_code": ret.get("error_code", 99),
                        "message": ret.get("message", "Injection result."),
                        "details": {
                            "injected": ret.get("injected", []),
                            "rejected": ret.get("rejected", []),
                            "duplicates": ret.get("duplicates", []),
                            "errors": ret.get("errors", [])
                        },
                        "payload": payload_summary
                    }
                })

                pk1.set_packet(pk2, "content")

                for ep in alert_nodes:
                    self.pass_packet(pk1, ep.get_universal_id())

        except Exception as e:
            self.log(error=e, block="main_try")

    @reap_mutation
    def _handle_inject_agents(self, content, packet):

        parent = content.get("target_universal_id")
        subtree = content.get("subtree")
        # error_codes
        # 0 success agent spawned
        # 1 TreeParse not returned from load_directive
        # 2 agent already exists
        # 3 couldn't load agent_tree_master
        # 4 parent doesn't exist
        # 5 tried to inject a matrix
        # 6 crashed while saving node into tree
        # 7 rejected malformed node
        ret = {
            "error_code": 0,
            "status": "pending",
            "message": "",
            "injected": [],
            "rejected": [],
            "errors": []
        }

        # Parse base agent identity
        if "subtree" in content:
            universal_id = content["subtree"].get("universal_id")
            agent_name = content["subtree"].get("name", "").lower()
        else:
            universal_id = content.get("universal_id")
            agent_name = content.get("name", "").lower()

        # Load tree directive
        tp = self.get_agent_tree_master()
        if not tp:
            ret["error_code"] = 1
            ret["status"] = "error"
            ret["message"] = "[INJECT][ERROR] Failed to load tree directive."
            self.log(ret["message"])
            return ret

        # Check for parent node existence
        if not tp.has_node(parent):
            ret["error_code"] = 2
            ret["status"] = "error"
            ret["message"] = f"[INJECT][ERROR] Parent '{parent}' not found in parsed tree."
            self.log(ret["message"])
            return ret

        # Don't inject under parent, if marked for deletion or is deleted
        parent_node = tp.get_node(parent)
        if parent_node and parent_node.get("lifecycle_status", {}).get("locked"):
            self.log(f"[INJECT][BLOCKED] Parent {parent} is deleted. Cannot inject new nodes.")
            ret["status"] = "error"
            ret["message"] = f"Parent {parent} is deleted. Injection blocked."
            ret["error_code"] = 8
            return ret

        # Lifecycle state belongs exclusively to Matrix, never to an injected payload.
        def contains_lifecycle_state(tree):
            if not isinstance(tree, dict):
                return False
            if "lifecycle_status" in tree:
                return True
            return any(contains_lifecycle_state(child) for child in tree.get("children", []))

        if subtree and contains_lifecycle_state(subtree):
            ret.update(status="error", error_code=7,
                       message="Injected agents cannot specify lifecycle status.")
            return ret

        # Scan subtree for any node with matrix identity
        def contains_matrix_node(tree):
            if not isinstance(tree, dict):
                return False
            name = tree.get("name", "").lower()
            uid = tree.get("universal_id", "").lower()
            if name == "matrix" or uid == self.get_matrix_universal_id().lower():
                return True
            for child in tree.get("children", []):
                if contains_matrix_node(child):
                    return True
            return False

        if subtree:
            if contains_matrix_node(subtree):
                self.log("[INJECT][BLOCKED] Subtree injection attempt includes forbidden Matrix agent.")
                ret['error_code'] = 4
                return ret
        else:
            if (
                agent_name == "matrix"
                or universal_id == self.get_matrix_universal_id()
            ):
                self.log("[INJECT][BLOCKED] Direct Matrix injection attempt denied.")
                ret['error_code'] = 4
                return ret

        try:
            success = False

            #SUBTREE_INJECTION
            if subtree:

                try:

                    injected_ids=[]
                    if tp.has_node(universal_id):
                        ret["duplicates"] = [universal_id]
                        ret["status"] = "duplicate"
                        ret["message"] = f"Agent '{universal_id}' already exists."
                    else:

                        injected_ids = tp.insert_node(subtree, parent_universal_id=parent, matrix_priv_obj=self.matrix_priv_obj)

                        ret["injected"] = tp.get_added_nodes()
                        ret["rejected"] = tp.get_rejected_nodes()
                        ret["duplicates"] = tp.get_duplicates()
                        self.log(f"[DEBUG] Injected IDs: {ret['injected']}")
                        self.log(f"[DEBUG] rejected IDs: {ret['rejected']}")
                        self.log(f"[DEBUG] duplicates IDs: {ret['duplicates']}")

                    push_live_config_on_duplicate = content.get("push_live_config", False)
                    #this will deliver a partial_config update, if a duplicate is found it will be flagged partial_config
                    if (
                        push_live_config_on_duplicate and
                        bool(len(ret["duplicates"]))
                        ):

                        # Check if agent exists
                        self.log('Entering the Thunderdome.')
                        if push_live_config_on_duplicate and bool(len(ret["duplicates"])):
                            existing_node = tp.get_node(universal_id)
                            config = subtree.get("config", {})
                            if existing_node and bool(config):
                                # THIS is the important push
                                self._cmd_update_agent({
                                    "target_universal_id": universal_id,
                                    "config": config,
                                    "push_live_config": True
                                }, packet)
                                self.commit_reap_mutation()
                            ret["status"] = "success"
                            ret["message"] = f"Agent already existed — config partially updated for {universal_id}"
                            return ret

                    success = bool(len(injected_ids))
                    if not success:
                        self.log(f"[INJECT][ERROR] Insert failed. Rejected nodes: {tp.get_rejected_nodes()}")
                        msg = f"[INJECT][ERROR] Insert failed. Rejected nodes: {tp.get_rejected_nodes()}"
                        ret["message"] = msg
                        ret['error_code'] = 5
                        self.log(msg)

                except Exception as e:
                    self.log(error=e, block="subtree_injection")
                    ret['error_code'] = 6
                    msg = ret.get("message", "")
                    ret['message'] = f"{msg} | {type(e).__name__}: {str(e)}"

                if success:
                    # NEW: Save payloads for each node in the subtree
                    for node in TreeParser.flatten_tree(subtree):
                        src = node.get("source_payload")
                        name = node.get("name")


            else:

                delegated = content.get("delegated", [])
                filesystem = content.get("filesystem", {})
                config = content.get("config", {})
                src = content.get("source_payload")

                new_node = {
                    "name": agent_name,
                    "universal_id": universal_id,
                    "delegated": delegated,
                    "filesystem": filesystem,
                    "config": config,
                    "children": [],
                    "confirmed": time.time()
                }

                injected_ids = tp.insert_node(new_node, parent_universal_id=parent, matrix_priv_obj=self.matrix_priv_obj)
                success = bool(len(injected_ids))
                if not success:
                    self.log(f"[INJECT][ERROR] Insert failed. Rejected node {universal_id}")
                    ret['error_code'] = 5
                    ret["message"] = f"[INJECT][ERROR] Insert failed. Rejected node: {universal_id}"
                else:
                    self.log(f"[INJECT] ✅ Injected agent '{universal_id}' under '{parent}'.")
                    success=True

            if success:

                if not self.save_agent_tree_master():
                    raise RuntimeError("Injected agent state could not be saved")
                self.commit_reap_mutation()

                # --- REMEDY ---
                # After saving, the tree has new nodes with vaults.
                # We must force the tree parser to re-index its internal
                # dictionary so it can find the new agents.
                tp.reparse()
                # --- END REMEDY ---

                #delegate to parent agent
                self.defer_reap_side_effect(lambda: self.delegate_tree_to_agent(parent, self.tree_path_dict))

                for agent_id in tp.get_first_level_child_ids(parent):
                    self.defer_reap_side_effect(lambda agent_id=agent_id: self.delegate_tree_to_agent(agent_id, self.tree_path_dict))

                ret["status"] = "success"
                ret.setdefault("message", "Agent(s) injected successfully.")

            else:

                ret["status"] = "error"
                ret.setdefault("message", "Injection failed or partial success.")

        except Exception as e:
            self.log(error=e, block="main_try")

        return ret

    @reap_mutation
    def _cmd_restart_subtree(self, content, packet, identity: IdentityObject = None):
        """
        Gracefully restarts an agent or its entire subtree.

        By default, restarts only the target agent.
        If content["restart_full_subtree"] = True, restarts the entire subtree.
        """
        snapshots = {}
        tp = None
        marked = False
        try:
            target_universal_id = content.get("target_universal_id")
            confirm_response = bool(content.get("confirm_response", 0))
            response_handler = content.get("return_handler")
            token = content.get("token", 0)
            session_id = content.get("session_id")
            full_flag = bool(content.get("restart_full_subtree", False))

            if not target_universal_id:
                self.log("[RESTART][ERROR] Missing universal_id.")
                return False

            tp = self.get_agent_tree_master()
            if not tp:
                self.log("[RESTART][ERROR] Failed to load tree.")
                return False

            for cid in tp.get_subtree_nodes(target_universal_id):  # skip the target itself
                child = tp.get_node(cid)
                if child and child.get("lifecycle_status", {}).get("locked"):
                    self.log(f"[RESTART][ABORT] {target_universal_id} has locked descendant '{cid}'. Aborting restart.")
                    return False

            # Scope
            recurse_children = False
            if full_flag:
                ids = tp.get_subtree_nodes(target_universal_id)
                self.log(f"[RESTART] Restarting full subtree for {target_universal_id}: {ids}")
                recurse_children = True
            else:
                ids = [target_universal_id]
                self.log(f"[RESTART] Restarting single agent only: {target_universal_id}")

            trans_id = secrets.token_hex(8)

            # Prime common values (Matrix-side best-effort)
            comm_path = self.path_resolution["comm_path"]

            mark = {
                "lifecycle_status": {
                    "locked": {
                        "by": self.get_matrix_universal_id(),
                        "reason": "shutdown_restart",
                        "timestamp": time.time()
                    },
                    "transaction_id": trans_id,
                    "op": "shutdown_restart",
                    "op_stage": "shutdown_probe",  # Reaper will probe first
                    "last_checked": time.time(),
                    "comm_path": comm_path,
                    "agent_status_callback": {
                        "operation": "restart_subtree",
                        "restart_full_subtree": full_flag,
                        "confirm_response": confirm_response,
                        "response_handler": response_handler,
                        "token": token,
                        "session_id": session_id,
                        "on_complete": "_restart_complete_callback"
                    }
                }
            }

            for uid in ids:
                node = tp.get_node(uid)
                if node:
                    snapshots[uid] = ("lifecycle_status" in node, copy.deepcopy(node.get("lifecycle_status")))
            marked = True
            tp.mark_target_list(target_universal_id, mark, recurse_children=recurse_children)
            if not self.save_agent_tree_master():
                raise RuntimeError("Restart state could not be saved")

            self.commit_reap_mutation()

            self.log(f"[RESTART] ✅ Marked {len(ids)} agent(s) for restart (probe stage queued): {ids}")
            return True

        except Exception as e:
            self.log(error=e, block="main_try", level="ERROR")
            if marked and tp:
                for uid, (existed, value) in snapshots.items():
                    node = tp.get_node(uid)
                    if node is not None:
                        if existed:
                            node["lifecycle_status"] = value
                        else:
                            node.pop("lifecycle_status", None)
                try:
                    self.save_agent_tree_master()
                except Exception:
                    pass
            return False

    #checks everyone's tree against Matrix's agent_tree_master, using a hash of the agents tree
    #this also ensures services are updated for agents added and removed
    def perform_tree_master_validation(self):

        try:

            if time.time() - self._last_tree_verify > 300:  # 5-minute window
                self._last_tree_verify = time.time()

                tp = self.get_agent_tree_master()
                if not tp:
                    self.log("[VERIFY-TREE] Could not load master tree.")
                    return

                for universal_id in tp.all_universal_ids():
                    self.delegate_tree_to_agent(universal_id, self.tree_path_dict)

        except Exception as e:
            self.log(error=e, block="main_try")

    def _cmd_service_request(self, content, packet, identity: IdentityObject = None):
        """
        Dispatch a generic service request to one or more agents that advertise a role.

        Args:
            content (dict): {
                "service": "<role pattern>",     # e.g. "hive.log"
                "payload": { ... }               # inner content to send
            }
            packet (dict): The raw inbound packet.
            identity (IdentityObject): Verified identity of the sender.
        """
        try:

            service_role = content.get("service")
            payload = content.get("payload", {})
            diagnostic_request = (service_role == "hive.log_streamer"
                                  and isinstance(payload, dict) and "operation" in payload)
            if diagnostic_request:
                fields = {"target_universal_id", "session_id", "token", "request_id", "operation", "runtime_id"}
                if (set(payload) not in (fields, fields | {"agent_id"})
                        or not isinstance(payload.get("operation"), str)
                        or payload.get("operation") not in {"bind", "agents", "logs", "inspect"}):
                    return
                from core.python_core.live_diagnostics import tree_snapshot
                master = self.get_agent_tree_master()
                payload = dict(payload)
                # The spawner supplies /comm/; Path discards the trailing slash.
                payload["diagnostic_tree"] = tree_snapshot(getattr(master, "root", None),
                    Path(self.path_resolution["comm_path"]).parent.name)

            # Private panel configuration should not enter Matrix's ordinary
            # service-request log or fan out to unrelated agent instances.
            private_targeted_request = isinstance(service_role, str) and service_role.startswith(
                ("hive.crypto_alert.", "hive.rsync_boy.", "hive.drop_vault.", "hive.log_health.")
            ) or diagnostic_request
            if private_targeted_request:
                self.log("[SERVICE-REQ] Targeted panel request (payload withheld).")
            else:
                self.log(f'content: {content}')

            if not service_role:
                self.log("[SERVICE-REQ][ERROR] Missing 'service' field.")
                return

            # Use refactored get_nodes_by_role → ServiceEndpoint objects
            endpoints = self.get_nodes_by_role(service_role)
            if not endpoints:
                self.log(f"[SERVICE-REQ] No agents found for role '{service_role}'")
                return

            for ep in endpoints:

                target_uid = ep.get_universal_id()
                handler = ep.get_handler()

                if private_targeted_request and target_uid != payload.get("target_universal_id"):
                    continue

                if not handler or not target_uid:
                    self.log(f"[SERVICE-REQ][WARN] Skipping endpoint {ep}")
                    continue

                # Build command packet
                pk = self.get_delivery_packet("standard.command.packet")
                pk.set_data({
                    "handler": handler,
                    "content": payload,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "origin": self.command_line_args.get("universal_id", "matrix")
                })

                if self.pass_packet(pk, target_uid):
                    self.log(f"[SERVICE-REQ] Routed '{service_role}' → {target_uid} ({handler})")
                else:
                    self.log(f"[SERVICE-REQ][ERROR] Delivery failed for '{service_role}' → {target_uid} ({handler})", level="ERROR")

        except Exception as e:
            self.log(error=e, block="main_try")

    # gives a given agent its agent_tree.json
    #2 types of trees roll through here: Matrix agent_tree_master.json and agents agent_tree.json
    #if encryption is on: every node will have a vault dict, inside contains the node's public key, timestamp issued
    def delegate_tree_to_agent(self, universal_id, tree_path):
        """Generates and delivers a secure, personalized "slice" of the agent tree.
        This method extracts the subtree of a specific agent from the master
        tree. It then securely signs and delivers this personalized
        `agent_tree.json` file to the target agent's `/directive` directory.
        This ensures that each agent only has the structural information it
        needs to manage its own children. It also delivers the agent's signed
        public key to its `/codex` directory for others to retrieve.

        Args:
            universal_id (str): The ID of the agent to deliver the tree slice to.
            tree_path (dict): A dictionary defining the path to the master tree.
        """
        try:
            #load the agent_tree_master

            tp = self.get_agent_tree_master()
            if not tp:
                self.log(f"Failed to load master tree for {universal_id}")
                return

            if not tp.has_node(universal_id):
                self.log(f"Skipping node {universal_id} not found in agent_tree, probably phantom dir created in comm by other agent or process.)")
                return

            subtree = tp.extract_subtree_by_id(universal_id)
            if not subtree:
                self.log(f"No subtree found for {universal_id}, sending empty tree.")
                subtree = {}

            if subtree.get('lifecycle_status',{}).get("op", False) == "shutdown_delete":
                self.log(f"[SPAWN-ERROR] Attempted to spawn deleted agent {universal_id}. Blocking.")
                return

            try:
                #SAVE IDENTITY FILE to comm/{universal_id}/codex
                identity={"identity": subtree.get("vault",{}).get("identity", {}), "sig": subtree.get("vault",{}).get("sig", {})}

                dir = os.path.join(self.path_resolution["comm_path"], universal_id, "codex")
                fpath = os.path.join(dir, "signed_public_key.json")
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump(identity, f, indent=2)
                    f.close()

            except Exception as e:
                self.log(error=e, block='write_signed_public_key')

            # define structured path dict for saving
            path = {
                "path": self.path_resolution["comm_path"],
                "address": universal_id,
                "drop": "directive",
                "name": "agent_tree.json"
            }

            data = {"agent_tree": subtree, 'services': tp.get_minimal_services_tree(universal_id)}

            football = self.get_football(type=self.FootballType.PASS)
            football.load_identity_file(vault=subtree.get("vault"), universal_id=universal_id)
            self.save_directive(path, data, football=football)

            if self.debug.is_enabled():
                self.log(f"Tree delivered to {universal_id}")

        except Exception as e:
            self.log(error=e, block="main_try")

    def get_agent_tree_master(self):
        """Loads the agent_tree_master.json from disk into memory.
        This method acts as a cached loader for the canonical agent tree.
        If the tree is not already in memory, it loads the securely signed
        and encrypted `agent_tree_master.json` file from the Matrix agent's
        own `/directive` directory. It returns a TreeParser object representing
        the entire swarm structure.

        Returns:
            TreeParser: An object representing the entire agent tree, or None.
        """
        if self._agent_tree_master is None:
            football = self.get_football(type=self.FootballType.CATCH)
            self._agent_tree_master = self.load_directive(self.tree_path_dict, football)
            if hasattr(self._agent_tree_master, "root"):
                self._meta = self._agent_tree_master.root.get('meta', {})

            self.log("[TREE] agent_tree_master loaded into memory.")

        return self._agent_tree_master


    def save_agent_tree_master(self, push_tree_home=False):
        """Signs and saves the current state of the in-memory agent tree to disk.

        This method is called whenever the swarm's structure is modified (e.g.,
        after injecting or deleting an agent). It takes the in-memory tree,
        adds any agent identity -- signs with the Matrix private key, generates rsa key pairs, private keys, to any added agents, and then
        securely saves the entire structure back to `agent_tree_master.json`.
        This persists the change and ensures the file on disk is always the
        single source of truth.

        Returns:
            bool: True if the save was successful, False otherwise.
        """
        try:
            if self._agent_tree_master is None:
                self.log("[TREE][WARN] Cannot save — agent_tree_master not loaded.")
                return False

            self._agent_tree_master.pre_scan_for_duplicates(self._agent_tree_master.root)

            data = {"agent_tree": self._agent_tree_master.root, "meta": self.meta}
            football = self.get_football(type=self.FootballType.PASS)
            football.load_identity_file(
                vault=self.tree_node['vault'],
                universal_id=self.get_matrix_universal_id(),
            )
            note_reap_save_attempt(self)
            if not self.save_directive(self.tree_path_dict, data, football=football):
                self.log("[TREE][ERROR] Agent tree could not be saved.")
                return False
            note_reap_save_success(self)

            if self.debug.is_enabled():
                if self.encryption_enabled:
                    self.log("[TREE] agent_tree_master saved and signed.")
                else:
                    self.log("[TREE] agent_tree_master saved.")

            if push_tree_home:
                self.defer_reap_side_effect(self._broadcast_agent_tree)

            return True

        except Exception as e:
            self.log("[TREE][ERROR] Failed to save agent_tree_master.", error=e)
            return False

    def _broadcast_agent_tree(self):
        """Publish an outbound tree only after the lifecycle commit."""
        alert_role = self.tree_node.get("rpc_router_role", "hive.rpc")
        if alert_role:
            remote_pub_pem = self._signing_keys.get("remote_pubkey")

            # Isolated outbound copy. Scrubbing cannot mutate the master.
            outbound_tree = copy.deepcopy(self._agent_tree_master.root)
            self._strip_sensitive_fields(outbound_tree)

            for ep in self.get_nodes_by_role(alert_role):
                relay_uid = ep.get_universal_id()
                alive_sessions = self.has_fresh_broadcast_flag(relay_uid)

                for sess in alive_sessions:
                    data = {
                        "handler": "agent_tree_master.update",
                        "session_id": sess,
                        "runtime_id": Path(self.path_resolution["comm_path"]).parent.name,
                        "content": outbound_tree,
                    }

                    sealed = encrypt_with_ephemeral_aes(data, remote_pub_pem)

                    content = {
                        "serial": self._serial_num,
                        "content": sealed,
                        "timestamp": int(time.time()),
                    }
                    content["sig"] = sign_data(content, self._signing_key_obj)

                    pk1 = self.get_delivery_packet("standard.command.packet")
                    pk1.set_data({
                        "handler": ep.get_handler(),
                        "origin": self.command_line_args["universal_id"],
                        "session_id": sess,
                        "content": content,
                    })
                    self.pass_packet(pk1, relay_uid)


    def _strip_sensitive_fields(self, value):
        """Remove locally declared sensitive siblings from an outbound copy."""
        if isinstance(value, dict):
            sensitive_fields = value.pop("sensitive_fields", None)

            if isinstance(sensitive_fields, dict):
                field_names = sensitive_fields.keys()
            elif isinstance(sensitive_fields, (list, tuple, set)):
                field_names = sensitive_fields
            else:
                field_names = ()

            for field_name in field_names:
                if isinstance(field_name, str):
                    value.pop(field_name, None)

            for child in value.values():
                self._strip_sensitive_fields(child)

        elif isinstance(value, list):
            for child in value:
                self._strip_sensitive_fields(child)

        return value

    def _perform_agent_consciousness_scan(self, time_delta_timeout=0, flip_threshold=3, flip_window=60):
        if time.time() - self._last_consciousness_scan <= 20:
            return
        return self._perform_guarded_consciousness_scan(time_delta_timeout, flip_threshold, flip_window)

    @reap_mutation
    def _perform_guarded_consciousness_scan(self, time_delta_timeout=0, flip_threshold=3, flip_window=60):
        """
        Evaluates each agent's heartbeat (from poke files) and spawn history (flip-tripping).
        Stores results inside node["agent_status"]. Broadcasts updated tree to relays if live.
        """
        try:
            if (time.time() - self._last_consciousness_scan) > 20:
                self._last_consciousness_scan = time.time()
                now = time.time()

                def recurse(node: dict):
                    if not isinstance(node, dict):
                        return

                    uid = node.get("universal_id")
                    if not uid:
                        return

                    result  = check_heartbeats(self.path_resolution["comm_path"], uid, time_delta_timeout)
                    thread_status = {}
                    if result["meta"]["error_success"]:
                        thread_status = {"error": f"❌ {result['meta']['error']}"}
                    else:
                        for t, info in result["threads"].items():
                            delta = round(info["delta"], 1)
                            thread_status[t] = {
                                "status": info["status"],
                                "last_seen": info["last_seen"],
                                "delta": delta,
                                "timeout": info["timeout"],
                                "sleep_for": info.get("sleep_for", "-"),
                                "wake_due": info.get("wake_due", "-"),
                            }

                    #Spawn analysis
                    spawn_data = analyze_spawn_records(
                        self.path_resolution["comm_path"],
                        uid,
                        flip_threshold=flip_threshold,
                        flip_window=flip_window,
                    )
                    spawn_report = {
                        "count": spawn_data["count"],
                        "latest_timestamp": spawn_data["latest_timestamp"],
                        "flip_tripping": spawn_data["flip_tripping"]
                    }

                    # Load raw spawn records for GUI
                    spawn_dir = os.path.join(self.path_resolution["comm_path"], uid, "spawn")
                    spawn_records = []
                    try:
                        for f in sorted(Path(spawn_dir).glob("*.spawn"), reverse=True)[:5]:  # last 5
                            with open(f, encoding="utf-8") as fh:
                                info = json.load(fh)
                                fh.close()
                                spawn_records.append({
                                    "timestamp": info.get("timestamp"),
                                    "note": info.get("uuid", "")
                                })
                    except Exception:
                        pass

                    if spawn_report["flip_tripping"]:
                        spawn_report["note"] = "flip-tripping detected"

                    node["agent_status"] = {
                        "checked_at": now,
                        "threads": thread_status,
                        "spawn": spawn_report
                    }

                    summary = {
                        "thread_count": result["meta"].get("thread_count", 0),
                        "latest_delta": round(result["meta"].get("latest_delta", 0), 1),
                        "last_seen_any": result["meta"].get("last_seen_any"),
                        "error": result["meta"].get("error"),
                        "error_success": result["meta"].get("error_success"),
                    }

                    node.setdefault("meta", {})

                    node["meta"].update({
                        "threads": [
                            {
                                "thread": t,
                                "status": info.get("status", "-"),
                                "delta": round(info.get("delta", 0), 1),
                                "timeout": info.get("timeout", "-"),
                                "sleep_for": info.get("sleep_for", "-"),
                                "wake_due": info.get("wake_due", "-"),
                            }
                            for t, info in result["threads"].items()
                        ],
                        "summary": summary,
                        "spawn": spawn_report.get("count", 0),
                        "flipping": spawn_report.get("flip_tripping", False),
                        "name": node["name"],
                        "universal_id": uid
                    })

                    node["meta"]["spawn_info"] = spawn_records

                    for child in node.get("children", []):
                        recurse(child)

                recurse(self._agent_tree_master.root)

                # Push tree if relays are alive
                alert_role = self.tree_node.get("rpc_router_role", "hive.rpc")
                live_relays = [
                    ep for ep in self.get_nodes_by_role(alert_role)
                    if self.has_fresh_broadcast_flag(ep.get_universal_id())
                ]

                if not self.save_agent_tree_master(push_tree_home=bool(live_relays)):
                    raise RuntimeError("Agent status could not be saved")
                self.commit_reap_mutation()
                if not live_relays and self.debug.is_enabled():
                    self.log("[TREE] Skipped broadcast (no fresh relays)")

        except Exception as e:
            self.log(error=e, block="main_try")

    def has_fresh_broadcast_flag(self, universal_id: str, threshold: int = 30) -> list[str]:
        """
        Checks whether any connected.flag* exists for the agent and is fresh.

        Args:
            universal_id (str): Agent UID to check.
            threshold (int): Max age (seconds) before a flag is considered stale.

        Returns:
            list[str]: A list of session_ids (or "legacy" for old style) that are alive.
        """
        base = os.path.join(
            self.path_resolution["comm_path"],
            universal_id,
            "broadcast"
        )
        if not os.path.isdir(base):
            return []

        now = time.time()
        alive_sessions = []

        for fname in os.listdir(base):
            if not fname.startswith("connected.flag"):
                continue

            fpath = os.path.join(base, fname)
            age = now - os.path.getmtime(fpath)
            if age < threshold:
                sid = fname.replace("connected.flag.", "")
                alive_sessions.append(sid)
            else:
                self.log(f"[BROADCAST] Flag stale: {fname} ({int(age)}s old)")

        return alive_sessions

    def cmd_deliver_agent_tree_to_child(self, content, packet, identity: IdentityObject = None):
        """
        Handles delivery of the current agent tree to a verified child agent.

        This command is typically triggered when a child agent requests its
        delegated slice of the overall swarm tree (e.g., via `request_agent_tree()`).
        Matrix verifies the sender’s identity, determines the requesting agent’s
        universal ID, and then sends the appropriate portion of the agent tree
        to that agent.

        Behavior:
            - If encryption is disabled, the universal_id is read directly from the
              packet content.
            - If encryption is enabled, the universal_id is extracted from the verified IdentityObject.
            - Logs an error and aborts if the universal_id cannot be determined.

        Args:
            content (dict): The packet’s inner content dictionary. Expected to contain
                "universal_id" when encryption is disabled.
            packet (dict): The full command packet structure that invoked this handler.
            identity (IdentityObject, optional): A verified sender identity object
                provided by the cryptographic layer. Used to confirm the source and
                extract its universal_id when encryption is active.

        Returns:
            None

        Raises:
            Logs any unexpected exceptions internally via `self.log()`.
        """
        try:

            uid = None
            if not self.encryption_enabled:
                uid = content.get("universal_id", False)  # swarm running in plaintext mode

            else:
                # reject invalid or missing identity
                if isinstance(identity, IdentityObject) and identity.has_verified_identity():
                     uid = identity.get_sender_uid()

            if not uid:
                self.log("[DELIVER-TREE][ERROR] Missing universal_id.")
                return

            self.delegate_tree_to_agent(uid, self.tree_path_dict)

        except Exception as e:
            self.log("[DELIVER-TREE][ERROR]", error=e)

    def _cmd_matrix_reloaded(self, content, packet, identity=None):
        """
        Legacy handler repurposed as a verified destructive teardown.

        Matrix launches ``matrixd kill`` for her own universe. Matrixd levels
        every running agent before removing the encrypted directive, matching
        swarm-key file (when present), and the universe's runtime/static trees.
        The Phoenix vault deployment is intentionally outside this operation.
        """
        try:
            if not isinstance(content, dict) or content.get("confirm_response") != 1:
                self.log(
                    "[MATRIX-DELETE][ERROR] Explicit teardown confirmation "
                    "was not supplied."
                )
                return

            delete_directive_with_key = (
                content.get("delete_directive_with_key") is True
            )
            clean_up = content.get("clean_up") is True
            if clean_up and not delete_directive_with_key:
                self.log(
                    "[MATRIX-DELETE][ERROR] Full runtime/static cleanup "
                    "requires directive/key deletion."
                )
                return

            universe_value = self.command_line_args.get("universe")
            if not isinstance(universe_value, str):
                self.log("[MATRIX-DELETE][ERROR] Current universe is unavailable.")
                return

            universe = universe_value.strip()
            if not universe or not all(
                char.isalnum() or char in "_-" for char in universe
            ):
                self.log(
                    f"[MATRIX-DELETE][ERROR] Invalid current universe: "
                    f"{universe_value!r}"
                )
                return

            # Keep launcher resolution inside this handler. Matrix agents are
            # materialized as generated ``run`` files, so the handler must not
            # depend on a newly added sibling helper being copied with it.
            # Prefer the installed Python entry point under Matrix's current
            # interpreter. This bypasses stale venv/PATH console shims while
            # preserving the exact environment that is already running Matrix.
            launcher = []
            canonical_matrixd = Path("/matrix/scripts/matrixd")
            if canonical_matrixd.is_file():
                launcher = [sys.executable, str(canonical_matrixd)]

            candidates = ["/usr/local/bin/matrixd"]
            reboot_command = self.security_box.get("reboot", "")
            if isinstance(reboot_command, str) and reboot_command.strip():
                try:
                    preserved_argv = shlex.split(reboot_command)
                    boot_index = preserved_argv.index("boot")
                    launcher_prefix = preserved_argv[:boot_index]
                    if (
                        launcher_prefix
                        and Path(launcher_prefix[-1]).name == "matrixd"
                    ):
                        candidates.append(launcher_prefix[-1])
                except (ValueError, TypeError):
                    pass

            installed = shutil.which("matrixd")
            if installed:
                candidates.append(installed)

            seen = set()
            for candidate in candidates if not launcher else ():
                candidate = os.path.expanduser(str(candidate))
                if not os.path.isabs(candidate):
                    candidate = shutil.which(candidate)
                    if not candidate:
                        continue
                candidate = os.path.abspath(candidate)
                if candidate in seen:
                    continue
                seen.add(candidate)

                path = Path(candidate)
                if not path.is_file():
                    continue
                launcher = (
                    [candidate]
                    if os.access(candidate, os.X_OK)
                    else [sys.executable, candidate]
                )
                break

            if not launcher:
                self.log("[MATRIX-DELETE][ERROR] Could not resolve matrixd.")
                return

            self.log(
                "[MATRIX-DELETE] Using launcher: "
                + " ".join(shlex.quote(part) for part in launcher)
            )

            cmd = launcher + ["kill", "--universe", universe]
            if delete_directive_with_key:
                cmd.append("--delete-directive-with-key")
            if clean_up:
                cmd.append("--clean-up")

            # The universe account can level its own processes, but removing
            # a legacy directive from root-owned /matrix/boot_directives needs
            # the exact Railgun-provisioned sudoers grant.  Sudo receives a
            # fixed matrixd argv (validated universe plus one of two cleanup
            # forms); no shell or general root command is exposed.
            if delete_directive_with_key and os.geteuid() != 0:
                sudo = shutil.which("sudo")
                if not sudo:
                    self.log(
                        "[MATRIX-DELETE][ERROR] sudo is unavailable for "
                        "privileged directive cleanup."
                    )
                    return
                cmd = [sudo, "-n"] + cmd

            selected_cleanup = (
                "directive/key and runtime/static trees"
                if clean_up
                else "directive/key"
                if delete_directive_with_key
                else "no remote files"
            )
            self.log(
                f"[MATRIX-DELETE] Leveling universe '{universe}'; selected "
                f"file cleanup: {selected_cleanup}. Vault deployment will "
                "be retained."
            )
            process = subprocess.Popen(
                cmd,
                shell=False,
                start_new_session=True,
                close_fds=True,
            )

            # Catch immediate launch/argument failures before Matrix exits.
            time.sleep(0.25)
            exit_code = process.poll()
            if exit_code not in (None, 0):
                self.log(
                    f"[MATRIX-DELETE][ERROR] matrixd exited immediately "
                    f"with status {exit_code}."
                )
                return

            self.log(
                f"[MATRIX-DELETE] Teardown launched as PID {process.pid}; "
                "Matrix standing down."
            )
            os._exit(0)

        except Exception as e:
            self.log("[MATRIX-DELETE][ERROR] Failed to launch teardown.", error=e)


if __name__ == "__main__":
    agent = Agent()
    agent.boot()

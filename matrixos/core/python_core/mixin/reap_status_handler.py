# Authored by Daniel F MacDonald and ChatGPT aka The Generals
import time, os, secrets, copy, re
from core.python_core.agent_factory.reaper.reaper_factory import make_reaper_node
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.lifecycle_fence import GENERATION_ENV
from core.python_core.reap_revision import (read_reap_authorization, reap_mutation, commit_reap_mutation,
                                            defer_reap_side_effect, ReapTransactionError)
class ReapStatusHandlerMixin:
    # ============================================================
    #  Matrix Handlers
    # ============================================================
    def cmd_reap_authorize(self, content, packet, identity: IdentityObject = None):
        """Answer a fresh Reaper challenge from Matrix's current tree."""
        try:
            reaper_uid = self.meta.get("swarm_state", {}).get("reserved_agent_ids", {}).get("reaper")
            if (not reaper_uid or not isinstance(identity, IdentityObject)
                    or not identity.has_verified_identity() or identity.get_sender_uid() != reaper_uid):
                return
            if not isinstance(content, dict):
                return
            uid, stage = content.get("universal_id"), content.get("stage")
            transaction_id, nonce = content.get("transaction_id"), content.get("nonce")
            stages = {"shutdown_probe", "restart_start", "restart_wait", "restart_escalate", "restart_cleanup",
                      "delete_start", "delete_escalate", "delete_cleanup"}
            if (not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", uid)
                    or stage not in stages or not isinstance(transaction_id, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", transaction_id)
                    or not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{64}", nonce)):
                return
            try:
                state, _ = read_reap_authorization(self._runtime_comm_fd, public_key=self.matrix_pub,
                    universe=self.command_line_args["universe"], boot_id=self.path_resolution["reboot_uuid"],
                    generation=os.environ.get(GENERATION_ENV))
                target = state["targets"].get(uid)
            except Exception:
                state, target = None, None
            operation = target.get("op") if isinstance(target, dict) else None
            valid_op = (operation in ("shutdown_restart", "shutdown_delete") if stage == "shutdown_probe"
                        else operation == ("shutdown_restart" if stage.startswith("restart_") else "shutdown_delete"))
            authorized = bool(isinstance(target, dict) and target.get("locked") is True and valid_op
                              and target.get("transaction_id") == transaction_id and target.get("stage") == stage)
            snapshot = copy.deepcopy(target.get("target_snapshot")) if authorized and stage != "shutdown_probe" else None
            if authorized and stage != "shutdown_probe" and (not isinstance(snapshot, list) or len(snapshot) > 1024):
                authorized = False
                snapshot = None
            response = {"handler": "cmd_reap_authorization", "content": {"universal_id": uid, "stage": stage,
                        "transaction_id": transaction_id, "nonce": nonce, "authorized": authorized,
                        "target_snapshot": snapshot, "revision": state["revision"] if authorized else None}}
            reply = self.get_delivery_packet("standard.command.packet")
            reply.set_data(response)
            if not self.pass_packet(reply, reaper_uid):
                self.log("[REAPER-AUTH] Could not deliver challenge response.", level="ERROR")
        except Exception as exc:
            self.log("[REAPER-AUTH] Challenge failed.", error=exc, level="ERROR")

    @reap_mutation
    def cmd_reap_status(self, content, packet, identity: IdentityObject = None):
        """
        Entry-point for every status packet emitted by the **Reaper** agent.

        Flow
        ----
        1. Verify the caller’s `IdentityObject` belongs to the single,
           Matrix-reserved Reaper UID.
        2. Stamp the target node’s lifecycle with the reported stage/result.
        3. Resolve which internal `_on_reaper_status_*` helper to invoke based
           on the original operation (shutdown, delete, restart, …).
        4. Persist the updated tree.

        Args:
            content: Signed payload from Reaper, e.g.
                `{"universal_id": "agent_42", "stage": "delete_start",
                  "result": {"success": True, "state": "alive"}}`
            packet: Full transport envelope (unused beyond logging).
            identity: Verified caller identity; must match the reserved
                Reaper UID or the packet is silently dropped.

        Side Effects:
            Updates `agent_tree_master` and may fan-out to helper handlers.

        Returns:
            None – all work is side-effect-driven.

        Raises:
            Never.  Exceptions are caught, logged, and swallowed to keep the
            packet listener loop alive.
        """
        try:

            reaper_uid = self.meta.get("swarm_state", {}).get("reserved_agent_ids", {}).get("reaper")
            if (not reaper_uid or not isinstance(identity, IdentityObject)
                    or not identity.has_verified_identity() or identity.get_sender_uid() != reaper_uid):
                self.log("[REAP-STATUS] A verified Reaper identity is required.", level="ERROR")
                return

            uid = content.get("universal_id")
            stage = content.get("stage")
            result = content.get("result", {})

            tp = self.get_agent_tree_master()
            node = tp.get_node(uid) if tp else None

            if not uid or not node:
                self.log(f"[REAP-STATUS] Missing or unknown universal_id {uid} {stage} {result}.")
                return

            lifecycle = node.setdefault("lifecycle_status", {})
            current_stage = lifecycle.get("op_stage")
            if (not lifecycle.get("transaction_id") or content.get("transaction_id") != lifecycle.get("transaction_id")
                    or stage != current_stage
                    or not isinstance(result, dict) or type(result.get("success")) is not bool):
                self.log(f"[REAP-STATUS] Refusing stale or invalid result for {uid} at {stage}.")
                return
            lifecycle["reap_result"] = result
            lifecycle["reported_stage"] = stage  # ← what reaper claims it was doing
            # Every stage must carry its own success; a previous successful
            # probe must never authorize a later failed cleanup or restart.
            lifecycle["success"] = result["success"]
            lifecycle["last_checked"] = time.time()

            # Don't overwrite Matrix's op_stage here.

            # Choose handler based on op type, not on reaper’s stage
            callback_info = lifecycle.get("agent_status_callback", {})
            op = "shutdown_probe" if stage == "shutdown_probe" else callback_info.get("operation", "default")

            self.log(f"[REAP-STATUS] {uid} reported '{stage}' (Matrix stage '{current_stage}') → handler: _on_reaper_status_{op}")

            handler = getattr(self, f"_on_reaper_status_{op}")
            handler(uid, stage, result, callback_info)

            if not self.save_agent_tree_master():
                raise ReapTransactionError("Could not save Reaper status")
            commit_reap_mutation(self)

        except Exception as e:
            self.log(error=e, block="main_try")
            raise

    def _assassin_manager(self):
        now = time.time()
        if self._last_assassin_run + 20 > now:
            return
        self._last_assassin_run = now
        return self._guarded_assassin_manager()

    @reap_mutation
    def _guarded_assassin_manager(self):
        """
        Opportunistic sweeper that */
        every ~20 sec* hunts for nodes stuck in destructive lifecycle stages
        and dispatches a kill list to the Reaper.

        Logic
        -----
        * Skips if called too soon since the last run.
        * Builds a list of target UIDs whose `op_stage` indicates
          shutdown/delete/restart progress has stalled.
        * Ensures a Reaper agent exists (deploys one if missing).
        * Hands the target list to Reaper via `cmd_reap_agents`.

        Returns:
            None
        """
        tp = self.get_agent_tree_master()
        if not tp:
            self.log("[ASSASSIN] No tree loaded.")
            return

        # 1. Find marked nodes
        targets = []
        for uid, node in tp.nodes.items():

            stage = node.get("lifecycle_status", {}).get("op_stage","")
            if stage.startswith("_"):
                if self.debug.is_enabled():
                    self.log(f"[ASSASSIN] 💤 {uid} in mid-stage ({stage}) — skipping.")
                continue

            if stage in (
                    "shutdown_probe", "delete_start", "delete_escalate", "delete_cleanup",
                    "restart_start", "restart_wait", "restart_escalate", "restart_cleanup"
            ):
                targets.append({
                    "universal_id": uid,
                    "op_stage": stage,
                    "transaction_id": node.get("lifecycle_status", {}).get("transaction_id")
                })
                self.log(f"[ASSASSIN] current stage is '{stage}'")

        if not targets:
            return  # nothing to kill

        # 2. Ensure Reaper presence
        reaper_id = (
            self.meta
            .setdefault("swarm_state", {})
            .setdefault("reserved_agent_ids", {})
            .get("reaper")
        )
        if not reaper_id:
            if self.matrix_priv_obj is None:
                self.log(
                    "[ASSASSIN] Reaper creation denied: Matrix signing "
                    "capability is not provisioned."
                )
                return
            reaper_id = f"reaper_{secrets.token_hex(6)}"
            self.meta["swarm_state"]["reserved_agent_ids"]["reaper"] = reaper_id

            reaper_node = make_reaper_node(universal_id=reaper_id)
            tp.insert_node(
                reaper_node,
                parent_universal_id=self.get_matrix_universal_id(),
                matrix_priv_obj=self.matrix_priv_obj,
            )
            if not self.save_agent_tree_master():
                raise ReapTransactionError("Could not save Reaper creation")
            commit_reap_mutation(self)
            defer_reap_side_effect(self, lambda: self.delegate_tree_to_agent(
                self.command_line_args['universal_id'], self.tree_path_dict))


            self.log(f"[ASSASSIN] Reaper {reaper_id} deployed. Waiting for boot.")

            return

        key_path = os.path.join(self.path_resolution["comm_path"], reaper_id, "codex", "signed_public_key.json")
        if not os.path.exists(key_path):
            self.log(f"[ASSASSIN] {reaper_id} not ready (no pubkey yet) — waiting.")
            return

        payload = {"handler": "cmd_reap_agents", "content": {"targets": targets}}
        pk = self.get_delivery_packet("standard.command.packet")
        pk.set_data(payload)
        def dispatch():
            if self.pass_packet(pk, reaper_id):
                self.log(f"[ASSASSIN] Dispatching {len(targets)} targets to {reaper_id}")
            else:
                self.log("[ASSASSIN] Failed to deliver packet to reaper.")
        defer_reap_side_effect(self, dispatch)

    def _reaper_transaction_watcher(self, force=False, tick_window=2):
        now = time.time()
        if not force and now - getattr(self, "_last_reaper_watch_tick", 0) < tick_window:
            return
        self._last_reaper_watch_tick = now
        return self._guarded_reaper_transaction_watcher(force, tick_window)

    @reap_mutation
    def _guarded_reaper_transaction_watcher(self, force=False, tick_window=2):
        """Periodically scan active transactions and promote stages when quorum met.
        This is intentionally simple: gather txn nodes, check reported_stage counts
        and node success/state, and call the existing _transaction_checkpoint when
        a checkpoint condition is satisfied.

        NOTE: By default this runs every `tick_window` seconds (rate-limited via self.meta).
        Quorum watcher for multi-node transactions.

        Called at the end of each packet-listener tick (rate-limited to
        `tick_window` s unless `force=True`).  Promotes a transaction through
        its checkpoint stages once **all** participating nodes report the
        expected `reported_stage` **and** success flag.

        Args:
            force: Bypass the internal rate-limit and run immediately.
            tick_window: Minimum seconds between evaluations.

        Returns:
            None
        """
        try:

            tp = self.get_agent_tree_master()
            if not tp:
                return
            before_tree = copy.deepcopy(tp.root)
            before_meta = copy.deepcopy(self.meta)

            # Build a set of transactions to inspect
            tx_map = {}
            for uid, node in tp.nodes.items():
                life = node.get("lifecycle_status", {})
                tx = life.get("transaction_id")
                if tx:
                    tx_map.setdefault(tx, []).append((uid, node))

            if not tx_map:
                return

            delete_flow = [
                ("shutdown_probe", {"alive", "dead", "already_dead"}, "_shutdown_probe", "delete_start"),
                ("delete_start", {"alive", "dead", "already_dead"}, "_delete_start", "delete_escalate"),
                ("delete_escalate", {"terminated"}, "_delete_escalate", "delete_cleanup"),
                ("delete_cleanup", {"cleaned"}, "_delete_cleanup", "delete_complete"),
            ]

            restart_flow = [
                ("shutdown_probe", {"alive", "dead", "already_dead"}, "_shutdown_probe", "restart_start"),
                ("restart_start", {"alive", "dead"}, "_restart_start", "restart_wait"),
                ("restart_wait", {"pod_cleared"}, "_restart_wait", "restart_cleanup"),
                ("restart_cleanup", {"cleaned"}, "_restart_cleanup", "restart_complete"),
            ]

            # For each transaction, evaluate each checkpoint in order
            #self.log(f"[WATCHER][TRACE] tx_map={len(tx_map)} active transactions found")
            for trans_id, tx_nodes in tx_map.items():

                # Completion keeps transaction metadata for diagnostics. A
                # completed restart also retains the last Reaper report, so
                # it must not be considered for that checkpoint again.
                if all(n.get("lifecycle_status", {}).get("op_stage") == "_complete_callback"
                       for _, n in tx_nodes):
                    continue

                thawed = False
                for uid, n in tx_nodes:
                    life = n.get("lifecycle_status", {})
                    frozen_stage = life.get("checkpoint_frozen_stage")
                    current_stage = life.get("reported_stage")

                    # timed auto-thaw
                    if life.get("checkpoint_frozen") and (time.time() - life.get("last_checked", 0)) > 30:
                        life.pop("checkpoint_frozen", None)
                        life.pop("checkpoint_frozen_stage", None)
                        self.log(f"[WATCHER] Auto-thawed txn {trans_id} after timeout.")
                        thawed = True

                    # event-driven thaw
                    elif frozen_stage and current_stage != frozen_stage:
                        life.pop("checkpoint_frozen", None)
                        life.pop("checkpoint_frozen_stage", None)
                        thawed = True

                if thawed:
                    self.log(f"[WATCHER] thawed transaction {trans_id}")

                total = len(tx_nodes)
                # fast-skip: if transaction already frozen / finalized, _transaction_checkpoint handles stragglers
                if any(n.get("lifecycle_status", {}).get("checkpoint_frozen") for _, n in tx_nodes):
                    continue

                first_node = tx_nodes[0][1]
                op = first_node.get("lifecycle_status", {}).get("op", "")
                checkpoints = restart_flow if "restart" in op else delete_flow


                # For each checkpoint: if ALL nodes have reported_stage==expected AND success==True AND state in allowed_states -> promote
                for expected, allowed_states, mid_stage, next_stage in checkpoints:
                    ready_nodes = [
                        uid for uid, n in tx_nodes
                        if (n["lifecycle_status"].get("reported_stage") == expected or
                            n["lifecycle_status"].get("op_stage") == f"_{expected}")
                    ]
                    if len(ready_nodes) == total:
                        if len(ready_nodes) == total and expected != self.meta.get("_last_quorum"):
                            self.meta["_last_quorum"] = expected
                            self.log(f"[WATCHER][{op.upper()}] txn {trans_id}: quorum met → {expected} → {next_stage}")

                        self._transaction_checkpoint(trans_id, expected, None, next_stage)
                        break

            if tp.root != before_tree or self.meta != before_meta:
                if not self.save_agent_tree_master():
                    raise ReapTransactionError("Could not save Reaper watcher state")
                commit_reap_mutation(self)

        except Exception as e:
            self.log(error=e, level="ERROR", block="_reaper_transaction_watcher")
            raise

    # ============================================================
    #  RESTART FLOW
    # ============================================================

    def _on_reaper_status_restart_subtree(self, uid, stage, result, callback_info):
        """
        Handler for `'restart_subtree'` operations.

        Not yet implemented – reserved for future restart-flow logic.
        """
        pass

    def _on_reaper_status_delete_agent(self, uid, stage, result, callback_info):
        """
        Handler for `'delete_agent'` operations.

        Not yet implemented – will finalize delete-flow specifics.
        """
        pass

    def _on_reaper_status_shutdown_probe(self, uid, stage, result, callback_info):
        """
        Light-weight probe handler.

        Records probe results for every node in the same transaction but
        **does not** advance `op_stage`; the watcher promotes once quorum is
        met.

        Args:
            uid: Target agent UID.
            stage: Always `'shutdown_probe'`.
            result: Probe result dict (e.g., `{"success": True, "state": "dead"}`).
            callback_info: Original lifecycle callback metadata.
        """
        try:
            tp = self.get_agent_tree_master()
            node = tp.get_node(uid)
            if not node:
                return

            lifecycle = node.setdefault("lifecycle_status", {})
            trans_id = lifecycle.get("transaction_id")

            # If this node isn't in a transaction, mark aborted and return early.
            if not trans_id:
                self.log(f"[SHUTDOWN_PROBE] ⚠️ {uid} missing transaction_id — marking shutdown_aborted.")
                lifecycle["op_stage"] = "shutdown_aborted"
                lifecycle["reported_stage"] = stage
                lifecycle["reap_result"] = result
                lifecycle["last_checked"] = time.time()
                self.save_agent_tree_master()
                return

            # Stamp this node with latest reaper info
            lifecycle["reported_stage"] = stage
            lifecycle["reap_result"] = result
            lifecycle["last_checked"] = time.time()


            # Also ensure all nodes that share the transaction at least have a reported_stage (for visibility).
            tx_nodes = self._get_tx_nodes(trans_id)
            for n_uid, n in tx_nodes:
                n_life = n.setdefault("lifecycle_status", {})
                # Do not overwrite existing op_stage, only ensure a reported_stage exists for visibility.
                n_life.setdefault("reported_stage", n_life.get("reported_stage", ""))
                n_life.setdefault("last_checked", n_life.get("last_checked", time.time()))

            target_snapshot = result.get("target_snapshot")
            if result.get("success") and (not isinstance(target_snapshot, list) or len(target_snapshot) > 1024):
                lifecycle["success"] = False
                self.log(f"[SHUTDOWN_PROBE] {uid} returned no valid target snapshot.")
            elif result.get("success"):
                lifecycle["reap_target"] = copy.deepcopy(target_snapshot)
                lifecycle["success"] = True
                lifecycle["op_stage"] = f"_{stage}"
            else:
                lifecycle["success"] = False

            self.save_agent_tree_master()

        except Exception as e:
            self.log(error=e, level="ERROR", block="shutdown_probe_handler")

    # ============================================================
    #  COMMON UTILITIES
    # ============================================================
    def _mark_stage(self, n, stage):
        """
        Convenience helper: synchronously stamp `op_stage` and
        `reported_stage` on a node’s `lifecycle_status`.
        """
        n_life = n.setdefault("lifecycle_status", {})
        n_life["op_stage"] = stage
        n_life["reported_stage"] = stage

    def _get_tx_nodes(self, trans_id):
        """
        Return **all** nodes participating in a given transaction.

        Args:
            trans_id: Transaction ID string.

        Returns:
            List of `(uid, node_dict)` tuples (may be empty).
        """
        tp = self.get_agent_tree_master()
        return [(uid, n) for uid, n in tp.nodes.items()
                if n.get("lifecycle_status", {}).get("transaction_id") == trans_id]

    @reap_mutation
    def _transaction_checkpoint(self, trans_id, expected_stage, mid_stage, next_stage):
        """
        Promote an entire transaction from *expected_stage* → *next_stage*
        once every node has reported success.

        Also fires the appropriate “complete” callback (`_delete_complete_…`
        or `_restart_complete_…`) when the terminal stage is reached.

        Returns:
            True if a promotion occurred, False otherwise.
        """
        try:
            tx_nodes = self._get_tx_nodes(trans_id)
            if not tx_nodes:
                self.log(f"[CHECKPOINT] txn {trans_id}: no nodes found, skipping.")
                return False

            total = len(tx_nodes)
            ready = []
            allowed_states = {
                "shutdown_probe": {"alive", "dead", "already_dead"},
                "delete_start": {"alive", "dead", "already_dead"},
                "delete_escalate": {"terminated"},
                "delete_cleanup": {"cleaned"},
                "restart_start": {"alive", "dead", "pod_cleared"},
                "restart_wait": {"pod_cleared"},
                "restart_escalate": {"terminated"},
                "restart_cleanup": {"cleaned"},
            }.get(expected_stage, set())

            # Anyone that has either reported or sits underscored is ready
            for uid, n in tx_nodes:
                life = n.get("lifecycle_status", {})
                reported = life.get("reported_stage", "").strip()
                op_now = life.get("op_stage", "").strip()
                success = life.get("success", False)

                if (reported != expected_stage and op_now != f"_{expected_stage}"):
                    self.log(f"[WATCHER][DEBUG] {uid} stage mismatch → reported='{reported}', op='{op_now}'")

                if not success:
                    self.log(f"[WATCHER][DEBUG] {uid} not successful")

                result = life.get("reap_result", {})
                state = result.get("state") if isinstance(result, dict) else None
                if (reported == expected_stage or op_now == f"_{expected_stage}") and success is True and state in allowed_states:
                    ready.append(uid)

            if len(ready) < total:
                waiting = [u for u, _ in tx_nodes if u not in ready]
                self.log(f"[CHECKPOINT] txn {trans_id}: waiting on {waiting}")
                return False


            for uid, n in tx_nodes:
                life = n.get("lifecycle_status", {})
                #already handled this
                op_stage= life["op_stage"]
                if op_stage.startswith("_complete_callback"):
                    return
                life["op_stage"] = next_stage
                life["success"] = False
                life["last_checked"] = time.time()

            if not self.save_agent_tree_master():
                raise ReapTransactionError("Could not save checkpoint")

            self.log(f"[CHECKPOINT] txn {trans_id}: quorum met → {expected_stage} → {next_stage}")

            if next_stage.endswith("_complete"):

                op_type = next_stage.split("_")[0]  # "delete" or "restart"
                tx_nodes = self._get_tx_nodes(trans_id)

                # default local fallbacks
                local_map = {
                    "delete": self._delete_complete_callback,
                    "restart": self._restart_complete_callback
                }

                # all nodes have reported success → finalize once for the group
                cb_name = None
                if tx_nodes:
                    # just look at the first node's callback metadata
                    cb_name = (
                        tx_nodes[0][1].get("lifecycle_status", {})
                        .get("agent_status_callback", {})
                        .get("on_complete")
                    )

                if cb_name and callable(getattr(self, cb_name, None)):
                    getattr(self, cb_name)(tx_nodes, trans_id=trans_id)
                elif op_type in local_map:
                    local_map[op_type](tx_nodes, trans_id=trans_id)

            if not self.save_agent_tree_master():
                raise ReapTransactionError("Could not save completed checkpoint")
            commit_reap_mutation(self)
        except Exception as e:
            self.log(error=e, level="ERROR", block="_transaction_checkpoint")
            raise

        return True

    def _delegate_transaction_parent(self, tx_nodes, trans_id=None):
        """
        After a transaction finalizes, re-delegate the parent slice back to
        the agent just above the now-completed subtree – keeps the swarm’s
        tree slices in sync.

        Silently no-ops if `trans_id` or `tx_nodes` is falsy.
        """
        if not trans_id or not tx_nodes:
            return

        tp = self.get_agent_tree_master()
        if not tp:
            return

        subtree_root_uid = None
        for uid, node in tx_nodes:
            parent = tp.find_parent_of(uid)
            if not parent:
                continue
            parent_tx = parent.get("lifecycle_status", {}).get("transaction_id")
            if parent_tx != trans_id:
                subtree_root_uid = uid
                break

        if subtree_root_uid:
            root_parent = tp.find_parent_of(subtree_root_uid)
            parent_id = root_parent.get("universal_id") if root_parent else None
            if parent_id:
                self.delegate_tree_to_agent(parent_id, self.tree_path_dict)
                self.log(f"[REAPER] 🔁 Delegated parent {parent_id} (root of txn {trans_id})")

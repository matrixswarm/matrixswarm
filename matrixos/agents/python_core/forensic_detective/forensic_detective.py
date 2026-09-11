# Authored by Daniel F MacDonald and ChatGPT aka The Generals
import sys
import os

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import importlib
import time
import json
import hashlib
import uuid
from collections import OrderedDict

from core.python_core.boot_agent import BootAgent
from core.python_core.agent_factory.oracle.oracle_query_mixin import OracleQueryMixin
from core.python_core.mixin.encrypted_state import EncryptedStateMixin
from forensic_detective.oracle_investigation import (
    build_oracle_messages,
    parse_oracle_analysis,
    render_oracle_alert,
)


class Agent(OracleQueryMixin, EncryptedStateMixin, BootAgent):
    def __init__(self):
        super().__init__()
        self.name = "ForensicDetective"
        self.event_buffer = OrderedDict()
        self.buffer_size = 100
        self.correlation_window_sec = 120
        self.service_name = ""
        self.source_agent = ""

        config = self.tree_node.get("config", {})
        self.alert_cooldown = config.get("alert_cooldown_sec", 300)
        self.alert_role = config.get("alert_to_role", "hive.alert")

        # --- Oracle Integration Config ---
        # Per-directive control; Phoenix enables it in new Forensic Detective
        # nodes, while older directives without the block remain compatible.
        oracle_config = config.get("oracle_analysis", {})
        self.enable_oracle_analysis = bool(oracle_config.get("enable_oracle", 0))
        self.oracle_role = oracle_config.get("role", "hive.oracle")
        self.oracle_timeout = max(
            10, min(600, int(oracle_config.get("timeout_sec", 90)))
        )
        self.oracle_max_context_events = max(
            1, min(30, int(oracle_config.get("max_context_events", 12)))
        )

        self.last_alerts = {}
        self.init_encrypted_state(namespace="forensic_journal")
        self.verify_existing_journal()

    def verify_existing_journal(self):
        """Authenticate a prior incident after boot so key reuse is visible."""
        incidents_dir = self._encrypted_state_root / "incidents"
        entries = sorted(
            incidents_dir.glob("*.json.aes") if incidents_dir.exists() else (),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        state_id = self._encrypted_state_identity
        if not entries:
            self.log(
                f"[PERSISTENCE] Encrypted forensic journal ready for "
                f"state_id={state_id}; no prior incidents found."
            )
            return

        latest_path = entries[0]
        incident_id = latest_path.name.removesuffix(".json.aes")
        try:
            restored = self.load_encrypted_state(
                incident_id,
                directory="incidents",
            )
            if not isinstance(restored, dict):
                raise ValueError("incident payload is not an object")
            if restored.get("incident_id") != incident_id:
                raise ValueError("incident identity does not match its filename")
        except Exception as exc:
            self.log(
                f"[PERSISTENCE] FAILED to authenticate existing forensic "
                f"journal for state_id={state_id}: {exc}",
                level="CRITICAL",
            )
            raise

        self.log(
            f"[PERSISTENCE] Reopened encrypted forensic journal for "
            f"state_id={state_id}; authenticated latest incident "
            f"{incident_id} ({len(entries)} stored)."
        )

    def _hash_event(self, event_data):
        """Creates a consistent hash based on the event's content."""
        event_string = json.dumps({
            k: event_data[k] for k in sorted(event_data) if k != 'timestamp'
        }, sort_keys=True).encode('utf-8')
        return hashlib.sha256(event_string).hexdigest()

    def should_alert(self, key):
        """Checks if an alert should be sent based on the cooldown period."""
        now = time.time()
        last_alert_time = self.last_alerts.get(key, 0)
        if (now - last_alert_time) > self.alert_cooldown:
            self.last_alerts[key] = now
            return True
        self.log(f"Alert for '{key}' is on cooldown. Suppressing.", level="INFO")
        return False

    def send_simple_alert(self, message, incident_id, critical_event, title_prefix="🔬 Forensic Report"):
        """Constructs and sends a unified alert packet with both text and embed data."""
        if not self.alert_role:
            self.log("missing an alert_role self.alert_role", level="ERROR")
            return
        endpoints = self.get_nodes_by_role(self.alert_role)
        if not endpoints:
            self.log(f"No alert-compatible agents found for '{self.alert_role}'.", level="ERROR")
            return

        trigger_service = critical_event.get('service_name', 'unknown')
        trigger_status = critical_event.get('status', 'unknown')

        simple_formatted_msg = (
            f"{title_prefix}: {trigger_service.capitalize()} is {trigger_status.upper()}\n"
            f"ID: {incident_id}\n---\n{message}"
        )

        embed_data = {
            "title": f"{title_prefix}: {trigger_service.capitalize()} Failure",
            "description": f"**Trigger:** `{trigger_service}` reported as `{trigger_status}`.\n---\n**Analysis:**\n{message}",
            "color": "red" if title_prefix.startswith("🔬") else "blue",
            "footer": f"Incident ID: {incident_id}"
        }

        pk = self.get_delivery_packet("notify.alert.general")
        pk.set_data({
            "msg": message,
            "formatted_msg": simple_formatted_msg,
            "embed_data": embed_data,
            "cause": "Forensic Analysis Report",
            "origin": self.command_line_args.get("universal_id")
        })

        cmd_pk = self.get_delivery_packet("standard.command.packet")
        cmd_pk.set_data({"handler": "cmd_send_alert_msg"})
        cmd_pk.set_packet(pk, "content")

        for ep in endpoints:
            cmd_pk.set_payload_item("handler", ep.get_handler())
            self.pass_packet(cmd_pk, ep.get_universal_id())

    def cmd_ingest_status_report(self, content, packet, identity=None):
        """Handler for receiving data. Triggers forensics on CRITICAL events."""
        try:
            status_data = content
            self.source_agent = status_data.get('source_agent', 'unknown_agent')
            self.service_name = status_data.get('service_name', 'unknown_service')
            severity = status_data.get('severity', 'INFO').upper()
            self.log(f"[INGEST] ✅ Received '{severity}' report from '{self.source_agent}' for service '{self.service_name}'.")

            event_hash = self._hash_event(status_data)
            now = time.time()

            if event_hash not in self.event_buffer:
                self.event_buffer[event_hash] = {'count': 0, 'first_seen': now, 'event_data': status_data}
            self.event_buffer[event_hash]['count'] += 1
            self.event_buffer[event_hash]['last_seen'] = now
            self.event_buffer.move_to_end(event_hash)

            if len(self.event_buffer) > self.buffer_size:
                self.event_buffer.popitem(last=False)

            service_name = status_data.get('service_name', 'unknown_service')

            if severity == "CRITICAL" and self.should_alert(service_name):
                incident_id = str(uuid.uuid4())
                self.log(f"CRITICAL event for '{service_name}' triggered a new incident: {incident_id}")

                correlated_events = [
                    event['event_data'] for event in self.event_buffer.values()
                    if (now - event['last_seen']) < self.correlation_window_sec
                ]

                forensic_findings_list = self.run_forensics(status_data['service_name'], correlated_events)
                full_forensic_report = "\n".join(forensic_findings_list)
                concise_alert_summary = forensic_findings_list[0] if forensic_findings_list else "Forensic analysis could not be completed."

                oracle_state = {
                    "status": "pending" if self.enable_oracle_analysis else "disabled"
                }
                self.save_event_summary(
                    incident_id,
                    status_data,
                    correlated_events,
                    full_forensic_report,
                    oracle_analysis=oracle_state,
                )

                # --- STAGE 1: Send Immediate Alert ---
                self.send_simple_alert(concise_alert_summary, incident_id, status_data)

                # --- STAGE 2: Request Oracle Analysis ---
                if self.enable_oracle_analysis:
                    self._request_oracle_analysis(
                        incident_id,
                        status_data,
                        correlated_events,
                        full_forensic_report,
                    )

        except Exception as e:
            self.log(error=e, level="ERROR", block="main_try")

    def _request_oracle_analysis(
        self,
        incident_id,
        critical_event,
        correlated_events,
        forensic_report,
    ):
        """Send a redacted incident evidence bundle through the Oracle mixin."""
        query = self.get_oracle_query_object()
        query.oracle_role = self.oracle_role
        query.response_handler = "_handle_oracle_forensics_result"
        query.json_response = True
        query.timeout_sec = self.oracle_timeout
        query.messages = build_oracle_messages(
            incident_id,
            critical_event,
            correlated_events,
            forensic_report,
            max_context_events=self.oracle_max_context_events,
        )
        query.save_data({
            "incident_id": incident_id,
            "critical_event": critical_event,
        })

        incident = self.load_encrypted_state(
            incident_id,
            default={},
            directory="incidents",
        )
        if isinstance(incident, dict):
            incident["oracle_analysis"] = {
                "status": "pending",
                "query_id": query.query_id,
                "requested_at": time.strftime(
                    '%Y-%m-%dT%H:%M:%SZ', time.gmtime()
                ),
            }
            self.save_encrypted_state(
                incident_id,
                incident,
                directory="incidents",
            )

        self.send_to_oracle(query)

    def _handle_oracle_forensics_result(self, query, response, error=None):
        """Persist Oracle's verdict and emit a concise follow-up alert."""
        incident_id = query.data.get("incident_id")
        if not incident_id:
            self.log("[ORACLE] Result missing incident identity.", level="ERROR")
            return

        incident = self.load_encrypted_state(
            incident_id,
            default={},
            directory="incidents",
        )
        if not isinstance(incident, dict):
            self.log(
                f"[ORACLE] Incident journal missing for {incident_id}.",
                level="ERROR",
            )
            return

        completed_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        if error:
            incident["oracle_analysis"] = {
                "status": "failed",
                "query_id": query.query_id,
                "error": str(error)[:200],
                "completed_at": completed_at,
            }
            self.save_encrypted_state(
                incident_id,
                incident,
                directory="incidents",
            )
            self.log(
                f"[ORACLE] Investigation {incident_id} failed: {error}",
                level="WARNING",
            )
            return

        try:
            analysis = parse_oracle_analysis(response)
        except ValueError as exc:
            incident["oracle_analysis"] = {
                "status": "failed",
                "query_id": query.query_id,
                "error": str(exc),
                "completed_at": completed_at,
            }
            self.save_encrypted_state(
                incident_id,
                incident,
                directory="incidents",
            )
            self.log(
                f"[ORACLE] Invalid investigation for {incident_id}: {exc}",
                level="ERROR",
            )
            return

        incident["oracle_analysis"] = {
            "status": "completed",
            "query_id": query.query_id,
            "completed_at": completed_at,
            "result": analysis,
        }
        self.save_encrypted_state(
            incident_id,
            incident,
            directory="incidents",
        )
        self.log(f"[ORACLE] Investigation completed for {incident_id}.")
        critical_event = query.data.get("critical_event") or incident.get(
            "critical_event", {}
        )
        self.send_simple_alert(
            render_oracle_alert(analysis),
            incident_id,
            critical_event,
            title_prefix="🔮 Oracle Hypothesis",
        )

    def worker(self, config=None, identity=None):
        """Complete Oracle timeout paths while the agent is running."""
        self.check_oracle_timeouts()

    def save_event_summary(
        self,
        incident_id,
        critical_event,
        correlated_events,
        forensic_report,
        oracle_analysis=None,
    ):
        """Saves all event data to a single JSON file for offline analysis."""
        summary_data = {
            "incident_id": incident_id,
            "incident_time": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            "critical_event": critical_event,
            "correlated_events": correlated_events,
            "full_forensic_report": forensic_report,
            "oracle_analysis": oracle_analysis or {"status": "disabled"},
        }
        try:
            self.save_encrypted_state(
                incident_id,
                summary_data,
                directory="incidents",
            )
            self.log(
                f"Encrypted incident journal updated for incident {incident_id}."
            )
        except Exception as e:
            self.log(f"Failed to save encrypted incident journal: {e}", level="ERROR")

    def run_forensics(self, service_name, recent_events):
        """Dynamically loads and runs the appropriate investigator."""
        findings = []
        try:
            mod_path = f"forensic_detective.factory.watchdog.{service_name}.investigator"
            factory_module = importlib.import_module(mod_path)
            Investigator = getattr(factory_module, "Investigator")
            specialized_investigator = Investigator(self, service_name, recent_events)
            return specialized_investigator.add_specific_findings(findings)
        except ImportError:
            self.log(f"No specialized factory for '{service_name}'.", level="INFO")
            return ["No specialized forensic investigator found."]
        except Exception as e:
            self.log(f"Specialized factory failed: {e}", level="ERROR")
            return [f"[!] The specialized '{service_name}' investigator failed to run."]


if __name__ == "__main__":
    agent = Agent()
    agent.boot()

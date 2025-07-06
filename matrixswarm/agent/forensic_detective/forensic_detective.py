#Authored by Daniel F MacDonald and Gemini
import sys
import os

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import importlib
import time
import json
import hashlib
import uuid
import requests
from collections import OrderedDict

from matrixswarm.core.boot_agent import BootAgent

class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        self.name = "ForensicDetective"
        self.event_buffer = OrderedDict()
        self.buffer_size = 100
        self.correlation_window_sec = 120
        self.service_name = ""
        self.source_agent = ""
        # Get the alerting role from the directive, with a default fallback
        config = self.tree_node.get("config", {})
        self.alert_cooldown = config.get("alert_cooldown_sec", 300)  # 5 minutes default

        self.alert_role = config.get("alert_to_role", "hive.alert.send_alert_msg")
        self.last_alerts = {}

        self.summary_path = os.path.join(self.path_resolution["comm_path_resolved"], "summary")
        os.makedirs(self.summary_path, exist_ok=True)

    def _hash_event(self, event_data):
        """Creates a consistent hash based on the event's content."""
        # Create a canonical representation of the event to ensure consistent hashing
        # We exclude timestamps and use a sorted list of key-value pairs.
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

    def send_simple_alert(self, message, incident_id, critical_event):

        """Constructs and sends a unified alert packet with both text and embed data."""
        if not self.alert_role: return
        alert_nodes = self.get_nodes_by_role(self.alert_role)
        if not alert_nodes: return

        # --- Refactored to create BOTH formats ---
        trigger_service = critical_event.get('service_name', 'unknown')
        trigger_status = critical_event.get('status', 'unknown')

        # 1. Create the simple text message for basic relays (Telegram, GUI)
        simple_formatted_msg = (
            f"🔬 Forensic Report: {trigger_service.capitalize()} is {trigger_status.upper()}\n"
            f"ID: {incident_id}\n---\n{message}"
        )

        # 2. Create the rich embed data for advanced relays (Discord)
        embed_data = {
            "title": f"🔬 Forensic Report: {trigger_service.capitalize()} Failure",
            "description": f"**Trigger:** `{trigger_service}` reported as `{trigger_status}`.\n---\n**Analysis:**\n{message}",
            "color": "red",
            "footer": f"Incident ID: {incident_id}"
        }

        # 3. Use the standard "notify.alert.general" packet
        pk = self.get_delivery_packet("notify.alert.general")
        pk.set_data({
            "msg": message, # The raw analysis
            "formatted_msg": simple_formatted_msg, # For text-based clients
            "embed_data": embed_data, # For embed-based clients
            "cause": "Forensic Analysis Report",
            "origin": self.command_line_args.get("universal_id")
        })

        # The outer command packet remains the same
        cmd_pk = self.get_delivery_packet("standard.command.packet")
        cmd_pk.set_data({"handler": "cmd_send_alert_msg"}) # Use a single, standard handler
        cmd_pk.set_packet(pk, "content")

        for node in alert_nodes:
            self.pass_packet(cmd_pk, node["universal_id"])

    def cmd_ingest_status_report(self, content, packet, identity=None):
        """
        Handler for receiving data. Triggers forensics on CRITICAL events.
        """
        try:

            status_data = content
            # Log every incoming status report for confirmation of receipt.
            self.source_agent = status_data.get('source_agent', 'unknown_agent')
            self.service_name = status_data.get('service_name', 'unknown_service')
            severity = status_data.get('severity', 'INFO').upper()
            if self.debug.is_enabled():
                self.log(f"[INGEST] ✅ Received '{severity}' report from '{self.source_agent}' for service '{self.service_name}'.")

            event_hash = self._hash_event(status_data)
            now = time.time()

            if event_hash in self.event_buffer:
                # Event is a duplicate, update its entry
                self.event_buffer[event_hash]['count'] += 1
                self.event_buffer[event_hash]['last_seen'] = now
                # Move to the end to mark it as most recently seen
                self.event_buffer.move_to_end(event_hash)
            else:
                # This is a new, unique event
                self.event_buffer[event_hash] = {
                    'event_hash': event_hash,
                    'count': 1,
                    'first_seen': now,
                    'last_seen': now,
                    'event_data': status_data
                }
                # Prune the buffer if it exceeds the max size
                if len(self.event_buffer) > self.buffer_size:
                    self.event_buffer.popitem(last=False)  # Remove the oldest item

            service_name = status_data.get('service_name', 'unknown_service')

            if  (status_data.get("severity") == "CRITICAL" and self.should_alert(service_name)):


                incident_id = str(uuid.uuid4())
                self.log(f"CRITICAL event for '{service_name}' triggered a new incident: {incident_id}")

                # Get correlated events that occurred BEFORE the critical one
                correlated_events = [
                    event for event in self.event_buffer.values()
                    if (now - event['last_seen']) > 0 and (now - event['last_seen']) < self.correlation_window_sec
                ]

                # Run forensics to get the full report findings
                raw_events_for_forensics = [e['event_data'] for e in correlated_events]
                forensic_findings_list = self.run_forensics(status_data['service_name'], raw_events_for_forensics)
                full_forensic_report = "\n".join(forensic_findings_list)

                concise_alert_summary = forensic_findings_list[
                    0] if forensic_findings_list else "Forensic analysis could not be completed."

                self.send_simple_alert(concise_alert_summary, incident_id, status_data)


                # Save the new de-duplicated event summary
                self.save_event_summary(incident_id, status_data, correlated_events, full_forensic_report)

        except Exception as e:
            self.log(error=e, level="ERROR", block="main_try")


    # ... other methods like save_event_summary and run_forensics remain the same ...
    def save_event_summary(self, incident_id, critical_event, correlated_events, forensic_report):
        """Saves all event data to a single JSON file for offline analysis."""
        summary_data = {
            "incident_id": incident_id,
            "incident_time": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            "critical_event": critical_event,
            "correlated_events": correlated_events,
            "full_forensic_report": forensic_report
        }
        filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{critical_event['service_name']}-failure.json"
        filepath = os.path.join(self.summary_path, filename)
        try:
            with open(filepath, 'w') as f:
                json.dump(summary_data, f, indent=4)
            self.log(f"Full incident summary saved to: {filepath}")
        except Exception as e:
            self.log(f"Failed to save event summary: {e}", level="ERROR")

    def run_forensics(self, service_name, recent_events):
        """
        Dynamically loads and runs the appropriate investigator.
        Now returns the full list of findings.
        """
        # ... (Default investigator logic remains the same) ...
        findings = [] # Start with an empty list

        try:
            # Dynamically load the specialized investigator
            mod_path = f"forensic_detective.factory.watchdog.{service_name}.investigator"
            factory_module = importlib.import_module(mod_path)
            Investigator = getattr(factory_module, "Investigator")
            specialized_investigator = Investigator(self, service_name, recent_events)

            # The specialized investigator now returns a list of findings
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
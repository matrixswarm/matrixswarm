# ╔════════════════════════════════════════════════════════════╗
# ║            📅 GOOGLE CALENDAR AGENT (v1) — SCOUT           ║
# ║   Scans calendar events and relays to swarm in real time  ║
# ╚════════════════════════════════════════════════════════════╝

import os
import sys
import json
import time
import datetime
import threading
from google.oauth2 import service_account
from googleapiclient.discovery import build


if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

from agent.core.boot_agent import BootAgent
from agent.core.utils.swarm_sleep import interruptible_sleep

class GoogleCalendarAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        config = tree_node.get("config", {}) if 'tree_node' in globals() else {}
        self.calendar_id = config.get("calendar_id", "primary")
        self.interval = int(config.get("interval", 300))  # every 5 minutes
        self.ahead_minutes = int(config.get("watch_ahead_minutes", 15))
        self.broadcast_to = config.get("broadcast_to", [])
        self.name = "GoogleCalendarAgent"
        self.service = self.setup_calendar_api()

    def setup_calendar_api(self):
        creds_path = os.path.join(self.path_resolution["comm_path_resolved"], "credentials.json")
        scopes = ['https://www.googleapis.com/auth/calendar.readonly']
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
        return build('calendar', 'v3', credentials=creds)

    def worker(self):
        self.log("[CALENDAR] Worker started.")
        while self.running:
            self.check_upcoming_events()
            interruptible_sleep(self, self.interval)

    def check_upcoming_events(self):
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        future = (datetime.datetime.utcnow() + datetime.timedelta(minutes=self.ahead_minutes)).isoformat() + 'Z'
        self.log(f"[CALENDAR] Checking events from {now} to {future}")

        try:
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=now,
                timeMax=future,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])

            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                message = {
                    "msg": f"📅 Upcoming: {event['summary']} at {start}",
                    "uuid": self.command_line_args.get("permanent_id", "calendar-agent-1"),
                    "severity": "info"
                }
                for target in self.broadcast_to:
                    outbox = os.path.join(self.path_resolution["comm_path"], target, "incoming")
                    os.makedirs(outbox, exist_ok=True)
                    fname = f"{int(time.time())}_calendar.msg"
                    with open(os.path.join(outbox, fname), "w") as f:
                        json.dump(message, f, indent=2)
                self.log(f"[CALENDAR] Event broadcasted: {event['summary']}")
        except Exception as e:
            self.log(f"[CALENDAR][ERROR] Failed to fetch events: {e}")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = GoogleCalendarAgent(path_resolution, command_line_args)
    agent.boot()

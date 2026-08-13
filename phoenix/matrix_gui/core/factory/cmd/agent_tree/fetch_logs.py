import time
from matrix_gui.core.factory.base_command import BaseCommand

class FetchLogsCommand(BaseCommand):
    def initialize(self):
        def forward_log(sess=None, ch=None, src=None, payload=None, **_):
            try:
                self.conn.send({
                    "type": "log_update",
                    "session_id": self.sid,
                    "payload": payload
                })
            except Exception as e:
                print(f"[FetchLogs][WARN] Pipe closed for {self.sid}: {e}")

        self.add_listener(f"inbound.verified.agent_log_view.update.{self.sid}", forward_log)
        print(f"[FetchLogs] Initialized for {self.sid}")

    def fire_event(self, target_agent=None, token=None, **_):
        payload = {
            "handler": "cmd_service_request",
            "timestamp": time.time(),
            "ts": time.time(),
            "content": {
                "service": "hive.log",
                "payload": {
                    "target_agent": target_agent,
                    "session_id": self.sid,
                    "token": token,
                    "follow": True,
                    "return_handler": "agent_log_view.update"
                }
            }
        }
        # Send through BaseCommand.send(), let it resolve the channel
        self.send(payload, channel_role="outgoing.command")
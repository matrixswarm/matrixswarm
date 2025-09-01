# modules/swarm/swarm_view_tab.py
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit
from matrix_gui.core.event_bus import EventBus
#from phoenix.state import SwarmState


class SwarmViewTab(QWidget):
    def __init__(self, agent_id=None):
        super().__init__()
        self.agent_id = agent_id

        self.layout = QVBoxLayout(self)

        # Agent Target + Action Panel
        self.agent_label = QLabel(f"Agent Target: {self.agent_id if self.agent_id else 'unknown'}")
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Enter command or directive payload")
        self.inject_button = QPushButton("Inject Agent")
        self.inject_button.clicked.connect(self.inject_clicked)

        # Log Panel (Tab Local)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        #self.layout.addWidget(self.agent_label)
        #self.layout.addWidget(self.cmd_input)
        #self.layout.addWidget(self.inject_button)
        #self.layout.addWidget(QLabel("Logs:"))
        #self.layout.addWidget(self.log_output)



        # Optional: Subscribe to local log stream for this agent
        EventBus.on("log.append", self.append_log)

    def inject_clicked(self):
        if not SwarmState.is_active():
            self.log_output.append("[LOCKED] Vault and Matrix must be active.")
            return

        cmd = self.cmd_input.text().strip()
        if not cmd:
            self.log_output.append("[ERROR] No payload provided.")
            return

        # Normally you'd trigger your agent injector module here
        self.log_output.append(f"[ACTION] Injecting payload to agent {self.agent_id}:")
        self.log_output.append(cmd)
        EventBus.emit("agent.injected", agent_id=self.agent_id, payload=cmd)

    def append_log(self, message, agent=None):
        if agent and self.agent_id and agent != self.agent_id:
            return  # ignore messages for other agents
        self.log_output.append(message)

    def set_agent(self, agent_id):
        self.agent_id = agent_id
        self.agent_label.setText(f"Agent Target: {agent_id}")

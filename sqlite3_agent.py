import sqlite3
import time

class SQLite3Agent:
    def __init__(self, name, mediator):
        self.name = name
        self.mediator = mediator  # Mediator handles message sending
        self.db_name = "mydatabase.db"
        self.is_active = False  # Default to False, agent is down initially
        self.dependencies = {}  # Track dependencies and their status
        self.report_status()  # Report status immediately on initialization

    def report_status(self):
        """Report agent's status to the mediator (up or down)."""
        status = "up" if self.is_active else "down"
        message = f"{self.name} is now {status}."
        self.mediator.send_message(message, sender=self)

    def add_dependency(self, dependency_name, status="up"):
        """Add a dependency for the agent to track."""
        self.dependencies[dependency_name] = status

    def check_dependencies(self):
        """Check the status of all dependencies and report status changes."""
        for dependency_name, status in self.dependencies.items():
            if status == "down":
                self.report_dependency_status(dependency_name, "down")
            elif status == "up":
                self.report_dependency_status(dependency_name, "up")

    def report_dependency_status(self, dependency_name, status):
        """Report the status of the dependency (up/down)"""
        message = f"Dependency {dependency_name} is now {status}."
        self.mediator.send_message(message, sender=self)

    def gossip(self):
        """Send gossip to neighbors via the mediator."""
        message = f"{self.name} is gossiping."
        self.mediator.gossip_message(message, sender=self)

    def receive_message(self, message):
        """Receive and process the message."""
        print(f"{self.name} received message: {message}")
        if "CREATE TABLE" in message:
            self.create_table_from_message(message)
        elif "INSERT INTO" in message:
            self.insert_record_from_message(message)

    def send_message(self, message):
        """Send a message through the mediator."""
        self.mediator.send_message(message, sender=self)

    def create_table_from_message(self, message):
        """Create a table from the received command."""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute(message)  # Execute the SQL command
            conn.commit()
            conn.close()
            success_msg = f"Table creation command executed successfully: {message}"
            self.mediator.send_message(success_msg, sender=self)
        except Exception as e:
            error_msg = f"Error executing create table command: {str(e)}"
            self.mediator.send_message(error_msg, sender=self)

    def insert_record_from_message(self, message):
        """Insert a record from the received command."""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute(message)  # Execute the SQL command
            conn.commit()
            conn.close()
            success_msg = f"Record inserted successfully: {message}"
            self.mediator.send_message(success_msg, sender=self)
        except Exception as e:
            error_msg = f"Error executing insert record command: {str(e)}"
            self.mediator.send_message(error_msg, sender=self)

    def run(self):
        """Run the agent, gossiping and checking health periodically."""
        self.is_active = True  # Mark as active when the agent is running
        print(f"{self.name} is now active.")
        self.report_status()  # Immediately report agent status
        while self.is_active:
            self.gossip()  # Gossip with neighbors via the mediator
            self.check_dependencies()  # Check the health of dependencies
            time.sleep(5)  # Simulate work

    def stop(self):
        """Stop the agent's activity."""
        self.is_active = False
        print(f"{self.name} has been stopped.")
        self.report_status()  # Immediately report agent status when stopped

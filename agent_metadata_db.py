# agent_metadata_db.py
class AgentMetadataDB:
    def __init__(self):
        # Initialize your database connection here
        self.db = {}

    def save_agent_metadata(self, agent_name, status):
        """Save agent status in the database."""
        self.db[agent_name] = status
        print(f"Agent {agent_name} status saved as {status}.")

    def get_saved_agents(self):
        """Retrieve all saved agent metadata from the database."""
        return [{'name': name, 'status': status} for name, status in self.db.items()]

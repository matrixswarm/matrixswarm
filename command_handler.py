import argparse  # Make sure to import argparse
from dynamic_agent import DynamicAgent

class CommandHandler:
    def __init__(self, mediator):
        self.mediator = mediator

    def run(self):
        """Run the command handler with argument parsing."""
        parser = argparse.ArgumentParser(description="Manage agents and system commands")
        
        # Adding 'add' to the list of valid commands
        parser.add_argument('command', choices=['start', 'stop', 'restart', 'status', 'version', 'system_check', 'help', 'add'],
                            help="Command to execute")
        parser.add_argument('agent_name', nargs='?', help="Agent name (optional)")

        args = parser.parse_args()

        if args.command == "start":
            self.start_agent(args.agent_name)
        elif args.command == "stop":
            self.stop_agent(args.agent_name)
        elif args.command == "restart":
            self.restart_agent(args.agent_name)
        elif args.command == "status":
            self.show_agent_status(args.agent_name)
        elif args.command == "version":
            self.print_version()  # Print the system version
        elif args.command == "system_check":
            self.system_check()  # Perform system health check
        elif args.command == "add":
            self.add_agent(args.agent_name)  # New 'add' command
        elif args.command == "help":
            parser.print_help()

    def add_agent(self, agent_name):
        """Add an agent."""
        if agent_name:
            routing_table = self.mediator.get_all_agents()  # Get the routing table from the Mediator
            self.mediator.create_agent(agent_name, routing_table)  # Create the agent and start it
            print(f"Agent {agent_name} added.")
        else:
            print("Please provide the agent name to add.")

    def start_agent(self, agent_name):
        """Start an agent."""
        if agent_name:
            routing_table = self.mediator.get_all_agents()  # Get the routing table from the Mediator
            self.mediator.create_agent(agent_name, routing_table)  # Create the agent and start it
        else:
            print("Please provide the agent name to start.")

    def stop_agent(self, agent_name):
        """Stop an agent."""
        if agent_name:
            self.mediator.stop_agent(agent_name)
        else:
            print("Please provide the agent name to stop.")

    def restart_agent(self, agent_name):
        """Restart an agent."""
        if agent_name:
            self.mediator.restart_agent(agent_name)
        else:
            print("Please provide the agent name to restart.")

    def show_agent_status(self, agent_name):
        """Display the status of an agent."""
        if agent_name in self.mediator.agents:
            agent = self.mediator.agents[agent_name]
            status = agent.get_status()
            print(f"Agent {agent_name} status: {status}")
        else:
            print(f"Agent {agent_name} not found.")

    def print_version(self):
        """Print the system version."""
        version = self.mediator.get_version()  # Get the version from the Mediator
        print(f"System Version: {version}")

    def system_check(self):
        """Perform a system health check (e.g., CPU, memory)."""
        self.mediator.system_check()  # Forward the system check command to Mediator

from command_handler import CommandHandler
from message_queue import MessageQueue
from mediator import Mediator
from messenger_agent import MessengerAgent
from agent_metadata_db import AgentMetadataDB

def main():
    # Initialize Message Queue
    message_queue = MessageQueue()

    # Initialize the MessengerAgent (handles all logging)
    messenger_agent = MessengerAgent(message_queue)

    # Initialize the Mediator (which will handle agent management)
    mediator = Mediator(message_queue, messenger_agent)

    # Initialize the CommandHandler to handle system commands
    command_handler = CommandHandler(mediator)

    # Run the command handler
    command_handler.run()

if __name__ == "__main__":
    main()

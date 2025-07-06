import socket
import threading

class SocketCommunication:
    def __init__(self, host='127.0.0.1', port=65432):
        self.host = host
        self.port = port
        self.socket = None

    def start_server(self):
        """Start the local server for communication (listens on 127.0.0.1)."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self.host, self.port))
        self.socket.listen(1)
        print(f"Server listening on {self.host}:{self.port}...")

        while True:
            client_socket, addr = self.socket.accept()
            print(f"Connection from {addr}")
            threading.Thread(target=self.handle_client, args=(client_socket,)).start()

    def handle_client(self, client_socket):
        """Handle incoming messages from clients."""
        data = client_socket.recv(1024)
        if data:
            print(f"Received message: {data.decode('utf-8')}")
        client_socket.close()

    def send_message(self, message):
        """Send a message to the local server."""
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((self.host, self.port))
        client_socket.sendall(message.encode('utf-8'))
        print(f"Sent message: {message}")
        client_socket.close()



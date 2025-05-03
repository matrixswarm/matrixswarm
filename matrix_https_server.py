# matrix_boot.py — Unified Launch Point for Matrix + HTTPS Interface

from agent.core.live_tree import LiveTree
from matrix import MatrixAgent
from matrix_https_server import MatrixHTTPSServer

path_resolution = {
    "comm_path": "/sites/orbit/python/comm",
    "pod_path": "/sites/orbit/python/pod"
}

command_line_args = {
    "universal_id": "matrix"
}

# Boot MatrixAgent
matrix = MatrixAgent(path_resolution, command_line_args)
matrix.tree = LiveTree()
matrix.tree.load("/deploy/tree.json")

# Start Matrix HTTPS Interface
https_server = MatrixHTTPSServer(
    matrix,
    cert_path="/sites/orbit/python/certs/server.crt",
    key_path="/sites/orbit/python/certs/server.key",
    client_ca="/sites/orbit/python/certs/client.crt"
)
https_server.start_payload_scanner()
https_server.start()

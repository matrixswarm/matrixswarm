"""Defense in depth for trusted tests, NOT an OS security sandbox."""
import ipaddress
import os
from pathlib import Path
import sys
import subprocess


def install_guards(sandbox, allowed_child=None):
    sandbox = Path(sandbox).resolve()

    def writable(value):
        if isinstance(value, int) or value is None:
            return
        path = Path(os.fsdecode(value)).resolve()
        if path != sandbox and sandbox not in path.parents:
            raise PermissionError("LAB_WRITE_OUTSIDE_SANDBOX")

    def audit(event, args):
        if event == "open":
            _, mode, flags = args
            if (mode and any(c in mode for c in "wax+")) or (flags and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                writable(args[0])
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime", "os.truncate"}:
            writable(args[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            writable(args[0])
            writable(args[1])
        elif event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork"} or event.startswith("os.spawn"):
            if event == "subprocess.Popen" and allowed_child:
                argv = args[1]
                if isinstance(argv, (list, tuple)) and tuple(argv) == tuple(allowed_child):
                    return
                # Windows exposes the serialized command line in this audit event.
                if os.name == "nt" and isinstance(argv, str) and argv == subprocess.list2cmdline(allowed_child):
                    return
            raise PermissionError("LAB_SUBPROCESS_DENIED: requires a dedicated integration adapter")
        elif event in {"socket.connect", "socket.bind", "socket.sendto"}:
            address = args[-1]
            try:
                allowed = isinstance(address, tuple) and ipaddress.ip_address(address[0]).is_loopback
            except ValueError:
                allowed = False
            if not allowed:
                raise PermissionError("LAB_NON_LOOPBACK_NETWORK_DENIED")
        elif event == "socket.getaddrinfo":
            host = args[0]
            try:
                allowed = ipaddress.ip_address(host).is_loopback
            except ValueError:
                allowed = host == "localhost"
            if not allowed:
                raise PermissionError("LAB_EXTERNAL_DNS_DENIED")

    sys.addaudithook(audit)

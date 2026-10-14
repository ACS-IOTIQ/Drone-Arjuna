"""Forward a Windows serial MAVLink device to the Docker backend.

Usage: python com_bridge.py [COM_PORT|auto] [BAUD|auto] [TCP_PORT]
Default: auto, 115200, 5762
BAUD "auto" tries 460800 (ELRS radio USB), 115200, 57600 (SiK), 921600, 230400 and
keeps the first rate that carries a MAVLink heartbeat.

Security (the MAVLink stream carries no authentication of its own):
  BRIDGE_BIND_ADDR       interface to listen on (default 0.0.0.0 so the Docker
                         backend can reach host.docker.internal; set to a specific
                         interface IP to narrow it)
  BRIDGE_ALLOWED_CLIENTS comma-separated IPs/CIDRs allowed to connect to BOTH the
                         MAVLink port and the discovery port. Default: loopback and
                         private ranges only. Set it to the backend host's address
                         for a tight policy.
"""
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import serial
import serial.tools.list_ports


REQUESTED_PORT = sys.argv[1] if len(sys.argv) > 1 else "auto"
_BAUD_ARG = sys.argv[2] if len(sys.argv) > 2 else "115200"
AUTO_BAUD = _BAUD_ARG.lower() == "auto"
# ELRS radio USB = 460800; USB-CDC flight controllers ignore it; SiK radios = 57600.
AUTO_BAUD_CANDIDATES = [460800, 115200, 57600, 921600, 230400]
BAUD = AUTO_BAUD_CANDIDATES[0] if AUTO_BAUD else int(_BAUD_ARG)   # updated once detected
AUTO_BAUD_LISTEN_S = 2.5   # per baud; MAVLink heartbeats arrive at 1 Hz
TCP_PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 5762
DISCOVERY_PORT = 5761
TCP_PORT_CANDIDATES = [TCP_PORT, 5764, 5770, 5760, 0]

BIND_ADDR = os.environ.get("BRIDGE_BIND_ADDR", "0.0.0.0")
_DEFAULT_ALLOWED = "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16"
ALLOWED_CLIENTS = [
    ipaddress.ip_network(part.strip(), strict=False)
    for part in os.environ.get("BRIDGE_ALLOWED_CLIENTS", _DEFAULT_ALLOWED).split(",")
    if part.strip()
]


# A MAVLink HEARTBEAT frame: v2 = FD, len 9, flags, 0, seq, sys, comp, msgid 0 (3 bytes);
# v1 = FE, len 9, seq, sys, comp, msgid 0.
_HEARTBEAT_FRAME = re.compile(rb"\xfd\x09[\x00\x01]\x00.{3}\x00\x00\x00|\xfe\x09.{3}\x00", re.S)


def looks_like_mavlink(data: bytes) -> bool:
    """True if `data` contains a MAVLink v1/v2 heartbeat frame header."""
    return bool(_HEARTBEAT_FRAME.search(data))


def open_serial_autobaud(device: str):
    """Open `device` at whichever baud rate carries MAVLink. Returns (serial, baud).
    If nothing is heard at any speed (e.g. radio not linked yet) the first candidate
    stays open so data still flows once the link comes up."""
    for baud in AUTO_BAUD_CANDIDATES:
        ser = serial.Serial(device, baud, timeout=0.1, write_timeout=1)
        heard = b""
        deadline = time.monotonic() + AUTO_BAUD_LISTEN_S
        while time.monotonic() < deadline and len(heard) < 4096:
            heard += ser.read(512)
            if looks_like_mavlink(heard):
                return ser, baud
        ser.close()
    first = AUTO_BAUD_CANDIDATES[0]
    print(f"[bridge] no MAVLink heard on {device}; holding {first} baud")
    return serial.Serial(device, first, timeout=0.1, write_timeout=1), first


def client_allowed(host) -> bool:
    """True if `host` is within BRIDGE_ALLOWED_CLIENTS. Unparseable addresses are refused."""
    try:
        addr = ipaddress.ip_address(str(host).split("%")[0])    # drop IPv6 zone id
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr in net for net in ALLOWED_CLIENTS)

_LOCK_FILE = None


def acquire_single_instance_lock():
    """Prevent multiple bridge processes from fighting over the same COM port."""
    global _LOCK_FILE
    lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge.lock")
    _LOCK_FILE = open(lock_path, "w")
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(_LOCK_FILE.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("[bridge] another com_bridge instance is already running; exiting")
            sys.exit(0)
    else:
        import fcntl
        try:
            fcntl.flock(_LOCK_FILE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("[bridge] another com_bridge instance is already running; exiting")
            sys.exit(0)


class SerialDevice:
    def __init__(self):
        self.serial = None
        self.port = None
        self.description = None
        self.tcp_port = None
        self.lock = threading.Lock()
        self.client_lock = threading.Lock()
        self.active_client = False

    def status(self):
        ports = [
            {"port": p.device, "desc": p.description or p.device, "hwid": p.hwid or ""}
            for p in serial.tools.list_ports.comports()
        ]
        return {
            "connected": bool(self.serial and self.serial.is_open),
            "active_port": self.port,
            "description": self.description,
            "baud": BAUD,
            "tcp_port": self.tcp_port or TCP_PORT,
            "ports": ports,
        }

    def connect_forever(self):
        while True:
            if self.serial and self.serial.is_open:
                time.sleep(1)
                continue

            ports = list(serial.tools.list_ports.comports())
            selected = None

            if REQUESTED_PORT.lower() != "auto":
                selected = next((p for p in ports if p.device.upper() == REQUESTED_PORT.upper()), None)
                if not selected:
                    available = ", ".join(p.device for p in ports) or "none"
                    print(
                        f"[bridge] requested {REQUESTED_PORT} not present; "
                        f"auto-scanning available ports: {available}"
                    )

            if not selected and ports:
                selected = sorted(
                    ports,
                    key=lambda p: ("USB" not in (p.hwid or "").upper(), p.device),
                )[0]

            if not selected:
                available = ", ".join(p.device for p in ports) or "none"
                print(f"[bridge] waiting for serial device (available: {available})")
                time.sleep(2)
                continue

            try:
                global BAUD
                if AUTO_BAUD:
                    ser, BAUD = open_serial_autobaud(selected.device)
                else:
                    ser = serial.Serial(selected.device, BAUD, timeout=0.1, write_timeout=1)
                with self.lock:
                    self.serial = ser
                    self.port = selected.device
                    self.description = selected.description or selected.device
                print(f"[bridge] {self.port} opened at {BAUD} baud ({self.description})")
            except (OSError, serial.SerialException) as exc:
                print(f"[bridge] waiting for {selected.device}: {exc}")
                time.sleep(2)

    def mark_disconnected(self):
        with self.lock:
            if self.serial:
                try:
                    self.serial.close()
                except Exception:
                    pass
            self.serial = None
            self.port = None
            self.description = None


device = SerialDevice()


class DiscoveryHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not client_allowed(self.client_address[0]):
            self.send_error(403)
            return
        if self.path != "/ports":
            self.send_error(404)
            return
        body = json.dumps(device.status()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def pipe_serial_to_tcp(ser, sock, stop):
    try:
        while not stop.is_set():
            data = ser.read(512)
            if data:
                sock.sendall(data)
    except serial.SerialException as exc:
        print(f"[bridge] serial connection lost: {exc}")
        device.mark_disconnected()
    except OSError as exc:
        print(f"[bridge] client socket closed while sending serial data: {exc}")
    finally:
        stop.set()


def pipe_tcp_to_serial(sock, ser, stop):
    try:
        while not stop.is_set():
            data = sock.recv(512)
            if not data:
                break
            ser.write(data)
    except serial.SerialException as exc:
        print(f"[bridge] serial connection lost while writing: {exc}")
        device.mark_disconnected()
    except OSError as exc:
        print(f"[bridge] client connection closed: {exc}")
    finally:
        stop.set()


def handle_client(conn, addr):
    if not client_allowed(addr[0]):
        print(f"[bridge] rejected {addr}: address not in BRIDGE_ALLOWED_CLIENTS")
        conn.close()
        return

    with device.client_lock:
        if device.active_client:
            print(f"[bridge] rejected {addr}: another MAVLink client is already connected")
            conn.close()
            return
        device.active_client = True

    with device.lock:
        ser = device.serial
    if not ser or not ser.is_open:
        print(f"[bridge] rejected {addr}: no serial device connected")
        with device.client_lock:
            device.active_client = False
        conn.close()
        return

    try:
        print(f"[bridge] client connected from {addr} -> {device.port}")
        stop = threading.Event()
        threading.Thread(target=pipe_serial_to_tcp, args=(ser, conn, stop), daemon=True).start()
        threading.Thread(target=pipe_tcp_to_serial, args=(conn, ser, stop), daemon=True).start()
        stop.wait()
        conn.close()
        print(f"[bridge] client disconnected from {addr}")
    finally:
        with device.client_lock:
            device.active_client = False


def main():
    acquire_single_instance_lock()
    threading.Thread(target=device.connect_forever, daemon=True).start()
    discovery = ThreadingHTTPServer((BIND_ADDR, DISCOVERY_PORT), DiscoveryHandler)
    threading.Thread(target=discovery.serve_forever, daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    tcp_port = None
    for candidate in TCP_PORT_CANDIDATES:
        try:
            server.bind((BIND_ADDR, candidate))
            tcp_port = server.getsockname()[1]
            break
        except OSError as exc:
            if candidate != 0:
                print(f"[bridge] TCP port {candidate} unavailable: {exc}")

    if tcp_port is None:
        raise OSError("Unable to bind any TCP port for the MAVLink bridge")

    with device.lock:
        device.tcp_port = tcp_port

    server.listen(1)
    if BIND_ADDR == "0.0.0.0":
        print("[bridge] WARNING: listening on all interfaces; clients limited to "
              + ", ".join(str(n) for n in ALLOWED_CLIENTS)
              + " (set BRIDGE_ALLOWED_CLIENTS / BRIDGE_BIND_ADDR to tighten)")
    print(f"[bridge] MAVLink TCP:{tcp_port}; discovery http://localhost:{DISCOVERY_PORT}/ports")
    print(f"[bridge] DroneArjuna: TCP host.docker.internal:{tcp_port}")

    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[bridge] stopped")
    finally:
        discovery.shutdown()
        server.close()
        device.mark_disconnected()


if __name__ == "__main__":
    main()

"""Forward a Windows serial MAVLink device to the Docker backend.

Usage: python com_bridge.py [COM_PORT|auto] [BAUD] [TCP_PORT]
Default: auto, 115200, 5760
"""
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import serial
import serial.tools.list_ports


REQUESTED_PORT = sys.argv[1] if len(sys.argv) > 1 else "auto"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
TCP_PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 5760
DISCOVERY_PORT = 5761
TCP_PORT_CANDIDATES = [TCP_PORT, 5762, 5764, 5770, 0]


class SerialDevice:
    def __init__(self):
        self.serial = None
        self.port = None
        self.description = None
        self.tcp_port = None
        self.lock = threading.Lock()

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
    except (OSError, serial.SerialException) as exc:
        print(f"[bridge] serial connection lost: {exc}")
        device.mark_disconnected()
    finally:
        stop.set()


def pipe_tcp_to_serial(sock, ser, stop):
    try:
        while not stop.is_set():
            data = sock.recv(512)
            if not data:
                break
            ser.write(data)
    except (OSError, serial.SerialException) as exc:
        print(f"[bridge] client connection closed: {exc}")
    finally:
        stop.set()


def handle_client(conn, addr):
    with device.lock:
        ser = device.serial
    if not ser or not ser.is_open:
        print(f"[bridge] rejected {addr}: no serial device connected")
        conn.close()
        return

    print(f"[bridge] client connected from {addr} -> {device.port}")
    stop = threading.Event()
    threading.Thread(target=pipe_serial_to_tcp, args=(ser, conn, stop), daemon=True).start()
    threading.Thread(target=pipe_tcp_to_serial, args=(conn, ser, stop), daemon=True).start()
    stop.wait()
    conn.close()
    print(f"[bridge] client disconnected from {addr}")


def main():
    threading.Thread(target=device.connect_forever, daemon=True).start()
    discovery = ThreadingHTTPServer(("0.0.0.0", DISCOVERY_PORT), DiscoveryHandler)
    threading.Thread(target=discovery.serve_forever, daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    tcp_port = None
    for candidate in TCP_PORT_CANDIDATES:
        try:
            server.bind(("0.0.0.0", candidate))
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

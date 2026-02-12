import socket
import struct
import json
import time

DEFAULT_PORT = 7777


class Connection:
    """Wraps a TCP socket with length-prefixed JSON message framing."""

    def __init__(self, sock):
        self.sock = sock
        self.sock.setblocking(False)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._recv_buffer = b""
        self._send_buffer = b""

    def send_message(self, msg_dict):
        """Queue a JSON message for sending. 4-byte length header + JSON payload."""
        data = json.dumps(msg_dict).encode("utf-8")
        header = struct.pack("!I", len(data))
        self._send_buffer += header + data

    def flush(self):
        """Send buffered data. Returns True if all data sent."""
        if not self._send_buffer:
            return True
        try:
            sent = self.sock.send(self._send_buffer)
            self._send_buffer = self._send_buffer[sent:]
        except BlockingIOError:
            pass
        return len(self._send_buffer) == 0

    def recv_messages(self):
        """Non-blocking receive. Returns list of decoded message dicts."""
        messages = []
        try:
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("Peer disconnected")
            self._recv_buffer += data
        except BlockingIOError:
            pass

        while len(self._recv_buffer) >= 4:
            msg_len = struct.unpack("!I", self._recv_buffer[:4])[0]
            if len(self._recv_buffer) < 4 + msg_len:
                break
            payload = self._recv_buffer[4:4 + msg_len]
            self._recv_buffer = self._recv_buffer[4 + msg_len:]
            messages.append(json.loads(payload.decode("utf-8")))

        return messages

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class NetworkHost:
    """Hosts a game, waits for one peer to connect."""

    def __init__(self, port=DEFAULT_PORT):
        self.port = port
        self.server_sock = None
        self.connection = None
        self.upnp_mapped = False
        self._upnp = None

    def start(self):
        """Open port via UPnP, then listen for a connection."""
        self._try_upnp()
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("", self.port))
        self.server_sock.listen(1)
        self.server_sock.settimeout(0.1)
        print(f"Hosting on port {self.port}... Waiting for peer to connect.")
        if self.upnp_mapped:
            print("UPnP port mapping active. Share your external IP.")
        else:
            print(f"UPnP failed or unavailable. You may need to forward port {self.port} manually.")

    def accept(self):
        """Non-blocking accept. Returns True when connected."""
        if self.connection:
            return True
        try:
            client_sock, addr = self.server_sock.accept()
            print(f"Peer connected from {addr}")
            self.connection = Connection(client_sock)
            return True
        except socket.timeout:
            return False

    def _try_upnp(self):
        """Attempt UPnP port mapping. Best-effort."""
        try:
            import miniupnpc
            upnp = miniupnpc.UPnP()
            upnp.discoverdelay = 200
            upnp.discover()
            upnp.selectigd()
            upnp.addportmapping(
                self.port, 'TCP',
                upnp.lanaddr, self.port,
                'GameOne RTS', ''
            )
            self.upnp_mapped = True
            self._upnp = upnp
        except Exception as e:
            print(f"UPnP: {e}")
            self.upnp_mapped = False

    def cleanup(self):
        """Remove UPnP mapping and close server socket."""
        if self.upnp_mapped and self._upnp:
            try:
                self._upnp.deleteportmapping(self.port, 'TCP')
            except Exception:
                pass
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass


class NetworkClient:
    """Joins a hosted game."""

    def __init__(self, host_ip, port=DEFAULT_PORT):
        self.host_ip = host_ip
        self.port = port
        self.connection = None

    def connect(self, timeout=10.0):
        """Blocking connect to host."""
        print(f"Connecting to {self.host_ip}:{self.port}...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((self.host_ip, self.port))
        sock.settimeout(None)
        self.connection = Connection(sock)
        print("Connected!")
        return True


class NetSession:
    """Manages the multiplayer session during gameplay."""

    def __init__(self, connection, is_host):
        self.conn = connection
        self.is_host = is_host
        self.local_team = "player" if is_host else "ai"
        self.remote_team = "ai" if is_host else "player"

        # Lockstep state
        self.current_tick = 0
        self.tick_interval = 4  # execute commands every N frames
        self.frame_counter = 0

        # Command buffers
        self.local_commands = []
        self.remote_commands = []
        self.pending_remote = {}  # tick -> [commands] for future ticks
        self.remote_tick_ready = False

        # Sync
        self.random_seed = None
        self.connected = True

    def queue_command(self, cmd):
        """Add a command from the local player."""
        self.local_commands.append(cmd)

    def end_tick_and_send(self):
        """Send all local commands for this tick."""
        msg = {
            "type": "tick_commands",
            "tick": self.current_tick,
            "commands": self.local_commands,
        }
        self.conn.send_message(msg)
        self.conn.flush()

    def receive_and_process(self):
        """Process incoming network messages."""
        try:
            messages = self.conn.recv_messages()
        except ConnectionError:
            self.connected = False
            return
        for msg in messages:
            if msg["type"] == "tick_commands":
                tick = msg["tick"]
                if tick == self.current_tick:
                    self.remote_commands = msg["commands"]
                    self.remote_tick_ready = True
                else:
                    self.pending_remote[tick] = msg["commands"]

    def advance_tick(self):
        """Move to next tick after both sides' commands are processed."""
        self.local_commands = []
        self.current_tick += 1
        self.remote_tick_ready = False
        self.remote_commands = []
        if self.current_tick in self.pending_remote:
            self.remote_commands = self.pending_remote.pop(self.current_tick)
            self.remote_tick_ready = True

    def is_tick_frame(self):
        return self.frame_counter % self.tick_interval == 0

    def increment_frame(self):
        self.frame_counter += 1

    def send_handshake(self, seed):
        """Host sends random seed to client."""
        self.random_seed = seed
        self.conn.send_message({"type": "handshake", "seed": seed})
        self.conn.flush()

    def wait_for_handshake(self, timeout=10.0):
        """Client waits for handshake from host."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                messages = self.conn.recv_messages()
            except ConnectionError:
                self.connected = False
                return False
            for msg in messages:
                if msg["type"] == "handshake":
                    self.random_seed = msg["seed"]
                    self.conn.send_message({"type": "handshake_ack"})
                    self.conn.flush()
                elif msg["type"] == "tick_commands":
                    # Buffer any tick commands that arrived early
                    self.pending_remote[msg["tick"]] = msg["commands"]
            if self.random_seed is not None:
                return True
            time.sleep(0.01)
        return False

    def wait_for_handshake_ack(self, timeout=10.0):
        """Host waits for client acknowledgment."""
        start = time.time()
        got_ack = False
        while time.time() - start < timeout:
            try:
                messages = self.conn.recv_messages()
            except ConnectionError:
                self.connected = False
                return False
            for msg in messages:
                if msg["type"] == "handshake_ack":
                    got_ack = True
                elif msg["type"] == "tick_commands":
                    # Buffer any tick commands that arrived early
                    self.pending_remote[msg["tick"]] = msg["commands"]
            if got_ack:
                return True
            time.sleep(0.01)
        return False

    def close(self):
        self.connected = False
        self.conn.close()

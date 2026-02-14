"""Peer-to-peer networking: UDP host/client, reliable delivery, lockstep synchronisation, UPnP."""

import socket
import struct
import json
import time

DEFAULT_PORT = 7777
RETRANSMIT_INTERVAL = 0.03  # resend unacked messages after 30ms
MAX_RETRANSMITS = 170       # give up after ~5s


class Connection:
    """Reliable UDP connection with sequence numbers, ACKs, and retransmit."""

    def __init__(self, sock, peer_addr):
        self.sock = sock
        self.peer_addr = peer_addr
        self._send_seq = 0
        self._recv_seq = -1          # highest seq received in order
        self._seen = set()            # all seqs ever received (for dedup)
        self._unacked = {}            # seq -> (data_bytes, send_time, retransmit_count)
        self._recv_buffer = {}        # seq -> msg_dict (out-of-order buffer)
        # Adaptive RTT (Jacobson/Karels)
        self._rtt_estimate = 0.05    # 50ms initial estimate
        self._rtt_variance = 0.025   # initial variance
        self._rto = 0.15             # retransmit timeout (computed)
        self._send_timestamps = {}   # seq -> first_send_time
        # ACK heartbeat
        self._last_ack_sent = -1     # highest ack value we've sent
        self._last_ack_time = 0.0    # time of last standalone ACK

    def send_message(self, msg_dict):
        """Send a reliable message. Adds seq/ack headers and queues for retransmit."""
        msg_dict["_seq"] = self._send_seq
        msg_dict["_ack"] = self._recv_seq
        data = json.dumps(msg_dict).encode("utf-8")
        header = struct.pack("!I", len(data))
        packet = header + data
        now = time.time()
        try:
            self.sock.sendto(packet, self.peer_addr)
        except (BlockingIOError, OSError):
            pass
        self._send_timestamps.setdefault(self._send_seq, now)
        self._unacked[self._send_seq] = (packet, now, 0)
        # Piggybacked ACK counts as ack sent
        if self._recv_seq >= 0:
            self._last_ack_sent = self._recv_seq
            self._last_ack_time = now
        self._send_seq += 1

    def flush(self):
        """Retransmit unacked messages past timeout. Returns True if all acked."""
        now = time.time()
        dead = []
        for seq, (packet, sent_at, count) in self._unacked.items():
            if now - sent_at >= self._rto:
                if count >= MAX_RETRANSMITS:
                    dead.append(seq)
                    continue
                try:
                    self.sock.sendto(packet, self.peer_addr)
                except (BlockingIOError, OSError):
                    pass
                self._unacked[seq] = (packet, now, count + 1)
        for seq in dead:
            del self._unacked[seq]
        # ACK heartbeat: send standalone ACK if we have unacknowledged recv_seq
        if self._recv_seq > self._last_ack_sent and now - self._last_ack_time >= 0.016:
            ack_msg = json.dumps({"_seq": -1, "_ack": self._recv_seq}).encode("utf-8")
            header = struct.pack("!I", len(ack_msg))
            try:
                self.sock.sendto(header + ack_msg, self.peer_addr)
            except (BlockingIOError, OSError):
                pass
            self._last_ack_sent = self._recv_seq
            self._last_ack_time = now
        return len(self._unacked) == 0

    def recv_messages(self):
        """Non-blocking receive. Returns list of decoded message dicts in order."""
        # Read all available datagrams
        while True:
            try:
                data, addr = self.sock.recvfrom(65536)
            except (BlockingIOError, OSError):
                break
            if len(data) < 4:
                continue
            msg_len = struct.unpack("!I", data[:4])[0]
            if len(data) < 4 + msg_len:
                continue
            payload = data[4:4 + msg_len]
            try:
                msg = json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            seq = msg.pop("_seq", -1)
            ack = msg.pop("_ack", -1)

            # Process ACK: remove acked messages from retransmit buffer + measure RTT
            if ack >= 0:
                to_remove = [s for s in self._unacked if s <= ack]
                for s in to_remove:
                    del self._unacked[s]
                    # Measure RTT from first send time (only for non-retransmitted)
                    if s in self._send_timestamps:
                        rtt_sample = time.time() - self._send_timestamps[s]
                        # Jacobson/Karels algorithm
                        err = rtt_sample - self._rtt_estimate
                        self._rtt_estimate += 0.125 * err
                        self._rtt_variance += 0.25 * (abs(err) - self._rtt_variance)
                        self._rto = max(0.03, min(self._rtt_estimate + 4 * self._rtt_variance, 1.0))
                # Clean up timestamps for acked seqs
                to_clean = [s for s in self._send_timestamps if s <= ack]
                for s in to_clean:
                    del self._send_timestamps[s]

            # Dedup (seq -1 = bare ACK, not a data message)
            if seq < 0 or seq in self._seen:
                continue
            self._seen.add(seq)
            # Cap seen set to prevent unbounded growth
            if len(self._seen) > 1000:
                cutoff = self._recv_seq - 100
                self._seen = {s for s in self._seen if s > cutoff}
            self._recv_buffer[seq] = msg

        # Deliver in-order messages
        messages = []
        while self._recv_seq + 1 in self._recv_buffer:
            self._recv_seq += 1
            messages.append(self._recv_buffer.pop(self._recv_seq))

        # Send proactive ACK so sender stops retransmitting.
        # Uses _seq=-1 so receiver ignores it as a data message (dedup skips it).
        if messages and self._recv_seq >= 0:
            ack_msg = json.dumps({"_seq": -1, "_ack": self._recv_seq}).encode("utf-8")
            header = struct.pack("!I", len(ack_msg))
            try:
                self.sock.sendto(header + ack_msg, self.peer_addr)
            except (BlockingIOError, OSError):
                pass
            self._last_ack_sent = self._recv_seq
            self._last_ack_time = time.time()

        return messages

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class NetworkHost:
    """Hosts a game over UDP, waits for one peer to connect."""

    def __init__(self, port=DEFAULT_PORT):
        self.port = port
        self.sock = None
        self.connection = None
        self.spectator_connection = None
        self._spectator_sock = None  # separate socket for spectator on port+1
        self.upnp_mapped = False
        self._upnp = None

    def start(self):
        """Open port via UPnP, then bind UDP socket."""
        self._try_upnp()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", self.port))
        self.sock.setblocking(False)
        # Separate socket for spectator connections on port+1
        self._spectator_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._spectator_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._spectator_sock.bind(("", self.port + 1))
        self._spectator_sock.setblocking(False)
        print(f"Hosting on port {self.port}... Waiting for peer to connect.")
        print(f"Spectator port: {self.port + 1}")
        if self.upnp_mapped:
            print("UPnP port mapping active. Share your external IP.")
        else:
            print(f"UPnP failed or unavailable. You may need to forward port {self.port} manually.")

    def accept(self):
        """Non-blocking: wait for first datagram from a peer on main socket.
        Also checks the spectator socket for spectator connections."""
        # Check for spectator connections on spectator socket (port+1)
        if not self.spectator_connection and self._spectator_sock:
            try:
                data, addr = self._spectator_sock.recvfrom(65536)
                if len(data) >= 4:
                    msg_len = struct.unpack("!I", data[:4])[0]
                    if len(data) >= 4 + msg_len:
                        payload = data[4:4 + msg_len]
                        try:
                            msg = json.loads(payload.decode("utf-8"))
                            seq = msg.pop("_seq", -1)
                            msg.pop("_ack", -1)
                            print(f"Spectator connected from {addr}")
                            self.spectator_connection = Connection(self._spectator_sock, addr)
                            if seq >= 0:
                                self.spectator_connection._seen.add(seq)
                            self.spectator_connection.send_message({"type": "hello_ack", "spectator": True})
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            pass
            except (BlockingIOError, OSError):
                pass

        if self.connection:
            return True
        try:
            data, addr = self.sock.recvfrom(65536)
            print(f"Peer connected from {addr}")
            # Push data back by creating connection and letting it parse
            self.connection = Connection(self.sock, addr)
            # Parse the hello datagram we just received
            if len(data) >= 4:
                msg_len = struct.unpack("!I", data[:4])[0]
                if len(data) >= 4 + msg_len:
                    payload = data[4:4 + msg_len]
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                        seq = msg.pop("_seq", -1)
                        msg.pop("_ack", -1)
                        if seq >= 0:
                            self.connection._seen.add(seq)
                            self.connection._recv_buffer[seq] = msg
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
            # Send ack back so client knows we received
            self.connection.send_message({"type": "hello_ack"})
            return True
        except (BlockingIOError, OSError):
            return False

    def _try_upnp(self):
        """Attempt UPnP port mapping for UDP."""
        try:
            import miniupnpc
            upnp = miniupnpc.UPnP()
            upnp.discoverdelay = 200
            upnp.discover()
            upnp.selectigd()
            upnp.addportmapping(
                self.port, 'UDP',
                upnp.lanaddr, self.port,
                'GameOne RTS', ''
            )
            self.upnp_mapped = True
            self._upnp = upnp
        except Exception as e:
            print(f"UPnP: {e}")
            self.upnp_mapped = False

    def cleanup(self):
        """Remove UPnP mapping and close sockets."""
        if self.upnp_mapped and self._upnp:
            try:
                self._upnp.deleteportmapping(self.port, 'UDP')
            except Exception:
                pass
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        if self._spectator_sock:
            try:
                self._spectator_sock.close()
            except Exception:
                pass


class NetworkClient:
    """Joins a hosted game over UDP."""

    def __init__(self, host_ip, port=DEFAULT_PORT):
        self.host_ip = host_ip
        self.port = port
        self.connection = None

    def connect(self, timeout=10.0, spectator=False):
        """Send hello to host and wait for acknowledgment."""
        mode_str = "spectator" if spectator else "player"
        print(f"Connecting to {self.host_ip}:{self.port} as {mode_str}...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        peer_addr = (self.host_ip, self.port)
        self.connection = Connection(sock, peer_addr)
        # Send hello and wait for ack
        hello = {"type": "hello"}
        if spectator:
            hello["spectator"] = True
        self.connection.send_message(hello)
        start = time.time()
        while time.time() - start < timeout:
            self.connection.flush()
            messages = self.connection.recv_messages()
            for msg in messages:
                if msg.get("type") == "hello_ack":
                    print("Connected!")
                    return True
            time.sleep(0.01)
        raise ConnectionError(f"Timeout connecting to {self.host_ip}:{self.port}")


class NetSession:
    """Manages the multiplayer session during gameplay."""

    def __init__(self, connection, is_host):
        from settings import TICK_INTERVAL
        self.conn = connection
        self.is_host = is_host
        self.local_team = "player" if is_host else "ai"
        self.remote_team = "ai" if is_host else "player"

        # Lockstep state
        self.current_tick = 0
        self.tick_interval = TICK_INTERVAL  # execute commands every N frames
        self.frame_counter = 0

        # Command buffers
        self.local_commands = []
        self.remote_commands = []
        self.pending_remote = {}  # tick -> [commands] for future ticks
        self.remote_tick_ready = False

        # Sync
        self.random_seed = None
        self.connected = True

        # Chat
        self.chat_messages = []  # incoming chat messages from remote

        # Desync detection
        self.sync_hash = None
        self.remote_sync_hash = None
        self.desync_detected = False

        # Spectator relay
        self.is_spectator = False
        self.spectator_conn = None  # Connection to spectator (host only)

    def queue_command(self, cmd):
        """Add a command from the local player."""
        self.local_commands.append(cmd)

    def end_tick_and_send(self):
        """Send local commands two ticks ahead, giving the network two full tick
        intervals to deliver them before they're needed (jitter buffer)."""
        msg = {
            "type": "tick_commands",
            "tick": self.current_tick + 2,
            "commands": self.local_commands,
        }
        # Include sync hash every 30 ticks for desync detection
        if self.current_tick % 30 == 0 and self.sync_hash is not None:
            msg["sync_hash"] = self.sync_hash
        self.conn.send_message(msg)
        self.conn.flush()

    def relay_to_spectator(self, tick, local_cmds, remote_cmds):
        """Send both teams' commands to the spectator connection."""
        if not self.spectator_conn:
            return
        msg = {
            "type": "spectator_tick",
            "tick": tick,
            "player_commands": local_cmds if self.is_host else remote_cmds,
            "ai_commands": remote_cmds if self.is_host else local_cmds,
        }
        self.spectator_conn.send_message(msg)
        self.spectator_conn.flush()

    def receive_and_process(self):
        """Process incoming network messages."""
        self.conn.flush()  # retransmit unacked
        if self.spectator_conn:
            self.spectator_conn.flush()
        try:
            messages = self.conn.recv_messages()
        except ConnectionError:
            self.connected = False
            return
        for msg in messages:
            msg_type = msg.get("type")
            if msg_type == "tick_commands":
                tick = msg["tick"]
                # Desync detection: check sync hash
                remote_hash = msg.get("sync_hash")
                if remote_hash is not None:
                    self.remote_sync_hash = remote_hash
                    if self.sync_hash is not None and remote_hash != self.sync_hash:
                        self.desync_detected = True
                if tick == self.current_tick:
                    self.remote_commands = msg["commands"]
                    self.remote_tick_ready = True
                else:
                    self.pending_remote[tick] = msg["commands"]
            elif msg_type == "chat":
                self.chat_messages.append(msg)
            elif msg_type == "spectator_tick":
                # Spectator receives both teams' commands
                tick = msg["tick"]
                combined = msg.get("player_commands", []) + msg.get("ai_commands", [])
                if tick == self.current_tick:
                    self.remote_commands = combined
                    self.remote_tick_ready = True
                    # Store split commands for execute_command routing
                    self._spectator_player_cmds = msg.get("player_commands", [])
                    self._spectator_ai_cmds = msg.get("ai_commands", [])
                else:
                    self.pending_remote[tick] = combined
                    # Also store split for later
                    if not hasattr(self, '_spectator_pending'):
                        self._spectator_pending = {}
                    self._spectator_pending[tick] = (
                        msg.get("player_commands", []),
                        msg.get("ai_commands", []),
                    )

    def advance_tick(self):
        """Move to next tick after both sides' commands are processed."""
        self.local_commands = []
        self.current_tick += 1
        self.remote_tick_ready = False
        self.remote_commands = []
        if self.current_tick in self.pending_remote:
            self.remote_commands = self.pending_remote.pop(self.current_tick)
            self.remote_tick_ready = True
            # Restore spectator split commands if available
            if self.is_spectator and hasattr(self, '_spectator_pending'):
                if self.current_tick in self._spectator_pending:
                    p, a = self._spectator_pending.pop(self.current_tick)
                    self._spectator_player_cmds = p
                    self._spectator_ai_cmds = a

    def is_tick_frame(self):
        return self.frame_counter % self.tick_interval == 0

    def increment_frame(self):
        self.frame_counter += 1

    def send_handshake(self, seed):
        """Host sends random seed to client (and spectator if connected)."""
        self.random_seed = seed
        self.conn.send_message({"type": "handshake", "seed": seed})
        self.conn.flush()
        if self.spectator_conn:
            self.spectator_conn.send_message({"type": "handshake", "seed": seed})
            self.spectator_conn.flush()

    def wait_for_handshake(self, timeout=10.0):
        """Client waits for handshake from host."""
        start = time.time()
        while time.time() - start < timeout:
            self.conn.flush()
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
            self.conn.flush()
            try:
                messages = self.conn.recv_messages()
            except ConnectionError:
                self.connected = False
                return False
            for msg in messages:
                if msg["type"] == "handshake_ack":
                    got_ack = True
                elif msg["type"] == "tick_commands":
                    self.pending_remote[msg["tick"]] = msg["commands"]
            if got_ack:
                return True
            time.sleep(0.01)
        return False

    def close(self):
        self.connected = False
        self.conn.close()

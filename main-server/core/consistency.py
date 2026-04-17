import os
import threading
import time
import uuid
import requests
import logging

logger = logging.getLogger(__name__)

class TokenRingManager:
    def __init__(self):
        self.server_id = int(os.environ.get("SERVER_ID", 1))
        self.own_address = os.environ.get("OWN_ADDRESS", "http://main-server-1:8000")
        self.peers = self._parse_peers()

        self.has_token = False
        self.token_epoch = 0 
        self._token_in_use = False   # True while an operation holds the token
        self.token_condition = threading.Condition()

        self.pending_acks = {}
        self.pending_ack_condition = threading.Condition()

        # Keep the token circulating so it doesn't get stuck on an idle server.
        threading.Thread(target=self._idle_token_circulator, daemon=True).start()

    def _parse_peers(self):
        peers = []
        raw = os.environ.get("PEER_SERVERS", "")
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            idx = entry.index(":")
            pid = int(entry[:idx])
            addr = entry[idx + 1:]
            peers.append((pid, addr))
        peers.sort(key=lambda x: x[0])
        return peers

    def other_peers(self):
        return [(pid, addr) for pid, addr in self.peers if pid != self.server_id]

    def next_peer(self):
        ids = [pid for pid, _ in self.peers]
        if self.server_id not in ids:
            return None
        i = ids.index(self.server_id)
        next_i = (i + 1) % len(ids)
        next_id = ids[next_i]
        return next((addr for pid, addr in self.peers if pid == next_id), None)

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _idle_token_circulator(self):
        """
        Pass the token to the next peer whenever this server holds it but
        no operation is actively using it.  This prevents the token from
        stalling on a server that receives no incoming requests, which
        would cause every other server's wait_for_token to time out.
        """
        while True:
            time.sleep(2)
            with self.token_condition:
                should_pass = self.has_token and not self._token_in_use
            if should_pass:
                logger.info(f"[SC] Server {self.server_id} circulating idle token")
                self.pass_token()

    def wait_for_token(self, timeout=None):
        with self.token_condition:
            if not self.has_token:
                self.token_condition.wait(timeout=timeout)
            if self.has_token:
                self._token_in_use = True   # operation is now holding the token
            return self.has_token

    def receive_token(self, epoch=None):
        with self.token_condition:
            if self.has_token:
                logger.warning(f"[SC] Server {self.server_id} already has token — ignoring duplicate")
                return
            # Reject tokens from a stale epoch
            if epoch is not None and epoch < self.token_epoch:
                logger.warning(
                    f"[SC] Server {self.server_id} dropping stale token "
                    f"(token epoch={epoch}, current epoch={self.token_epoch})"
                )
                return
            if epoch is not None:
                self.token_epoch = epoch
            self.has_token = True
            self._token_in_use = False
            self.token_condition.notify_all()
        logger.info(f"[SC] Server {self.server_id} received token (epoch={self.token_epoch})")

    def seed_token(self, new_epoch):
        """Called only by _declare_victory. Bumps the epoch and takes ownership."""
        with self.token_condition:
            self.token_epoch = new_epoch
            self.has_token = True
            self._token_in_use = False
            self.token_condition.notify_all()
        logger.info(f"[SC] Server {self.server_id} seeded token at epoch={new_epoch}")

    def pass_token(self):
        ids = [pid for pid, _ in self.peers]
        if self.server_id not in ids:
            logger.warning(f"[SC] Server {self.server_id} is not in peer list")
            return

        start_i = ids.index(self.server_id)

        for offset in range(1, len(self.peers)):
            next_i = (start_i + offset) % len(self.peers)
            next_id, next_addr = self.peers[next_i]

            try:
                requests.post(f"{next_addr}/token/receive/", json={"epoch": self.token_epoch}, timeout=2)
                with self.token_condition:
                    self.has_token = False
                    self._token_in_use = False
                logger.info(f"[SC] Server {self.server_id} passed token to server {next_id} at {next_addr}")
                return
            except Exception as e:
                logger.warning(f"[SC] Failed to pass token to server {next_id} at {next_addr}: {e}")

        logger.error(f"[SC] Server {self.server_id} could not pass token to any peer")

    # ------------------------------------------------------------------
    # ACK tracking
    # ------------------------------------------------------------------

    def create_pending_ack(self, op_id, expected_count):
        with self.pending_ack_condition:
            self.pending_acks[op_id] = {
                "expected": expected_count,
                "received": 0,
            }

    def receive_ack(self, op_id):
        with self.pending_ack_condition:
            if op_id in self.pending_acks:
                self.pending_acks[op_id]["received"] += 1
                self.pending_ack_condition.notify_all()

    def wait_for_all_acks(self, op_id, timeout=10):
        end_time = time.time() + timeout
        with self.pending_ack_condition:
            while op_id in self.pending_acks:
                info = self.pending_acks[op_id]
                if info["received"] >= info["expected"]:
                    del self.pending_acks[op_id]
                    return True
                remaining = end_time - time.time()
                if remaining <= 0:
                    del self.pending_acks[op_id]
                    return False
                self.pending_ack_condition.wait(timeout=remaining)

token_ring_manager = TokenRingManager()

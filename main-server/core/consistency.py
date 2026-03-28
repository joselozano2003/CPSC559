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
        self.token_condition = threading.Condition()

        self.pending_acks = {}
        self.pending_ack_condition = threading.Condition()

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

    def next_peer(self):
        ids = [pid for pid, _ in self.peers]
        if self.server_id not in ids:
            return None
        i = ids.index(self.server_id)
        next_i = (i + 1) % len(ids)
        next_id = ids[next_i]
        return next((addr for pid, addr in self.peers if pid == next_id), None)

    def wait_for_token(self, timeout=None):
        with self.token_condition:
            if not self.has_token:
                self.token_condition.wait(timeout=timeout)
            return self.has_token

    def receive_token(self):
        with self.token_condition:
            self.has_token = True
            self.token_condition.notify_all()
        logger.info(f"[SC] Server {self.server_id} received token")

    def pass_token(self):
        next_addr = self.next_peer()
        if not next_addr:
            return
        try:
            requests.post(f"{next_addr}/token/receive/", timeout=3)
            with self.token_condition:
                self.has_token = False
            logger.info(f"[SC] Server {self.server_id} passed token to {next_addr}")
        except Exception as e:
            logger.error(f"[SC] Failed to pass token: {e}")

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
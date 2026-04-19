import os
import threading
import time
import uuid
import requests
import logging
from django.db import transaction
from django.db.models import Max
from .models import ReplicatedOperation

logger = logging.getLogger(__name__)

class LeaderConsistencyManager:
    def __init__(self):
        self.server_id = int(os.environ.get("SERVER_ID", 1))
        self.own_address = os.environ.get("OWN_ADDRESS", "http://main-server-1:8000")
        self.peers = self._parse_peers()

        self.sequence_lock = threading.Lock()
        self.sequence_number = 1

        self.pending_acks = {}
        self.pending_ack_condition = threading.Condition()

        # Simple in memory log for now
        # will move to DB model later if we have time
        self.log = {}
        self.commit_index = 0

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

    def allocate_seq_no(self):
        with self.sequence_lock:
            seq_no = self.sequence_number
            self.sequence_number += 1
            return seq_no
    
    def append_log_entry(self, op_type, payload):
        with transaction.atomic():
            max_seq = (
                ReplicatedOperation.objects
                .select_for_update()
                .aggregate(Max("seq_no"))["seq_no__max"]
            )
            next_seq = 1 if max_seq is None else max_seq + 1

            op_id = uuid.uuid4()

            entry = ReplicatedOperation.objects.create(
                seq_no=next_seq,
                op_id=op_id,
                op_type=op_type,
                payload=payload,
                status="pending",
            )

        return {
            "seq_no": entry.seq_no,
            "op_id": str(entry.op_id),
            "op_type": entry.op_type,
            "payload": entry.payload,
            "status": entry.status,
        }
    


    # ------------------------------------------------------------------
    # ACK tracking
    # ------------------------------------------------------------------

    def create_pending_ack(self, seq_no, expected_count):
        with self.pending_ack_condition:
            self.pending_acks[seq_no] = {
                "expected": expected_count,
                "received": 0,
                "acked_by": set(),
            }

    def receive_ack(self, seq_no, server_id):
        with self.pending_ack_condition:
            if seq_no in self.pending_acks:
                info = self.pending_acks[seq_no]
                if server_id not in info["acked_by"]:
                    info["acked_by"].add(server_id)
                    info["received"] += 1
                    self.pending_ack_condition.notify_all()

    def wait_for_quorum(self, seq_no, quorum_size, timeout=10):
        end_time = time.time() + timeout
        with self.pending_ack_condition:
            while seq_no in self.pending_acks:
                info = self.pending_acks[seq_no]
                if info["received"] >= quorum_size:
                    del self.pending_acks[seq_no]
                    return True
                remaining = end_time - time.time()
                if remaining <= 0:
                    del self.pending_acks[seq_no]
                    return False
                self.pending_ack_condition.wait(timeout=remaining)

    def mark_committed(self, seq_no):
        if seq_no in self.log:
            self.log[seq_no]["status"] = "committed"
            self.commit_index = max(self.commit_index, seq_no)
            logger.info(f"[SC] Committed seq={seq_no}")

    def replicate_to_followers(self, entry):
        peer_list = self.other_peers()
        for _, addr in peer_list:
            try:
                requests.post(
                    f"{addr}/sc/replicate/",
                    json={
                        "seq_no": entry["seq_no"],
                        "op_id": entry["op_id"],
                        "op_type": entry["op_type"],
                        "payload": entry["payload"],
                        "leader_address": self.own_address,
                    },
                    timeout=3,
                )
            except Exception as e:
                logger.warning(f"[SC] Failed to replicate seq={entry['seq_no']} to {addr}: {e}")
        return peer_list


consistency_manager = LeaderConsistencyManager()

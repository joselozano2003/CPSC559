import os
import threading
import time
import requests
import logging
from .consistency import token_ring_manager

logger = logging.getLogger(__name__)


class ElectionManager:
    def __init__(self):
        self.server_id = int(os.environ.get('SERVER_ID', 1))
        self.own_address = os.environ.get('OWN_ADDRESS', 'http://main-server-1:8000')
        self.nginx_updater_url = os.environ.get('NGINX_UPDATER_URL', 'http://nginx:8080')
        self.peers = self._parse_peers()    # peers are used during elections to know who to send messages to
        self.storage_nodes = self._parse_storage_nodes()    # used to broadcast the new leader addreess

        self.leader_id = None
        self.leader_address = None  # Tracks who the current leader is
        self.is_running_election = False
        self._last_leader_change = 0.0  # timestamp used to enforce 10s cooldown after a leader change before checking heartbeats again

        # Thread synchronization primitives. Election runs in a background thread and Django handles requests on other threads.
        self._lock = threading.Lock()   # prevents two election threads from starting at the same time
        self._received_bully = threading.Event()   
        self._received_leader = threading.Event()  

    def _parse_peers(self):
        """
            Parses environment variable into a list of (id, address) tuples.
        """
        # Format: 1:http://main-server-1:8000,2:http://main-server-2:8000,...
        peers = []
        raw = os.environ.get('PEER_SERVERS', '')
        for entry in raw.split(','):
            entry = entry.strip()
            if not entry:
                continue
            idx = entry.index(':')
            pid = int(entry[:idx])
            addr = entry[idx + 1:]
            peers.append((pid, addr))
        return peers

    def _parse_storage_nodes(self):
        """
            Parses environment variable into a list of storage node URLs.
        """
        raw = os.environ.get('STORAGE_NODE_URLS', '')
        return [u.strip() for u in raw.split(',') if u.strip()]

    def _higher_peers(self):
        return [(pid, addr) for pid, addr in self.peers if pid > self.server_id]

    def _all_other_peers(self):
        return [(pid, addr) for pid, addr in self.peers if pid != self.server_id]

    # -------------------------------------------------------------------------
    # Election initiation  (Initiate_Election(i) from the pseudocode)
    # -------------------------------------------------------------------------
    def start_election(self):
        with self._lock:
            # If the server is already in an election is already running, do nothing.
            if self.is_running_election:
                return
            # The server is not currently running an election — set the flag and proceed to start one.
            self.is_running_election = True

        logger.info(f"[Server {self.server_id}] Starting election")
        # clear old events from any previous elections
        self._received_bully.clear()
        self._received_leader.clear()

        higher = self._higher_peers()   # get the list of peers with higher IDs

        if not higher:
            # if no higher-id servers exist, I am the highest-ID node — declare victory immediately
            self._declare_victory()
            return

        # Send ELECTION to all higher peers.
        for _, addr in higher:
            try:
                requests.post(
                    f"{addr}/election/",
                    json={"sender_id": self.server_id},
                    timeout=3,  # if there is no response from the POST itself, server is dead, move on.
                )
            except Exception:
                pass

        # Wait 5 seconds for a BULLY response from a higher node
        got_bully = self._received_bully.wait(timeout=5)

        if not got_bully:
            # Before declaring victory, check if a coordinator arrived while
            # coordinator arrived - someone else already won the election
            if self._received_leader.is_set():
                with self._lock:
                    self.is_running_election = False
                return
            # no coordinator received
            self._declare_victory()
        else:
            # A higher node bullied us
            # wait for 15s for their COORDINATOR.
            got_coordinator = self._received_leader.wait(timeout=15)
            if not got_coordinator:
                # Higher node failed before announcing — restart election
                with self._lock:
                    self.is_running_election = False    # Because election skips running for the server that is already running. It needs to be set to false for the server to start the election again.
                self.start_election()
            # else: coordinator received, handled in handle_leader()

    # -------------------------------------------------------------------------
    # Called when this node wins the election
    # -------------------------------------------------------------------------
    def _declare_victory(self):
        logger.info(f"[Server {self.server_id}] I am the new leader")
        self.leader_id = self.server_id
        self.leader_address = self.own_address
        self._last_leader_change = time.time()
        new_epoch = int(time.time())   # monotonically increasing; leader's wall clock is fine
        token_ring_manager.seed_token(new_epoch)
        logger.info(f"[SC] Server {self.server_id} seeded token at epoch={new_epoch}")

        # Broadcast COORDINATOR to all other peers
        for _, addr in self._all_other_peers():
            try:
                requests.post(
                    f"{addr}/leader-announce/",
                    json={"leader_id": self.server_id, "leader_address": self.own_address},
                    timeout=3,
                )
            except Exception:
                pass

        # Broadcast new leader address to all storage nodes so they can send their heartbeats at the right place
        for node_url in self.storage_nodes:
            try:
                requests.post(
                    f"{node_url}/set-leader",
                    json={"leader_address": self.own_address},
                    timeout=3,
                )
            except Exception:
                pass

        # Update Nginx upstream to point at new elected server to route client traffic to the new leader.
        try:
            requests.post(
                f"{self.nginx_updater_url}/set-leader",
                json={"address": self.own_address},
                timeout=3,
            )
        except Exception as e:
            logger.error(f"[Server {self.server_id}] Failed to update Nginx: {e}")

        with self._lock:
            self.is_running_election = False

    # -------------------------------------------------------------------------
    # Message handlers (called from Django views)
    # -------------------------------------------------------------------------
    def handle_election(self, sender_id):
        """
        On receiving election(k) where sender_id == k.
        Returns True if we outrank the sender (i.e. we send back a BULLY message).
        """
        outranks = self.server_id > sender_id
        sender_address = next(
            (addr for pid, addr in self.peers if pid == sender_id), None
        )
        if outranks and sender_address:
            # Always bully the sender — we outrank them
            threading.Thread(
                target=self._send_bully_to,
                args=(sender_address,),
                daemon=True,
            ).start()
            if self.leader_id is not None:
                # We already know who the leader is — forward it to the sender
                # so they accept the result immediately without waiting T2.
                # No need to start a new election.
                threading.Thread(
                    target=self._send_leader_to,
                    args=(sender_address, self.leader_id, self.leader_address),
                    daemon=True,
                ).start()
            elif not self.is_running_election:
                # No known leader yet — start an election
                threading.Thread(target=self.start_election, daemon=True).start()
        return outranks

    # function to send bully message to the lower id servers
    def _send_bully_to(self, address):
        """POST a BULLY message back to the sender on a separate channel."""
        try:
            requests.post(
                f"{address}/bully/",
                json={"from_id": self.server_id},
                timeout=3,
            )
        except Exception:
            pass
    
    # function to send the leader message to all the other servers
    def _send_leader_to(self, address, leader_id=None, leader_address=None):
        """Send a LEADER message to a single node.
        Defaults to announcing self as leader. Pass leader_id and
        leader_address to forward a different node's leadership.
        """
        try:
            requests.post(
                f"{address}/leader-announce/",
                json={
                    "leader_id": leader_id or self.server_id,
                    "leader_address": leader_address or self.own_address,
                },
                timeout=3,
            )
        except Exception:
            pass

    # function for the server to handle the bully message received from the higher id servers
    def handle_bully(self):
        """On receiving a BULLY response — a higher node is alive and taking over."""
        self._received_bully.set()

    def handle_leader(self, leader_id, leader_address):
        """On receiving leader(k)."""
        # The bully algorithm guarantees the highest-ID alive node wins.
        # Never accept the leader message from a node we would outrank — if we
        # are alive and have a higher ID we should have bullied that node
        # already.
        if leader_id < self.server_id:
            logger.info(
                f"[Server {self.server_id}] Ignoring coordinator from lower "
                f"node {leader_id} (we outrank it)"
            )
            return
        self.leader_id = leader_id
        self.leader_address = leader_address
        self._last_leader_change = time.time()
        self._received_leader.set()
        with self._lock:
            self.is_running_election = False
        logger.info(
            f"[Server {self.server_id}] New leader is Server {leader_id} at {leader_address}"
        )

    # -------------------------------------------------------------------------
    # Background health monitor
    # -------------------------------------------------------------------------
    # watches whether the currentl leader is still alive
    def start_monitor(self):
        def _monitor():
            # Give the server time to finish startup before the first election.
            # Higher-ID servers wait less so they always start the election
            # first. Server 5 waits 10s, server 4 waits 11s, ..., server 1 waits 14s.
            # By the time lower servers wake up, they've already received a
            # COORDINATOR from the winner and skip their own election.
            max_id = max(pid for pid, _ in self.peers) if self.peers else self.server_id
            jitter = (max_id - self.server_id) * 1.0
            time.sleep(10 + jitter)
            # Kick off an initial election only if no leader was established
            # during the startup delay (e.g. received a COORDINATOR already).
            if self.leader_id is None:
                threading.Thread(target=self.start_election, daemon=True).start()

            while True:
                time.sleep(5)
                # If we are the leader, nothing to monitor
                if self.leader_id == self.server_id:
                    continue
                # Cooldown: give a newly elected leader time to stabilise
                # before checking its heartbeat. Without this the monitor, it
                # fires immediately after a leader change, which triggers a needless re-election.
                if time.time() - self._last_leader_change < 10:
                    continue
                # Check whether the current leader is still alive
                if self.leader_address:
                    try:
                        r = requests.get(
                            f"{self.leader_address}/heartbeat/", timeout=3
                        )
                        if r.status_code == 200:
                            continue
                    except Exception:
                        pass
                    logger.info(
                        f"[Server {self.server_id}] Leader unreachable — starting election"
                    )
                    # Clear stale leader info so we don't forward a dead
                    # leader's address to other servers during the election.
                    self.leader_id = None
                    self.leader_address = None
                if not self.is_running_election:
                    threading.Thread(target=self.start_election, daemon=True).start()

        threading.Thread(target=_monitor, daemon=True).start()


# Module-level singleton — imported by views and apps
election_manager = ElectionManager()


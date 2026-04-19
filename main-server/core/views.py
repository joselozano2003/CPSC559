import uuid
import os
import requests
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, BasePermission
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from django.db import transaction
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.views.decorators.csrf import csrf_exempt
from .models import *
from .serializers import *
from .s3_utils import S3ImageUploader
from django.http import JsonResponse
from django.db import connection
from django.utils import timezone
from django.conf import settings
from rest_framework.views import APIView
from django.db import transaction
from datetime import timedelta
from .models import File, Chunk, StorageNode, ChunkReplica, PendingDelete
from .serializers import FileUploadRequestSerializer, FileUploadResponseSerializer
from .consistency import consistency_manager
import time
import logging
logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT = 30  # seconds
REPLICATION_FACTOR = 5
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "cps559-internal-key")

def get_active_nodes():
    cutoff = timezone.now() - timedelta(seconds=HEARTBEAT_TIMEOUT)
    return StorageNode.objects.filter(is_active=True, last_heartbeat__gte=cutoff)
class IsOwnerOrReadOnly(BasePermission):
    """
    Custom permission to only allow users to edit their own profile.
    """
    def has_object_permission(self, request, view, obj):
        # Read permissions for any authenticated user
        if request.method in ['GET']:
            return True

        # Write permissions only to the owner of the profile
        return obj.user_id == request.user.user_id


class IsOwner(BasePermission):
    """
    Custom permission to only allow users to access their own data.
    """
    def has_object_permission(self, request, view, obj):
        # Only allow access if the user owns this object
        return obj.user_id == request.user.user_id


def get_tokens_for_user(user):
    """Generate JWT tokens for our custom User model"""
    # User model now has all required Django authentication attributes
    refresh = RefreshToken.for_user(user)

    # Add custom claims
    refresh['user_id'] = user.user_id
    refresh['email'] = user.email

    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


def health_check(request):
    """
    Health check endpoint that verifies database connectivity
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        return JsonResponse({
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'database': 'connected'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'unhealthy',
            'timestamp': timezone.now().isoformat(),
            'database': 'disconnected',
            'error': str(e)
        }, status=503)


def _get_leader_address_if_not_self():
    from .election import election_manager
    this_server_id = int(os.environ.get("SERVER_ID", 1))

    if election_manager.leader_id is None:
        raise RuntimeError("No leader elected yet")

    if election_manager.leader_id == this_server_id:
        return None

    return election_manager.leader_address

# helper to detect whether this server is leader, and get the leader's address:
def _leader_forward_address():
    from .election import election_manager

    this_server_id = int(os.environ.get("SERVER_ID", 1))

    if election_manager.leader_id is None:
        raise RuntimeError("No leader elected yet")

    if election_manager.leader_id == this_server_id:
        return None  # this server is leader

    return election_manager.leader_address

# helper to forward a request to the leader and return the response, 
# or None if this server is the leader and caller
def _forward_to_leader(request, path, method="POST"):
    leader_address = _leader_forward_address()
    if leader_address is None:
        return None  # caller should handle locally

    headers = {}
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth
    if request.content_type:
        headers["Content-Type"] = request.content_type

    url = f"{leader_address}{path}"

    if method == "POST":
        resp = requests.post(url, json=request.data, headers=headers, timeout=60)
    elif method == "DELETE":
        resp = requests.delete(url, headers=headers, timeout=60)
    else:
        raise ValueError(f"Unsupported forward method: {method}")

    try:
        body = resp.json()
    except Exception:
        body = {"error": resp.text}

    return Response(body, status=resp.status_code)

# ---------------------------------------------------------------------------
# Sequential Consistency
# ---------------------------------------------------------------------------

def _sc_replicate_and_commit(op_type, payload, token_timeout=15, ack_timeout=10):
    """
    Leader-side sequential consistency wrapper:
    1. append ordered log entry
    2. replicate entry to followers
    3. wait for quorum ACKs
    4. mark committed
    Returns: (entry, peer_list, quorum_ok)
    """
    entry = consistency_manager.append_log_entry(op_type=op_type, payload=payload)
    peer_list = consistency_manager.other_peers()

    # quorum = leader + majority of followers
    # majority = floor(n/2) + 1
    total_nodes = len(consistency_manager.peers)
    majority = (total_nodes // 2) + 1

    # followers needed, since leader counts as already having an entry
    followers_acks_needed = max(0, majority - 1) # max in case of 1 server with no followers

    consistency_manager.create_pending_ack(entry["seq_no"], len(peer_list))
    consistency_manager.replicate_to_followers(entry)

    quorum_ok = True
    if followers_acks_needed > 0:
        quorum_ok = consistency_manager.wait_for_quorum(
            seq_no=entry["seq_no"],
            quorum_size=followers_acks_needed,
            timeout=ack_timeout,
        )

    if not quorum_ok:
        raise TimeoutError(
            f"Timed out waiting for quorum for seq={entry['seq_no']} op_id={entry['op_id']}"
        )
    
    consistency_manager.mark_committed(entry["seq_no"])
    return entry, peer_list, quorum_ok


@api_view(["POST"])
@permission_classes([AllowAny])
def sc_replicate(request):
    seq_no = request.data.get("seq_no")
    op_id = request.data.get("op_id")
    op_type = request.data.get("op_type")
    payload = request.data.get("payload", {})
    leader_address = request.data.get("leader_address")

    if seq_no is None or not op_id or not op_type or not leader_address:
        return Response({"error": "seq_no, op_id, op_type, leader_address required"}, status=400)

    seq_no = int(seq_no)

    logger.info(
        f"[SC] Follower received replicate seq={seq_no} op_id={op_id} op_type={op_type}"
    )

    # store entry locally so follower knows ordering
    consistency_manager.log[seq_no] = {
        "seq_no": seq_no,
        "op_id": op_id,
        "op_type": op_type,
        "payload": payload,
        "status": "replicated",
        "timestamp": time.time(),
    }

    try:
        requests.post(
            f"{leader_address}/sc/ack/",
            json={
                "seq_no": seq_no,
                "server_id": int(os.environ.get("SERVER_ID", 1)),
            },
            timeout=3,
        )
    except Exception as e:
        logger.warning(f"[SC] Failed to ACK seq={seq_no}: {e}")
        return Response({"error": "failed to ack"}, status=502)

    return Response({"ok": True})

@api_view(["POST"])
@permission_classes([AllowAny])
def sc_ack(request):
    seq_no = request.data.get("seq_no")
    server_id = request.data.get("server_id")

    if seq_no is None or server_id is None:
        return Response({"error": "seq_no and server_id required"}, status=400)

    consistency_manager.receive_ack(int(seq_no), int(server_id))
    return Response({"ok": True})


MAX_RETRY_COUNT = 10

def _retry_pending_deletes(node):
    logger = __import__("logging").getLogger(__name__)
    pending = list(PendingDelete.objects.filter(storage_node=node))
    if not pending:
        return
    logger.info(f"[EC] Retrying {len(pending)} pending delete(s) for {node.name}")
    for p in pending:
        if p.retry_count >= MAX_RETRY_COUNT:
            logger.warning(f"[EC] Giving up on pending delete chunk={p.chunk_id} on {node.name} after {p.retry_count} retries — manual investigation needed")
            p.delete()
            continue
        try:
            resp = requests.delete(
                f"{node.address}/chunk/{p.chunk_id}",
                headers={"X-Internal-Key": INTERNAL_SECRET},
                timeout=5,
            )
            if resp.status_code in (200, 404):
                p.delete()
                logger.info(f"[EC] Cleared pending delete chunk={p.chunk_id} on {node.name} (status {resp.status_code})")
            else:
                p.retry_count += 1
                p.save(update_fields=["retry_count"])
                logger.warning(f"[EC] Pending delete chunk={p.chunk_id} on {node.name} returned {resp.status_code}")
        except Exception as e:
            p.retry_count += 1
            p.save(update_fields=["retry_count"])
            logger.warning(f"[EC] Pending delete retry failed chunk={p.chunk_id} on {node.name}: {e}")


@api_view(["POST"])
@permission_classes([AllowAny])
def node_heartbeat(request):
    name = request.data.get("name")
    address = request.data.get("address")
    if not name or not address:
        return Response({"error": "name and address required"}, status=400)
    node, _ = StorageNode.objects.update_or_create(
        name=name,
        defaults={"address": address, "is_active": True, "last_heartbeat": timezone.now()},
    )
    threading.Thread(target=_retry_pending_deletes, args=(node,), daemon=True).start()
    return Response({"ok": True, "node_id": str(node.id)})


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    Register a new user
    """
    serializer = UserSerializer(data=request.data)
    if serializer.is_valid():
        # Generate unique user_id
        user_id = str(uuid.uuid4())[:15]
        while User.objects.filter(user_id=user_id).exists():
            user_id = str(uuid.uuid4())[:15]

        serializer.validated_data['user_id'] = user_id
        user = serializer.save()

        # Generate JWT tokens
        tokens = get_tokens_for_user(user)

        return Response({
            'user': UserProfileSerializer(user).data,
            'tokens': tokens,
            'message': 'User registered successfully'
        }, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    Login user with email and password
    """
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        try:
            user = User.objects.get(email=email)
            if user.check_password(password):
                # Generate JWT tokens
                tokens = get_tokens_for_user(user)

                return Response({
                    'user': UserProfileSerializer(user).data,
                    'tokens': tokens,
                    'message': 'Login successful'
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'error': 'Invalid credentials'
                }, status=status.HTTP_401_UNAUTHORIZED)
        except User.DoesNotExist:
            return Response({
                'error': 'Invalid credentials'
            }, status=status.HTTP_401_UNAUTHORIZED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()  # Required for router, but filtered in get_queryset()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        """
        Users can only see their own profile
        """
        return User.objects.filter(user_id=self.request.user.user_id)

    def get_serializer_class(self):
        """
        Use different serializers for different actions
        """
        if self.action in ['list', 'retrieve']:
            return UserProfileSerializer
        return UserSerializer

    def perform_create(self, serializer):
        """
        Prevent creation through this endpoint - use registration instead
        """
        raise PermissionDenied("Use /auth/register/ to create new users")

    @action(detail=False, methods=['get'])
    def me(self, request):
        """
        Get current user's profile - same as /auth/profile/
        """
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download_metadata(request, file_id):
    """
    Returns chunk IDs and storage node URLs for a given file.
    """
    try:
        file_obj = File.objects.get(pk=file_id, owner=request.user)
    except File.DoesNotExist:
        return Response({"error": "File not found"}, status=404)

    chunks = file_obj.chunks.order_by("order")
    response_chunks = [
        {
            "chunk_id": chunk.chunk_id,
            #"download_url": f"{chunk.storage_node}/download/chunk/{chunk.chunk_id}/"

            "download_url": f"http://localhost:8000/download/chunk/{chunk.chunk_id}/" #testing
            '''
            curl -X POST http://localhost:8000/upload/ \ -H "Authorization: Bearer <ACCESS_TOKEN>" \ -H "Content-Type: application/json" \ -d '{"filename":"myfile.txt","size":12345,"num_chunks":3}'

            curl -X GET http://localhost:8000/download/<FILE_ID>/ \ -H "Authorization: Bearer <ACCESS_TOKEN>"
            '''
        }
        for chunk in chunks
    ]
    return Response({"file_id": file_obj.pk, "filename": file_obj.filename, "size": file_obj.size, "chunks": response_chunks})

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download_chunk(request, chunk_id):
    try:
        chunk = Chunk.objects.select_related("file").get(chunk_id=chunk_id)
    except Chunk.DoesNotExist:
        return Response({"error": "Chunk not found"}, status=404)

    if chunk.file.owner != request.user:
        return Response({"error": "Forbidden"}, status=403)
    return Response({"chunk_id": str(chunk.chunk_id), "storage_node": chunk.storage_node, "order": chunk.order})

class FileUploadView(APIView):

    # If not leader, forward request to leader and return response
    def post(self, request):
        try:
            forwarded = _forward_to_leader(request, "/files/upload/", method="POST")
            if forwarded is not None:
                return forwarded
        except Exception as e:
            logger.exception("Failed to forward upload to leader")
            return Response(
                {"error": f"Failed to forward upload to leader: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        serializer = FileUploadRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        leader_address = _get_leader_address_if_not_self()
        if leader_address:
            try:
                resp = requests.post(
                    f"{leader_address}/files/upload/",
                    json=request.data,
                    headers={
                        "Authorization": request.headers.get("Authorization", ""),
                        "Content-Type": "application/json",
                    },
                    timeout=60,
                )
                return Response(resp.json(), status=resp.status_code)
            except Exception as e:
                logger.exception("Failed to forward upload to leader")
                return Response({"error": f"Failed to forward upload to leader: {str(e)}"}, status=502)

        serializer = FileUploadRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        user = request.user

        active_nodes = list(get_active_nodes())
        if len(active_nodes) < REPLICATION_FACTOR:
            return Response(
                {"error": f"Need {REPLICATION_FACTOR} active nodes, found {len(active_nodes)}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        chunk_responses = []
        file_record = None

        try:
            entry, peer_list, quorum_ok = _sc_replicate_and_commit(
            op_type="upload_file",
            payload={
                "filename": data["filename"],
                "size": data["size"],
                "chunk_count": len(data["chunks"]),
            },
            ack_timeout=10,
            )   

            with transaction.atomic():
                file_record = File.objects.create(
                    owner=user,
                    filename=data['filename'],
                    size=data['size'],
                )

                node_count = len(active_nodes)
                for i, chunk_data in enumerate(sorted(data['chunks'], key=lambda c: c['order'])):
                    real_chunk_id = str(uuid.uuid4())
                    selected_nodes = [active_nodes[(i + r) % node_count] for r in range(REPLICATION_FACTOR)]

                    chunk_record = Chunk.objects.create(
                        file=file_record,
                        chunk_id=real_chunk_id,
                        order=chunk_data['order'],
                        size=chunk_data['size'],
                        expected_hash=chunk_data.get('hash'),
                    )

                    presigned_urls = []
                    first_public_url = None

                    for node in selected_nodes:
                        try:
                            resp = requests.put(
                                f"{node.address}/chunk",
                                json={"chunk_id": real_chunk_id, "file_id": str(file_record.id)},
                                headers={"Authorization": request.headers.get("Authorization")},
                                timeout=10,
                            )
                            resp.raise_for_status()
                        except requests.exceptions.RequestException as e:
                            raise Exception(f"Storage node {node.name} unreachable: {str(e)}")

                        node_data = resp.json()
                        presigned_urls.append(node_data['presigned_url'])
                        if first_public_url is None:
                            first_public_url = node_data['public_url']
                        ChunkReplica.objects.create(chunk=chunk_record, storage_node=node)

                    chunk_responses.append({
                        "temp_chunk_id": chunk_data['temp_chunk_id'],
                        "chunk_id": real_chunk_id,
                        "order": chunk_data['order'],
                        "presigned_url": presigned_urls[0],
                        "presigned_urls": presigned_urls,
                        "public_url": first_public_url,
                        "replica_nodes": [node.name for node in selected_nodes],
                        "expected_hash": chunk_data.get('hash'),
                    })

                file_record.status = File.STATUS_COMPLETE
                file_record.save(update_fields=["status"])

            response_data = {
                "file_id": file_record.id,
                "filename": file_record.filename,
                "total_chunks": len(chunk_responses),
                "chunks": chunk_responses,
                "sc": {
                    "seq_no": entry["seq_no"],
                    "op_id": entry["op_id"],
                    "quorum_achieved": quorum_ok,
                    "replicas_contacted": len(peer_list),
                },
            }

            response_serializer = FileUploadResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)

            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except TimeoutError as e:
            return Response({"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            logger.exception("Upload failed")
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download_file(request, file_id):

    try:
        file_obj = File.objects.get(pk=file_id, owner=request.user)
    except File.DoesNotExist:
        return Response({"error": "File not found"}, status=status.HTTP_404_NOT_FOUND)

    cutoff = timezone.now() - timedelta(seconds=HEARTBEAT_TIMEOUT)
    chunk_responses = []

    for chunk in file_obj.chunks.prefetch_related('replicas__storage_node').order_by('order'):
        replicas = sorted(
            chunk.replicas.all(),
            key=lambda r: 0 if (r.storage_node and r.storage_node.last_heartbeat and r.storage_node.last_heartbeat >= cutoff) else 1,
        )
        presigned_url = None
        for replica in replicas:
            if not replica.storage_node:
                continue
            try:
                r = requests.get(
                    f"{replica.storage_node.address}/chunk/{chunk.chunk_id}",
                    headers={"Authorization": request.headers.get("Authorization")},
                    timeout=10,
                )
                r.raise_for_status()
                presigned_url = r.json()['presigned_url']
                break
            except Exception:
                continue

        if not presigned_url:
            return Response(
                {"error": f"All replicas unreachable for chunk {chunk.order}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        chunk_responses.append({
            "chunk_id": chunk.chunk_id,
            "order": chunk.order,
            "size": chunk.size,
            "presigned_url": presigned_url,
            "expected_hash": chunk.expected_hash,
        })

    return Response({
        "file_id": str(file_obj.id),
        "filename": file_obj.filename,
        "size": file_obj.size,
        "total_chunks": len(chunk_responses),
        "chunks": chunk_responses,
    }, status=status.HTTP_200_OK)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_files(request):
    files = (
        File.objects.filter(owner=request.user, status=File.STATUS_COMPLETE)
        .prefetch_related("chunks__replicas__storage_node")
        .order_by("-created_at")
    )

    data = []
    for f in files:
        file_chunks = []
        for chunk in f.chunks.all().order_by("order"):
            file_chunks.append({
                "chunk_id": str(chunk.chunk_id),
                "order": chunk.order,
                "size": chunk.size,
                "replica_nodes": [
                    replica.storage_node.name
                    for replica in chunk.replicas.all()
                    if replica.storage_node
                ],
            })

        data.append({
            "file_id": str(f.id),
            "filename": f.filename,
            "size": f.size,
            "created_at": f.created_at.isoformat(),
            "chunks": file_chunks,
        })

    return Response({"files": data}, status=status.HTTP_200_OK)

# ---------------------------------------------------------------------------
# Bully election endpoints
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
def election(request):
    """
    Receive an ELECTION message from a lower-ID peer.
    If we outrank the sender we return {"bully": true} and start our own election in a background thread.
    """
    from .election import election_manager
    sender_id = request.data.get("sender_id")
    if sender_id is None:
        return Response({"error": "sender_id required"}, status=400)
    outranks = election_manager.handle_election(int(sender_id))
    return Response({"bully": outranks})


@api_view(["POST"])
@permission_classes([AllowAny])
def bully(request):
    """
    Receive a BULLY message from a higher-ID peer on a separate channel.
    This signals that a higher node is alive and taking over the election.
    """
    from .election import election_manager
    election_manager.handle_bully()
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([AllowAny])
def leader(request):
    """
    Receive a LEADER message — the sender has won the election.
    """
    from .election import election_manager
    leader_id = request.data.get("leader_id")
    leader_address = request.data.get("leader_address")
    if leader_id is None or not leader_address:
        return Response({"error": "leader_id and leader_address required"}, status=400)
    election_manager.handle_leader(int(leader_id), leader_address)
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def leader_info(request):
    """
    Return who the current leader is.
    Storage nodes and peers call this to discover the leader.
    """
    from .election import election_manager
    if election_manager.leader_id is None:
        return Response({"error": "No leader elected yet"}, status=503)
    return Response({
        "leader_id": election_manager.leader_id,
        "leader_address": election_manager.leader_address,
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def heartbeat_check(request):
    """
    Peers call this to verify this server is alive.
    Also returns this server's ID so callers know who they are talking to.
    """
    return Response({
        "ok": True,
        "server_id": int(os.environ.get("SERVER_ID", 1)),
    })

@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_file(request, file_id):

    # If not leader, forward request to leader and return response
    try:
        forwarded = _forward_to_leader(
            request,
            f"/files/{file_id}/delete/",
            method="DELETE",
        )
        if forwarded is not None:
            return forwarded
    except Exception as e:
        logger.exception("Failed to forward delete to leader")
        return Response(
            {"error": f"Failed to forward delete to leader: {str(e)}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    leader_address = _get_leader_address_if_not_self()
    if leader_address:
        try:
            resp = requests.post(
                f"{leader_address}/files/upload/",
                json=request.data,
                headers={
                    "Authorization": request.headers.get("Authorization", ""),
                    "Content-Type": "application/json",
                },
                timeout=60,
            )
            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.exception("Failed to forward upload to leader")
            return Response({"error": f"Failed to forward upload to leader: {str(e)}"}, status=502)

    try:
        file_obj = File.objects.prefetch_related(
            "chunks__replicas__storage_node"
        ).get(pk=file_id, owner=request.user)
    except File.DoesNotExist:
        return Response({"error": "File not found"}, status=status.HTTP_404_NOT_FOUND)

    filename = file_obj.filename

    try:
        entry, peer_list, quorum_ok = _sc_replicate_and_commit(
        op_type="delete_file",
        payload={"file_id": str(file_id), "filename": filename},
        ack_timeout=10,
    )

        # Collect all (chunk, node) pairs to delete in parallel
        replicas_to_delete = []
        for chunk in file_obj.chunks.all().order_by("order"):
            for replica in chunk.replicas.all():
                replicas_to_delete.append((chunk, replica.storage_node))

        chunk_results = {}
        for chunk in file_obj.chunks.all().order_by("order"):
            chunk_results[str(chunk.chunk_id)] = {"chunk_id": str(chunk.chunk_id), "order": chunk.order, "replicas": []}

        def delete_replica(chunk, node):
            if not node:
                return str(chunk.chunk_id), {"node": None, "status": "skipped", "message": "Replica has no storage node"}
            try:
                resp = requests.delete(
                    f"{node.address}/chunk/{chunk.chunk_id}",
                    headers={"X-Internal-Key": INTERNAL_SECRET},
                    timeout=5,
                )
                if resp.status_code == 200:
                    return str(chunk.chunk_id), {"node": node.name, "status": "deleted", "message": "Chunk deleted from replica"}
                elif resp.status_code == 404:
                    return str(chunk.chunk_id), {"node": node.name, "status": "missing", "message": "Chunk not on replica"}
                else:
                    return str(chunk.chunk_id), {"node": node.name, "status": "error", "message": f"Unexpected status {resp.status_code}"}
            except Exception as e:
                PendingDelete.objects.get_or_create(storage_node=node, chunk_id=str(chunk.chunk_id))
                logger.info(f"[EC] Queued pending delete chunk={chunk.chunk_id} on {node.name}")
                return str(chunk.chunk_id), {"node": node.name, "status": "error", "message": str(e)}

        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = {executor.submit(delete_replica, chunk, node): (chunk, node) for chunk, node in replicas_to_delete}
            for future in as_completed(futures):
                chunk_id, result = future.result()
                chunk_results[chunk_id]["replicas"].append(result)

        deleted_chunks = list(chunk_results.values())

        file_obj.delete()

        return Response({
            "success": True,
            "message": "File deleted",
            "file_id": str(file_id),
            "filename": filename,
            "sc": {
                "seq_no": entry["seq_no"],
                "op_id": entry["op_id"],
                "quorum_achieved": quorum_ok,
                "replicas_contacted": len(peer_list),
            },
            "chunks": deleted_chunks,
        }, status=status.HTTP_200_OK)

    except TimeoutError as e:
        return Response({"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as e:
        logger.exception("File deletion failed")
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


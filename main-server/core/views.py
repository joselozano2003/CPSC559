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
from .consistency import token_ring_manager
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
    
def _sc_begin(op_type, payload, token_timeout=15, ack_timeout=10):
    """
    Begin an SC-wrapped operation:
    1. wait for token
    2. broadcast apply to peers
    3. wait for ACKs (or timeout)
    Returns: (op_id, peer_list, ack_ok)
    """
    op_id = str(uuid.uuid4())
    peer_list = token_ring_manager.other_peers()

    got_token = token_ring_manager.wait_for_token(timeout=token_timeout)
    if not got_token:
        raise TimeoutError("Timed out waiting for SC token")

    logger.info(f"[SC] Server {token_ring_manager.server_id} acquired token for {op_type} op_id={op_id}")

    token_ring_manager.create_pending_ack(op_id, len(peer_list))

    for _, addr in peer_list:
        try:
            requests.post(
                f"{addr}/sc/apply/",
                json={
                    "op_id": op_id,
                    "op_type": op_type,
                    "payload": payload,
                    "sender_address": token_ring_manager.own_address,
                },
                timeout=3,
            )
        except Exception as e:
            logger.warning(f"[SC] Failed to send {op_type} apply to {addr}: {e}")

    ack_ok = token_ring_manager.wait_for_all_acks(op_id, timeout=ack_timeout)
    if not ack_ok:
        logger.warning(f"[SC] Timed out waiting for all ACKs for {op_type} op_id={op_id}")

    return op_id, peer_list, ack_ok


def _sc_pass_token_async(context):
    threading.Thread(
        target=token_ring_manager.pass_token,
        daemon=True,
    ).start()
    logger.info(f"[SC] Server {token_ring_manager.server_id} scheduled token pass after {context}")


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

    def post(self, request):
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
            op_id, peer_list, ack_ok = _sc_begin(
                op_type="upload_file",
                payload={
                    "filename": data["filename"],
                    "size": data["size"],
                    "chunk_count": len(data["chunks"]),
                },
                token_timeout=15,
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
                    "token_acquired": True,
                    "op_id": op_id,
                    "acks_expected": len(peer_list),
                    "acks_received_or_timed_out": ack_ok,
                },
            }

            response_serializer = FileUploadResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)

            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except TimeoutError as e:
            return Response({"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        finally:
            # only pass token if this request actually acquired it
            if token_ring_manager.has_token:
                _sc_pass_token_async(f"upload {data.get('filename', 'unknown')}")

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
    try:
        file_obj = File.objects.prefetch_related(
            "chunks__replicas__storage_node"
        ).get(pk=file_id, owner=request.user)
    except File.DoesNotExist:
        return Response({"error": "File not found"}, status=status.HTTP_404_NOT_FOUND)

    filename = file_obj.filename

    try:
        op_id, peer_list, ack_ok = _sc_begin(
            op_type="delete_file",
            payload={"file_id": str(file_id), "filename": filename},
            token_timeout=15,
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
                "token_acquired": True,
                "op_id": op_id,
                "acks_expected": len(peer_list),
                "acks_received_or_timed_out": ack_ok,
            },
            "chunks": deleted_chunks,
        }, status=status.HTTP_200_OK)

    except TimeoutError as e:
        return Response({"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
    finally:
        if token_ring_manager.has_token:
            _sc_pass_token_async(f"delete {file_id}")

@api_view(["POST"])
@permission_classes([AllowAny])
def receive_token(request):
    epoch = request.data.get("epoch")
    token_ring_manager.receive_token(epoch=int(epoch) if epoch is not None else None)
    return Response({"ok": True})

@api_view(["POST"])
@permission_classes([AllowAny])
def sc_apply(request):
    op_id = request.data.get("op_id")
    op_type = request.data.get("op_type")
    payload = request.data.get("payload", {})

    if not op_id or not op_type:
        return Response({"error": "op_id and op_type required"}, status=400)

    logger = __import__("logging").getLogger(__name__)
    logger.info(
        f"[SC] Server {token_ring_manager.server_id} received apply "
        f"op_id={op_id} op_type={op_type} payload={payload}"
    )

    sender_address = request.data.get("sender_address")
    if sender_address:
        try:
            requests.post(
                f"{sender_address}/sc/ack/",
                json={"op_id": op_id, "server_id": int(os.environ.get('SERVER_ID', 1))},
                timeout=3,
            )
        except Exception as e:
            logger.warning(f"[SC] Failed to send ACK for {op_id}: {e}")

    return Response({"ok": True})

@api_view(["POST"])
@permission_classes([AllowAny])
def sc_ack(request):
    op_id = request.data.get("op_id")
    if not op_id:
        return Response({"error": "op_id required"}, status=400)

    token_ring_manager.receive_ack(op_id)
    return Response({"ok": True})
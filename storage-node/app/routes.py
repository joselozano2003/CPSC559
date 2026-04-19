import threading
import os
import requests as req_lib
from flask import Blueprint, jsonify, request
from .auth import require_jwt, require_jwt_or_internal
from .bucketClient import BucketClient
from .extensions import db
from .models import Chunk

_main_server_url = os.environ.get("MAIN_SERVER_URL", "http://main-server:8000")
NODE_NAME = os.environ.get("NODE_NAME", "storage-node-1")
NODE_ADDRESS = os.environ.get("NODE_ADDRESS", "http://storage-node:6000")
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "10"))


def send_heartbeat():
    try:
        req_lib.post(
            f"{_main_server_url}/nodes/heartbeat/",
            json={"name": NODE_NAME, "address": NODE_ADDRESS},
            timeout=5,
        )
    except Exception as e:
        print(f"[heartbeat] failed: {e}", flush=True)
    finally:
        t = threading.Timer(HEARTBEAT_INTERVAL, send_heartbeat)
        t.daemon = True
        t.start()

bp = Blueprint("chunks", __name__)


@bp.route("/chunk", methods=["PUT"])
@require_jwt
def put_chunk():
    data = request.get_json()
    if not data or "chunk_id" not in data:
        return jsonify({"error": "Missing chunk_id in JSON body"}), 400

    chunk_id = data["chunk_id"]
    file_id = data.get("file_id")

    if not file_id:
        return jsonify({"error": "Missing file_id in JSON body"}), 400

    # Check for duplicate chunk
    existing = Chunk.query.filter_by(chunk_id=chunk_id).first()
    if existing:
        return jsonify({"error": "Chunk already exists"}), 409

    bucket_client = BucketClient()
    object_key = bucket_client.generate_object_key(chunk_id)
    presigned_url = bucket_client.generate_presigned_upload_url(object_key)

    if not presigned_url:
        return jsonify({"error": "Failed to generate upload URL"}), 500

    public_url = bucket_client.get_public_url(object_key)

    chunk = Chunk(
        chunk_id=chunk_id,
        minio_object_key=object_key,
        file_id=file_id,
        confirmed=False,
    )
    db.session.add(chunk)
    db.session.commit()

    upload_url = f"{NODE_ADDRESS}/chunk/{chunk_id}/data"

    return jsonify({
        "chunk_id": chunk_id,
        "presigned_url": upload_url,
        "public_url": public_url,
        "success": True,
    }), 201


@bp.route("/chunk/<chunk_id>/data", methods=["PUT"])
def upload_chunk_data(chunk_id):
    chunk = Chunk.query.filter_by(chunk_id=chunk_id).first()
    if not chunk:
        return jsonify({"error": "Chunk not found"}), 404

    data = request.get_data()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    bucket_client = BucketClient()
    ok = bucket_client.upload_bytes(chunk.minio_object_key, data)
    if not ok:
        return jsonify({"error": "Failed to upload to storage"}), 500

    return '', 200

@bp.route("/chunk/<chunk_id>", methods=["GET"])
@require_jwt
def get_chunk(chunk_id):
    chunk = Chunk.query.filter_by(chunk_id=chunk_id).first()
    if not chunk:
        return jsonify({"error": "Chunk not found"}), 404

    bucket_client = BucketClient()
    presigned_url = bucket_client.generate_presigned_download_url(chunk.minio_object_key)

    if not presigned_url:
        return jsonify({"error": "Failed to generate download URL"}), 500

    return jsonify({
        "chunk_id": chunk_id,
        "presigned_url": presigned_url,
        "success": True
    }), 200

@bp.route("/set-leader", methods=["POST"])
def set_leader():
    global _main_server_url
    data = request.get_json()
    address = data.get("leader_address") if data else None
    if not address:
        return jsonify({"error": "leader_address required"}), 400
    _main_server_url = address
    print(f"[set-leader] Updated main server URL to {_main_server_url}", flush=True)
    return jsonify({"ok": True}), 200


@bp.route("/chunk/<chunk_id>/confirm", methods=["PATCH"])
@require_jwt
def confirm_chunk(chunk_id):
    data = request.get_json()
    size_bytes = data.get("size_bytes") if data else None

    chunk = Chunk.query.filter_by(chunk_id=chunk_id).first()
    if not chunk:
        return jsonify({"error": "Chunk not found"}), 404

    chunk.confirmed = True
    if size_bytes is not None:
        chunk.size_bytes = size_bytes

    db.session.commit()

    return jsonify({"chunk_id": chunk_id, "confirmed": True, "success": True}), 200

@bp.route("/chunk/<chunk_id>", methods=["DELETE"])
@require_jwt_or_internal
def delete_chunk(chunk_id):
    chunk = Chunk.query.filter_by(chunk_id=chunk_id).first()
    if not chunk:
        return jsonify({"error": "Chunk not found"}), 404

    bucket_client = BucketClient()
    deleted = bucket_client.delete_file(chunk.minio_object_key)

    if not deleted:
        return jsonify({"error": "Failed to delete chunk from bucket"}), 500

    db.session.delete(chunk)
    db.session.commit()

    return jsonify({
        "chunk_id": chunk_id,
        "deleted": True,
        "success": True
    }), 200
from flask import Blueprint, jsonify, request
from .auth import require_jwt
from .bucketClient import BucketClient
from .extensions import db
from .models import Chunk

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
    file_key = bucket_client.generate_unique_filename(chunk_id)
    presigned_url = bucket_client.generate_presigned_url(file_key)

    if not presigned_url:
        return jsonify({"error": "Failed to generate upload URL"}), 500

    public_url = bucket_client.get_public_url(file_key)

    chunk = Chunk(
        chunk_id=chunk_id,
        minio_object_key=file_key,
        file_id=file_id,
        confirmed=False,
    )
    db.session.add(chunk)
    db.session.commit()

    return jsonify({
        "chunk_id": chunk_id,
        "presigned_url": presigned_url,
        "public_url": public_url,
        "success": True,
    }), 201


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
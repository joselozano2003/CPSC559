from flask import Blueprint, jsonify, abort, request
from .auth import require_jwt
from .bucketClient import BucketClient

bp = Blueprint("chunks", __name__)

@bp.route("/chunk", methods=["PUT"])
@require_jwt
def put_chunk():
    data = request.get_json()
    if not data or "chunk_id" not in data:
        return jsonify({"error": "Missing chunk_id in JSON body"}), 400
    chunk_id = data["chunk_id"]

    bucket_client = BucketClient()
    file_key = bucket_client.generate_unique_filename(chunk_id)
    presigned_url = bucket_client.generate_presigned_url(file_key)

    if not presigned_url:
        return jsonify({
            'error': 'Failed to generate upload URL'
        }), 500
    
    public_url = bucket_client.get_public_url(file_key)
    
    return jsonify({"chunk_id": chunk_id, "public_url": public_url, "success": True}), 201


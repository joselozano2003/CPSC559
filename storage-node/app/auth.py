import os
import requests
from functools import wraps
from flask import request, jsonify

INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "cps559-internal-key")


def require_jwt_or_internal(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        internal_key = request.headers.get("X-Internal-Key", "")
        if internal_key and internal_key == INTERNAL_SECRET:
            return f(*args, **kwargs)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401

        token = auth_header.split(" ", 1)[1]
        from .routes import _main_server_url
        verify_endpoint = f"{_main_server_url}/api/token/verify/"
        try:
            response = requests.post(verify_endpoint, json={"token": token}, timeout=5, headers={"ngrok-skip-browser-warning": "true"})
            if response.status_code == 200:
                return f(*args, **kwargs)
            else:
                return jsonify({"error": "Unauthorized", "message": "Token verification failed", "details": response.json()}), 401
        except requests.exceptions.RequestException as e:
            print(f"CONNECTION ERROR: Could not reach {verify_endpoint}: {e}", flush=True)
            return jsonify({"error": "Authentication service unreachable"}), 500

    return decorated


def require_jwt(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. Extract Token from Header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401

        token = auth_header.split(" ", 1)[1]

        # Read the current leader URL at request time so /set-leader updates take effect.
        from .routes import _main_server_url
        verify_endpoint = f"{_main_server_url}/api/token/verify/"

        # 2. Forward the token to your Django 'main-server'
        try:
            response = requests.post(
                verify_endpoint,
                json={"token": token},
                timeout=5  # Prevents Flask from hanging if Django is down
            )
            
            # 3. Handle the Response
            if response.status_code == 200:
                # Token is valid! Now we call your actual route (e.g., put_chunk)
                return f(*args, **kwargs)
            else:
                # Token is expired or tampered with
                return jsonify({
                    "error": "Unauthorized", 
                    "message": "Token verification failed",
                    "details": response.json()
                }), 401

        except requests.exceptions.RequestException as e:
            # This triggers if the 'main-server' container isn't reachable
            print(f"CONNECTION ERROR: Could not reach {verify_endpoint}: {e}", flush=True)
            return jsonify({"error": "Authentication service unreachable"}), 500

    return decorated
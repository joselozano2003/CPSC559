import os
import requests
from functools import wraps
from flask import request, jsonify

# Get the URL from your docker-compose environment variable
# Defaulting to the name you provided: http://main-server:8000
MAIN_SERVER_URL = os.environ.get("MAIN_SERVER_URL", "http://main-server:8000")
VERIFY_ENDPOINT = f"{MAIN_SERVER_URL}/api/token/verify/"

def require_jwt(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. Extract Token from Header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        
        token = auth_header.split(" ", 1)[1]

        # 2. Forward the token to your Django 'main-server'
        try:
            response = requests.post(
                VERIFY_ENDPOINT,
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
            print(f"CONNECTION ERROR: Could not reach {VERIFY_ENDPOINT}: {e}", flush=True)
            return jsonify({"error": "Authentication service unreachable"}), 500

    return decorated
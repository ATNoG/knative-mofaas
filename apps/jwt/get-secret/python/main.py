import os
import jwt
import datetime
import requests
from flask import Flask, request, jsonify

# Ensure required environment variables are set
DIRECTUS_URL = os.getenv("DIRECTUS_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN")

EXPIRATION = 1  # 1 hour

app = Flask(__name__)

def decode_jwt(token):
    """Decode and validate JWT token."""
    try:
        decoded_token = jwt.decode(token, SECRET_KEY, options={"verify_signature": False})  # algorithms=["HS256"]
        
        # Retrieve the issued-at timestamp
        issued_at = decoded_token.get("iat")
        if not issued_at:
            # Missing issued-at claim
            return None
        
        # Convert issued_at (an integer) to a datetime object
        issued_at = datetime.datetime.fromtimestamp(issued_at, datetime.timezone.utc)
        
        # Check if the token is older than 1 hour
        if datetime.datetime.now(datetime.timezone.utc) > issued_at + datetime.timedelta(hours=1):
            return None  # Token expired
        
        return decoded_token
    except jwt.exceptions.JWTError:
        return None

def get_secret():
    """Retrieve the first secret from the database if authorized."""
    url = f"{DIRECTUS_URL}/items/secrets"
    headers = {"Authorization": f"Bearer {DIRECTUS_TOKEN}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = response.json().get("data", [])
        return data[0]["value"] if data else None
    return None

@app.route("/", methods=["GET"])
def secret():
    """Protected endpoint that returns a secret if the user has access."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid token"}), 401
    
    token = auth_header.split(" ")[1]
    decoded_token = decode_jwt(token)
    if not decoded_token:
        return jsonify({"error": "Invalid token"}), 401
    
    if not decoded_token.get("has_access"):
        return jsonify({"error": "Access denied"}), 403
    
    secret_data = get_secret()
    if not secret_data:
        return jsonify({"error": "No secret found"}), 404
    
    return jsonify(secret_data)

if __name__ == "__main__":
    if not DIRECTUS_URL or not SECRET_KEY or not DIRECTUS_TOKEN:
        raise ValueError("Missing required environment variables: DIRECTUS_URL, SECRET_KEY, DIRECTUS_TOKEN")

    app.run(host='0.0.0.0', port=8080)

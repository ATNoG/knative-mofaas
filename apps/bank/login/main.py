import os
import time
import jwt
import requests
import bcrypt
from flask import Flask, request, jsonify, Response


# Ensure required environment variables are set
DIRECTUS_URL = os.getenv("DIRECTUS_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN")

EXPIRATION = 3600  # 1 hour

app = Flask(__name__)

def verify_credentials(username, password):
    """Verify user credentials by querying Directus."""
    url = f"{DIRECTUS_URL}/items/users?filter[username][_eq]={username}"
    headers = {"Authorization": f"Bearer {DIRECTUS_TOKEN}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        user_data = response.json().get("data", [])
        if user_data:
            stored_hash = user_data[0]["password"]
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')), user_data[0]["has_access"]
    return False, False

# def check_access(username):
#     """Check if the user has access by querying Directus."""
#     url = f"{DIRECTUS_URL}/items/users?filter[username][_eq]={username}"
#     headers = {"Authorization": f"Bearer {DIRECTUS_TOKEN}"}
#     response = requests.get(url, headers=headers)
    
#     if response.status_code == 200:
#         data = response.json().get("data", [])
#         return data[0]["has_access"] if data else False
#     return False

def generate_jwt(username, has_access):
    """Generate a JWT token for authenticated users."""
    payload = {
        "sub": username,
        "has_access": has_access,
        "iat": int(time.time()),
        "exp": int(time.time()) + EXPIRATION
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

@app.route("/", methods=["POST"])
def login():
    """Login endpoint."""
    data = request.json
    username = data.get("username")
    password = data.get("password")
    
    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400
    
    correct_password, has_access = verify_credentials(username, password)
    if not correct_password:
        return jsonify({"error": "Invalid username or password"}), 401
    
    jwt_token = generate_jwt(username, has_access)
    return Response(status=200, headers={'Authorization': f'Bearer {jwt_token}'})

if __name__ == "__main__":
    if not DIRECTUS_URL or not SECRET_KEY or not DIRECTUS_TOKEN:
        raise ValueError("Missing required environment variables: DIRECTUS_URL, SECRET_KEY, DIRECTUS_TOKEN")

    app.run(host='0.0.0.0', port=8080)

import os
import jwt
import datetime
import requests
import logging
from flask import Flask, request, jsonify

# Ensure required environment variables are set
SECRET_KEY = os.getenv("SECRET_KEY")
K_SINK = os.getenv("K_SINK")

EXPIRATION = 1  # 1 hour
HEADERS_REMOVE = ("Ce-Id", "Ce-Specversion", "Ce-Type", "Ce-Source", "Content-Type", "Host")

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
    
def forward_to_broker(req, proceed, headers):
    headers = {
        "Ce-Id": headers.get("Ce-Id"),
        "Ce-Specversion": "1.0",
        "Ce-Type": "authorization",
        "Ce-Source": "authorization",
        "Content-Type": "application/json",
        "Ce-dv": str(proceed),          # dv = do verification
        **{k: v for k, v in headers.items() if k not in HEADERS_REMOVE}
    }
    requests.post(K_SINK, json=req, headers=headers)

@app.route("/", methods=["POST"])
def authorization():
    """Protected endpoint that returns a secret if the user has access."""
    proceed = True
    message = "Forwarded"
    code = 200
    
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        proceed = False
        message = "Missing or invalid token"
        code = 401
    
    token = auth_header.split(" ")[1]
    decoded_token = decode_jwt(token)
    if code == 200 and not decoded_token:
        proceed = False
        message = "Invalid token"
        code = 401
    
    if code == 200 and decoded_token and not decoded_token.get("has_access"):
        proceed = False
        message = "Access denied"
        code = 403

    forward_to_broker({"client": decoded_token.get("sub") if decoded_token else None, **request.json, "message": message}, proceed, request.headers)

    return jsonify({"message": message}), code

if __name__ == "__main__":
    if not SECRET_KEY:
        raise ValueError("Missing required environment variables: SECRET_KEY")
    if not K_SINK:
        logging.warning("Missing K_SINK variable")

    app.run(host='0.0.0.0', port=8080)

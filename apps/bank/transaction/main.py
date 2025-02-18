import os
import logging
import requests
from flask import Flask, request, jsonify

# Configuration
DIRECTUS_URL = os.getenv("DIRECTUS_URL")
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN")
K_SINK = os.getenv("K_SINK")

HEADERS_REMOVE = ("Ce-Id", "Ce-Specversion", "Ce-Type", "Ce-Source", "Content-Type", "Host")

app = Flask(__name__)

def forward_to_broker(data, headers):
    headers = {
        "Ce-Id": headers.get("Ce-Id"),
        "Ce-Specversion": "1.0",
        "Ce-Type": "transaction-info",
        "Ce-Source": "transaction",
        "Content-Type": "application/json",
        **{k: v for k, v in headers.items() if k not in HEADERS_REMOVE}
    }
    requests.post(K_SINK, json=data, headers=headers)

@app.route("/", methods=["POST"])
def create_transaction():
    data = request.get_json()
    message = "Transaction successful"
    code = 200
    
    # Create the transaction.
    url = f"{DIRECTUS_URL}/items/transactions"
    headers = {
        "Authorization": f"Bearer {DIRECTUS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"from": data.get("from"), "to": data.get("to"), "amount": float(data.get("amount"))}
    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        code = 400
        message = "Transaction failed"

    forward_to_broker({**data, "message": message, "success": code == 200, "details": response.json()}, request.headers)

    return jsonify({"message": message}), code

if __name__ == "__main__":
    if not DIRECTUS_URL or not DIRECTUS_TOKEN:
        raise ValueError("Missing required environment variables: DIRECTUS_URL, DIRECTUS_TOKEN")
    if not K_SINK:
        logging.warning("Missing K_SINK variable")
    app.run(host='0.0.0.0', port=8080)

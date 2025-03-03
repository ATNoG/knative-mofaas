import uuid
import requests, os, logging
from flask import Flask, request, jsonify

logging.basicConfig(
    format="%(created)f - %(levelname)s - %(message)s",
    level=logging.DEBUG
)

app = Flask(__name__)

K_SINK = os.getenv("K_SINK")
HEADERS_REMOVE = ("Ce-Id", "Ce-Specversion", "Ce-Type", "Ce-Source", "Content-Type", "Host")

@app.route("/", methods=["POST"])
def forward_to_broker():
    event = request.get_json()
    original_headers = request.headers
    headers = {
        "Ce-Id": original_headers.get("Ce-Id"),
        "Ce-Specversion": "1.0",
        "Ce-Type": "http.request.received",
        "Ce-Source": "http-event-source",
        "Content-Type": "application/json",
        # "Authorization": request.headers.get("Authorization"),
        **{k: v for k, v in original_headers.items() if k not in HEADERS_REMOVE}
    }
    response = requests.post(original_headers["X-K-Sink"] if original_headers.get("X-K-Sink") else K_SINK, json=event, headers=headers)
    return {"forwarded-response": response.json()}, response.status_code

if __name__ == "__main__":
    if not K_SINK:
        logging.warning("Missing required environment variables: K_SINK")
    app.run(host="0.0.0.0", port=8080)

import logging
import json
from flask import Flask, request

logging.basicConfig(
    format="%(created)f - %(levelname)s - %(message)s",
    level=logging.DEBUG
)

DELIMITER = "---------------"
app = Flask(__name__)

@app.route("/", methods=["POST"])
def main():
    logging.info(f"Received response:\n{DELIMITER}\nHEADERS\n{json.dumps(dict(request.headers))}\n{DELIMITER}\nBODY\n{json.dumps(request.json)}\n{DELIMITER}\n\n\n")
    return {"message": "success"}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

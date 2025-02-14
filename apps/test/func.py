from flask import Flask, request, make_response
import uuid
import os
import requests
import logging
import datetime

logging.basicConfig(
    format="{asctime} - {levelname} - {message}",
    style="{",
    datefmt="%Y-%m-%d %H:%M",
    level=logging.DEBUG
)

app = Flask(__name__)

k_sink = os.getenv("K_SINK")
directus_url = os.getenv("DIRECTUS_URL")  # Directus base URL (e.g., http://directus-service:8055)

@app.route('/', methods=['POST'])
def hello_world():    
    app.logger.info(f"Received number {request.json['number']}")
    recv_number = request.json["number"]
    sent_number = recv_number + 1
    response = make_response({
        "number": sent_number
    })
    response.headers["Ce-Id"] = str(uuid.uuid4())
    response.headers["Ce-specversion"] = "1.0"
    response.headers["Ce-Source"] = "appender"
    response.headers["Ce-Type"] = "json.document"
    
    # Send data to Directus (create new request record)
    new_request_data = {
        "recv_number": recv_number,
        "sent_number": sent_number,
    }
    
    # Insert the new record into the Directus database (POST to /items/{collection})
    response_directus = requests.post(
        f"{directus_url}/items/requests",  # Directus item API endpoint for the "requests" collection
        json=new_request_data,
        headers={"Authorization": f"Bearer {os.getenv('DIRECTUS_API_TOKEN')}"}
    )

    if response_directus.status_code == 201:
        app.logger.info(f"Successfully created request in Directus: {new_request_data}")
    else:
        app.logger.error(f"Failed to create request in Directus: {response_directus.text}")

    # Example of calling another service
    r = requests.get("http://detectportal.firefox.com/success.txt")
    app.logger.info(r.text)
    
    app.logger.info(f"Sending information to {k_sink}")
    return response


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)

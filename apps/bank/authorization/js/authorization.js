const http = require('http');
const express = require('express');
const bodyParser = require('body-parser');
const jwt = require('jsonwebtoken');
const request = require('sync-request'); // Blocking HTTP requests

const SECRET_KEY = process.env.SECRET_KEY;
const K_SINK = process.env.K_SINK;
const HEADERS_REMOVE = ["ce-id", "ce-specversion", "ce-type", "ce-source", "content-type", "host", "x-k-sink"];

if (!SECRET_KEY) {
  console.error("Missing required environment variable: SECRET_KEY");
  process.exit(1);
}

const app = express();
app.use(bodyParser.json());

app.post('/', (req, res) => {
  const authHeader = req.headers['authorization'];
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return forwardToBroker(req, res, null, "Missing or invalid token", 401);
  }

  const token = authHeader.substring(7);
  try {
    const decoded = jwt.verify(token, SECRET_KEY, { algorithms: ['HS256'] });
    const hasAccess = decoded.has_access || false;
    const client = decoded.sub || "unknown";

    if (!hasAccess) {
      return forwardToBroker(req, res, client, "Access denied", 403);
    }
    forwardToBroker(req, res, client, "Forwarded", 200);
  } catch (err) {
    return forwardToBroker(req, res, null, "Invalid token", 401);
  }
});

function forwardToBroker(req, res, client, message, statusCode) {
  let payload = req.body || {};
  payload.client = client;
  payload.message = message;

  let headers = {};

  // Normalize HEADERS_REMOVE to lowercase for case-insensitive comparison
  const headersToRemove = new Set(HEADERS_REMOVE.map(h => h.toLowerCase()));

  // First, copy existing headers (excluding the ones in HEADERS_REMOVE)
  for (let key in req.headers) {
    if (!headersToRemove.has(key.toLowerCase())) {
      headers[key] = req.headers[key];
    }
  }

  // Then, add or override with the required headers
  Object.assign(headers, {
    "Ce-Specversion": "1.0",
    "Ce-Type": "authorization",
    "Ce-Source": "authorization",
    "Content-Type": "application/json",
    "Ce-dv": String(statusCode === 200)
  });

  if (req.headers['ce-id']) {
    headers['Ce-Id'] = req.headers['ce-id'];
  }

  let targetSink = req.headers['x-k-sink'] || K_SINK;
  if (targetSink) {
    try {
      let bodyString = JSON.stringify(payload);
      headers['Content-Length'] = Buffer.byteLength(bodyString, 'utf8');

      console.log("Forwarding request to broker:", {
        url: targetSink,
        headers,
        body: bodyString
      });

      let response = request('POST', targetSink, {
        headers: headers,
        body: bodyString
      });

      console.log(`Successfully forwarded event to: ${targetSink}, Response: ${response.getBody('utf8')}`);
    } catch (error) {
      console.error(`Failed to forward event to: ${targetSink}, Error: ${error.message}`);
    }
  } else {
    console.warn("Warning: No valid sink configured. Event not forwarded.");
  }

  // If the request was not forwarded, send the response to the client
  if (!res.headersSent) {
    const responseBody = JSON.stringify({ message: message });
    res.writeHead(statusCode, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(responseBody) });
    res.end(responseBody);
  }
}

const server = http.createServer(app);
server.listen(8080, () => {
  console.log("Server started on port 8080");
});

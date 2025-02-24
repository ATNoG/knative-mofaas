const express = require('express');
const axios = require('axios');

const app = express();
app.use(express.json());

// Required environment variables
const DIRECTUS_URL = process.env.DIRECTUS_URL;
const DIRECTUS_TOKEN = process.env.DIRECTUS_TOKEN;
const K_SINK = process.env.K_SINK;
const OTP_SECRET = process.env.OTP_SECRET;
const MAX_AMOUNT = process.env.MAX_AMOUNT ? parseFloat(process.env.MAX_AMOUNT) : 0;

const HEADERS_REMOVE = [
  'ce-id',
  'ce-specversion',
  'ce-type',
  'ce-source',
  'content-type',
  'host',
  'x-k-sink'
];

if (!DIRECTUS_URL || !DIRECTUS_TOKEN || !OTP_SECRET || MAX_AMOUNT === 0) {
  console.error('Missing required environment variables: DIRECTUS_URL, DIRECTUS_TOKEN, MAX_AMOUNT, OTP_SECRET');
  process.exit(1);
}
if (!K_SINK) {
  console.warn('Warning: K_SINK is not set. Events will not be forwarded.');
}

/**
 * Retrieves a user ID from Directus given a username.
 */
async function getUserId(username, req_id) {
  if (!username) return null;
  const url = `${DIRECTUS_URL}/items/users?filter[username][_eq]=${username}`;
  try {
    const res = await axios.get(url, {
      headers: {
        'Authorization': `Bearer ${DIRECTUS_TOKEN}`,
        'Ce-Id': req_id
      }
    });
    const data = res.data;
    if (data && data.data && data.data.length > 0) {
      return data.data[0].id;
    }
    return null;
  } catch (error) {
    return null;
  }
}

/**
 * Forwards the transaction payload to the external broker and responds to the original requester.
 * Outgoing headers are constructed to prevent overrides by incoming headers.
 */
async function forwardToBroker(req, res, payload, proceed, message, statusCode) {
  // Copy allowed incoming headers (skip ones in HEADERS_REMOVE)
  const headers = {};
  for (const key in req.headers) {
    if (!HEADERS_REMOVE.includes(key)) {
      headers[key] = req.headers[key];
    }
  }

  // Set additional headers
  headers['Ce-Id'] = req.headers['ce-id'] || '';
  headers['Ce-Specversion'] = '1.0';
  headers['Ce-Type'] = 'transaction';
  headers['Ce-Source'] = 'verify-transaction';
  headers['Ce-Dt'] = proceed ? 'true' : 'false';
  headers['Content-Type'] = 'application/json';

  // Determine target sink from header or environment variable
  const targetSink = req.headers['x-k-sink'] || K_SINK; 

  if (targetSink) {
    try {
      let bodyString = JSON.stringify(payload);
      headers['Content-Length'] = Buffer.byteLength(bodyString, 'utf8');
      await axios.post(targetSink, payload, { headers });
      console.log('Successfully forwarded event');
    } catch (error) {
      console.error('Failed to forward event:', error.message);
    }
  } else {
    console.warn('Warning: No valid sink configured. Event not forwarded.');
  }

  // If the request was not forwarded, send the response to the client
  if (!res.headersSent) {
    const responseBody = JSON.stringify({ message: message });
    res.writeHead(statusCode, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(responseBody) });
    res.end(responseBody);
  }
}

app.post('/', async (req, res) => {
  // Initialize processing state
  let proceed = true;
  let message = 'Forwarded';
  let statusCode = 200;
  
  const body = req.body;
  if (!body) {
    proceed = false;
    message = 'Invalid JSON';
    statusCode = 400;
    await forwardToBroker(req, res, {}, proceed, message, statusCode);
    return;
  }
  
  // Parse and validate "amount"
  let amount = 0;
  if (body.hasOwnProperty('amount')) {
    if (typeof body.amount === 'number' || !isNaN(body.amount)) {
      amount = parseFloat(body.amount);
    } else {
      amount = parseFloat(String(body.amount).trim());
      if (isNaN(amount)) {
        proceed = false;
        message = 'Invalid amount provided';
        statusCode = 400;
      }
    }
  } else {
    proceed = false;
    message = 'Invalid amount provided';
    statusCode = 400;
  }
  
  const clientUsername = body.client || null;
  const destinationClient = body.destination_client || null;
  // Ensure OTP values are compared as strings
  const otp = body.otp !== undefined ? String(body.otp) : null;
  const otpSecret = String(OTP_SECRET);
  
  // Check OTP if amount exceeds MAX_AMOUNT
  if (statusCode === 200 && amount > MAX_AMOUNT && (!otp || otp !== otpSecret)) {
    proceed = false;
    message = 'OTP required or incorrect';
    statusCode = 403;
  }
  
  const req_id = req.headers['ce-id'] || '';
  
  // Retrieve user IDs sequentially:
  const fromId = await getUserId(clientUsername, req_id);
  const toId = await getUserId(destinationClient, req_id);
  
  if (statusCode === 200 && (fromId === null || toId === null)) {
    proceed = false;
    message = 'Invalid client usernames';
    statusCode = 400;
  }
  
  // Build payload by copying original body and adding extra fields
  const payload = { ...body, message, from: fromId, to: toId };
  
  await forwardToBroker(req, res, payload, proceed, message, statusCode);
});

const port = 8080;
app.listen(port, () => {
  console.log(`Server started on port ${port}`);
});

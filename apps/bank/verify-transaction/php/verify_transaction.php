<?php

use Swoole\Http\Server;
use Swoole\Http\Request;
use Swoole\Http\Response;
use GuzzleHttp\Client;

require 'vendor/autoload.php';

// Required environment variables
$DIRECTUS_URL = getenv('DIRECTUS_URL');
$DIRECTUS_TOKEN = getenv('DIRECTUS_TOKEN');
$K_SINK = getenv('K_SINK');
$OTP_SECRET = getenv('OTP_SECRET');
$MAX_AMOUNT = getenv('MAX_AMOUNT') ? (float)getenv('MAX_AMOUNT') : 0;

$HEADERS_REMOVE = [
    'ce-id', 'ce-specversion', 'ce-type', 'ce-source', 'content-type', 'host', 'x-k-sink'
];

if (!$DIRECTUS_URL || !$DIRECTUS_TOKEN || !$OTP_SECRET || $MAX_AMOUNT == 0) {
    die("Missing required environment variables: DIRECTUS_URL, DIRECTUS_TOKEN, MAX_AMOUNT, OTP_SECRET\n");
}
if (!$K_SINK) {
    echo "Warning: K_SINK is not set. Events will not be forwarded.\n";
}

$server = new Server("0.0.0.0", 8080);
$client = new Client();

$server->on("request", function (Request $request, Response $response) use ($client, $DIRECTUS_URL, $DIRECTUS_TOKEN, $K_SINK, $OTP_SECRET, $MAX_AMOUNT, $HEADERS_REMOVE) {
    // Only accept POST requests
    if ($request->server['request_method'] !== 'POST') {
        $response->status(405);
        $response->end(json_encode(["message" => "Method Not Allowed"]));
        return;
    }
    
    $body = json_decode($request->rawContent(), true);

    // Initialize variables to hold the processing state
    $proceed = true;
    $message = "Forwarded";
    $statusCode = 200;

    // If the JSON payload is invalid, update our state
    if (!$body) {
        $proceed = false;
        $message = "Invalid JSON";
        $statusCode = 400;
        $payload = [];
        forwardToBroker($request, $response, $payload, $proceed, $message, $statusCode, $K_SINK, $HEADERS_REMOVE, $client);
        return;
    }

    // Parse and validate "amount"
    $amount = 0;
    if (isset($body['amount'])) {
        if (is_numeric($body['amount'])) {
            $amount = (float)$body['amount'];
        } else {
            // Try to trim and parse; if still not valid, mark as error
            $amount = (float)trim($body['amount']);
            if (!is_numeric($amount)) {
                $proceed = false;
                $message = "Invalid amount provided";
                $statusCode = 400;
            }
        }
    } else {
        $proceed = false;
        $message = "Invalid amount provided";
        $statusCode = 400;
    }

    // Retrieve client usernames and OTP from the payload
    $clientUsername = $body['client'] ?? null;
    $destinationClient = $body['destination_client'] ?? null;
    // Cast the OTP value from the body to string for proper comparison
    $otp = isset($body['otp']) ? (string)$body['otp'] : null;
    // Cast the OTP_SECRET to string as well (though getenv() returns a string by default)
    $OTP_SECRET = (string)$OTP_SECRET;

    // Check OTP if the amount exceeds MAX_AMOUNT
    if ($statusCode === 200 && $amount > $MAX_AMOUNT && (empty($otp) || $otp !== $OTP_SECRET)) {
        $proceed = false;
        $message = "OTP required or incorrect";
        $statusCode = 403;
    }

    // Retrieve the request ID from the headers
    $req_id = $request->header['ce-id'] ?? '';

    // Synchronously retrieve user IDs for both the client and the destination client
    $fromId = getUserId($clientUsername, $req_id, $DIRECTUS_URL, $DIRECTUS_TOKEN, $client);
    $toId = getUserId($destinationClient, $req_id, $DIRECTUS_URL, $DIRECTUS_TOKEN, $client);

    if ($statusCode === 200 && ($fromId === null || $toId === null)) {
        $proceed = false;
        $message = "Invalid client usernames";
        $statusCode = 400;
    }

    // Build the payload by copying the original body and adding extra fields
    $payload = $body;
    $payload['message'] = $message;
    $payload['from'] = $fromId;
    $payload['to'] = $toId;

    // Forward to the broker and send the final response
    forwardToBroker($request, $response, $payload, $proceed, $message, $statusCode, $K_SINK, $HEADERS_REMOVE, $client);
});

function getUserId($username, $req_id, $DIRECTUS_URL, $DIRECTUS_TOKEN, $client) {
    if (!$username) return null;
    
    $url = "$DIRECTUS_URL/items/users?filter[username][_eq]=$username";
    try {
        $res = $client->request('GET', $url, [
            'headers' => [
                'Authorization' => "Bearer $DIRECTUS_TOKEN",
                'Ce-Id' => $req_id
            ]
        ]);
        $data = json_decode($res->getBody()->getContents(), true);
        return $data['data'][0]['id'] ?? null;
    } catch (Exception $e) {
        return null;
    }
}

function forwardToBroker($request, $response, $payload, $proceed, $message, $statusCode, $K_SINK, $HEADERS_REMOVE, $client) {
    $headers = [];
    // Copy allowed incoming headers
    foreach ($request->header as $key => $value) {
        if (!in_array(strtolower($key), $HEADERS_REMOVE)) {
            $headers[$key] = $value;
        }
    }
    
    // Set additional headers explicitly
    $headers['Ce-Id'] = $request->header['ce-id'] ?? '';
    $headers['Ce-Specversion'] = "1.0";
    $headers['Ce-Type'] = "transaction";
    $headers['Ce-Source'] = "verify-transaction";
    $headers['Ce-Dt'] = $proceed ? 'true' : 'false';
    $headers['Content-Type'] = "application/json";

    // Determine target sink from header or environment variable
    $targetSink = $request->header['x-k-sink'] ?? $K_SINK;

    if ($targetSink) {
        try {
            $client->request('POST', $targetSink, [
                'headers' => $headers,
                'json' => $payload
            ]);
            echo "Successfully forwarded event\n";
        } catch (Exception $e) {
            echo "Failed to forward event: " . $e->getMessage() . "\n";
        }
    } else {
        echo "Warning: No valid sink configured. Event not forwarded.\n";
    }
    
    // Respond to the original requester
    $response->status($statusCode);
    $response->header("Content-Type", "application/json");
    $response->end(json_encode(["message" => $message]));
}

$server->start();
?>

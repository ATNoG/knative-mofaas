<?php
use Swoole\Http\Server;
use Swoole\Http\Request;
use Swoole\Http\Response;
use Firebase\JWT\JWT;
use Firebase\JWT\Key;

require 'vendor/autoload.php';

// Define constant for headers that should not be forwarded.
const HEADERS_REMOVE = ["Ce-Id", "Ce-Specversion", "Ce-Type", "Ce-Source", "Content-Type", "Host", "X-K-Sink"];

$secretKey = getenv('SECRET_KEY');
$kSink = getenv('K_SINK');

if (!$secretKey) {
    echo "Missing required environment variable: SECRET_KEY\n";
    exit(1);
}

$server = new Server("0.0.0.0", 8080);

$server->set([
    'http_compression' => false,
]);

$server->on("request", function (Request $request, Response $response) use ($secretKey, $kSink) {
    // Retrieve the Authorization header
    $authHeader = $request->header['authorization'] ?? '';
    if (!$authHeader || stripos($authHeader, 'Bearer ') !== 0) {
        forwardToBroker($request, $response, null, "Missing or invalid token", 401);
        return;
    }
    $token = substr($authHeader, 7);

    try {
        $decoded = JWT::decode($token, new Key($secretKey, 'HS256'));
        $decodedArray = (array)$decoded;
        $client = $decodedArray['sub'] ?? "unknown";
        $hasAccess = $decodedArray['has_access'] ?? false;
        if (!$hasAccess) {
            forwardToBroker($request, $response, $client, "Access denied", 403);
        } else {
            forwardToBroker($request, $response, $client, "Forwarded", 200);
        }
    } catch (Exception $e) {
        forwardToBroker($request, $response, null, "Invalid token", 401);
    }
});

function forwardToBroker(Request $request, Response $response, ?string $client, string $message, int $statusCode)
{
    global $kSink;
    
    // Merge the original request JSON (if any) with additional fields.
    $bodyContent = $request->getContent();
    $originalBody = json_decode($bodyContent, true);
    $payload = is_array($originalBody) ? $originalBody : [];
    $payload['client'] = $client;
    $payload['message'] = $message;
    
    $proceed = ($statusCode === 200);

    // Build fixed outgoing headers.
    $outHeaders = [];

    // Copy additional headers from the incoming request, skipping those in HEADERS_REMOVE.
    foreach ($request->header as $key => $value) {
        $skip = false;
        foreach (HEADERS_REMOVE as $remove) {
            if (strcasecmp($key, $remove) === 0) {
                $skip = true;
                break;
            }
        }
        if (!$skip) {
            $outHeaders[$key] = $value;
        }
    }

    if (!empty($request->header['ce-id'])) {
        $outHeaders['Ce-Id'] = $request->header['ce-id'];
    }
    $outHeaders['Ce-Specversion'] = '1.0';
    $outHeaders['Ce-Type'] = 'authorization';
    $outHeaders['Ce-Source'] = 'authorization';
    $outHeaders['Content-Type'] = 'application/json';
    $outHeaders['Ce-dv'] = $proceed ? 'true' : 'false';

    // Determine target sink: use the "x-k-sink" header if present; otherwise, use the global K_SINK.
    $targetSink = (isset($request->header['x-k-sink']) && !empty($request->header['x-k-sink'])) 
                    ? $request->header['x-k-sink'] 
                    : $kSink;

    // Forward the payload if a valid target sink is provided.
    if ($targetSink) {
        $parsedUrl = parse_url($targetSink);
        $host = $parsedUrl['host'] ?? '';
        $path = $parsedUrl['path'] ?? '/';
        $port = $parsedUrl['port'] ?? 80;
        $client = new Swoole\Coroutine\Http\Client($host, $port);
        $client->setHeaders($outHeaders);
        $client->post($path, json_encode($payload));
        echo "Successfully forwarded event to: $targetSink. Response: " . $client->body . "\n";
    } else {
        echo "Warning: No valid sink configured. Event not forwarded.\n";
    }

    // Respond to the original requester.
    $response->status($statusCode);
    $response->header("Content-Type", "application/json");
    $response->end(json_encode(["message" => $message]));
}

$server->start();

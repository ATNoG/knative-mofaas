import os
import requests
import json
import aiohttp
import aiohttp.web
import logging
import asyncio
import yarl


logging.basicConfig(level=logging.DEBUG)
logging.getLogger("http.client").setLevel(logging.DEBUG)

DEFAULT_CONCURRENCY = 1
SENDER_HEADER = "x-original-hostname"
IGNORE_HEADERS_RECEIVED = ("host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "accept-encoding",
                           "x-forwarded-proto", "x-request-id", "x-original-hostname", "x-envoy-expected-rq-timeout-ms", "x-forwarded-host", "traceparent", 
                           "forwarded", "k-proxy-request", "x-b3-sampled", "x-b3-spanid", "x-b3-traceid", "x-forwarded-for", "user-agent", "content-length", "accept")
IGNORE_HEADERS_SEND = ("transfer-encoding", "connection", "content-encoding")
ADMIN_HEADER_START = "x-start-request"
ADMIN_HEADER_STOP = "x-stop-request"
CLOUD_EVENT_ID_HEADER = "ce-id"

class MoFaaSProxy:
    def __init__(self):
        self.tasks = {}
        self.requests_queues = {}
        self.response_queues = {}

    async def proxy_handler(self, request):
        if request.headers.get(ADMIN_HEADER_START):
            body = await request.read()
            data = json.loads(body)
            req_id = data["id"]
            services = data["services"]

            logging.debug(f"Received new request to start: {data}")
            self.tasks[req_id] = asyncio.create_task(self.handle_requests(req_id, services))

            self.requests_queues[req_id] = {s: asyncio.Queue() for s in services}
            self.response_queues[req_id] = {s: asyncio.Queue() for s in services}
            return aiohttp.web.Response(status=200)
        if request.headers.get(ADMIN_HEADER_STOP):
            body = await request.read()
            data = json.loads(body)
            req_id = data["id"]
            logging.debug(f"Received new request to stop: {data}")
            self.tasks[req_id].cancel()
            del self.tasks[req_id]
            del self.requests_queues[req_id]
            del self.response_queues[req_id]
            return aiohttp.web.Response(status=200)

        sender_header = request.headers.get(SENDER_HEADER)
        sender = sender_header[:sender_header.find("deployment") - 7]
        req_id = request.headers.get(CLOUD_EVENT_ID_HEADER)
        await self.requests_queues[req_id][sender].put(request)

        # Return the response (wait for it)
        return await self.response_queues[req_id][sender].get()

    async def handle_requests(self, req_id, services):
        """Handles incoming HTTP requests and verifies identical ones before forwarding."""
        try:
            while True:
                request_store = {}
                for service in services:
                    request = await self.requests_queues[req_id][service].get()

                    method = request.method
                    body = await request.read()
                    headers = request.headers
                    path_qs = yarl.URL(request.path_qs).human_repr()

                    logging.debug(f"Received request: {method}")
                    logging.debug(f"Received headers: {headers}")

                    request_store[service] = (method, path_qs, headers, body)

                response = await self.forward_request(request_store, req_id)
                for service in services:
                    logging.debug(f"Sending response to {service}")
                    await self.response_queues[req_id][service].put(aiohttp.web.Response(status=response[0], body=response[1], headers=response[2]))
        except asyncio.CancelledError:
            return

    async def verify_requests_equal(self, request_store):
        """
        Verify that all stored requests have identical method, path, body, and
        filtered headers (i.e. after removing headers in IGNORE_HEADERS_RECEIVED).
        If they are identical, return True and tuple:
            (method, path, original_headers, body, filtered_headers)
        Otherwise, return False and message.
        """
        all_requests = list(request_store.items())
        if not all_requests:
            return False, "Internal issue"

        # Use the first request as the reference.
        ref_sender, (ref_method, ref_path, ref_headers, ref_body) = all_requests[0]
        ref_is_json = False
        ref_filtered = {}
        for k, v in ref_headers.items():
            if k.lower() == "content-type" and 'json' in v:
                ref_is_json = True
            if k.lower() not in IGNORE_HEADERS_RECEIVED:
                ref_filtered[k] = v
        # ref_filtered = {k: v for k, v in ref_headers.items() if k.lower() not in IGNORE_HEADERS_RECEIVED}

        for sender, (method, path, headers, body) in all_requests[1:]:
            current_filtered = {}
            is_json = False
            for k, v in headers.items():
                if k.lower() == "content-type" and 'json' in v:
                    is_json = True
                if k.lower() not in IGNORE_HEADERS_RECEIVED:
                    current_filtered[k] = v
            # current_filtered = {k: v for k, v in headers.items() if k.lower() not in IGNORE_HEADERS_RECEIVED}
            # Verify if body is json
            if ref_is_json and is_json:
                body = json.loads(body)
                ref_body = json.loads(ref_body)
            if method != ref_method or path != ref_path or body != ref_body or current_filtered != ref_filtered:
                err_message = f"Mismatch for sender '{ref_sender}' vs '{sender}': expected '{ref_method, ref_path, ref_filtered, ref_body}', got '{method, path, current_filtered, body}'"
                logging.error(err_message)
                return False, err_message
        return True, (ref_method, ref_path, ref_headers, ref_body, ref_filtered)

    async def forward_request(self, request_store, req_id):
        """Forwards the request to the original destination and returns the response."""
        verified = await self.verify_requests_equal(request_store)
        if not verified[0]:
            logging.error(f"Requests do not match. Potential attack happening for request id <{req_id}>.")
            await self.idependet_sinkbinding_forward_result(req_id, verified[1])
            return (400, b"Requests did not match!", {})
    
        _, (method, path, original_headers, body, filtered_headers) = verified
        proto = original_headers.get("X-Forwarded-Proto")
        host = original_headers.get("X-Forwarded-Host")
        
        url = f"{proto}://{host}{path}"
        logging.debug(f"Making <{method}> request to <{url}> with headers ({list(filtered_headers.items())}) and body <{body}>")
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=filtered_headers, **{'json' if type(body) == dict else 'data': body}) as resp:  # , headers=headers, data=body
                logging.debug(f"Response status: {resp.status}")
                response_body = await resp.read()
                logging.debug(f"Response body: {response_body}")
                return (resp.status, response_body, {k:v for k, v in dict(resp.headers).items() if k.lower() not in IGNORE_HEADERS_SEND})
    
    async def idependet_sinkbinding_forward_result(self, req_id, message):
        if k_sink := os.getenv("K_SINK"):
            headers = {
                "Ce-Id": req_id,
                "Ce-Specversion": "1.0",
                "Ce-Type": "egress-proxy-error",
                "Ce-Source": "egress-proxy",
                "Content-Type": "application/json",
            }
            requests.post(k_sink, json={"error_message": message}, headers=headers)

async def main():
    # Create the aiohttp application and route
    app = aiohttp.web.Application()
    proxy = MoFaaSProxy()
    # asyncio.create_task(proxy.handle_requests())
    app.router.add_route("*", "/{path_info:.*}", proxy.proxy_handler)

    # Properly run aiohttp app
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, host='0.0.0.0', port=8080)
    await site.start()

    logging.info("Server running on http://0.0.0.0:8080")

    # Keep the event loop alive
    await asyncio.Event().wait()  # Keeps the loop running forever


if __name__ == "__main__":
    asyncio.run(main())

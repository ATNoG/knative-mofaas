import os
import json
import aiohttp
import aiohttp.web
import logging
import asyncio
from collections import defaultdict


logging.basicConfig(level=logging.DEBUG)
logging.getLogger("http.client").setLevel(logging.DEBUG)

DEFAULT_CONCURRENCY = 1
SENDER_HEADER = "x-original-hostname"
IGNORE_HEADERS_RECEIVED = ("host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "accept-encoding",
                           "x-forwarded-proto", "x-request-id", "x-original-hostname", "x-envoy-expected-rq-timeout-ms", "x-forwarded-host", "traceparent", 
                           "forwarded", "k-proxy-request", "x-b3-sampled", "x-b3-spanid", "x-b3-traceid", "x-forwarded-for", "user-agent", "content-length")
IGNORE_HEADERS_SEND = ("transfer-encoding", "connection", "content-encoding")

class MoFaaSProxy:
    def __init__(self, concurrency):
        self.concurrency = concurrency
        
        self.request_store = defaultdict(tuple)
        self.response = defaultdict(tuple)
        self.events = defaultdict(tuple)

    async def proxy_handler(self, request):
        """Handles incoming HTTP requests and verifies identical ones before forwarding."""
        method = request.method
        body = await request.read()
        headers = request.headers
        path = request.path

        logging.debug(f"Received request: {method}")
        logging.debug(f"Received headers: {headers}")
        
        sender = headers[SENDER_HEADER][:headers[SENDER_HEADER].find("deployment") - 1]
        self.request_store[sender] = (method, path, headers, body)
        self.events[sender] = asyncio.Event()
        # import random
        # if sender == "test-00002" and random.random() > 0.5:
        #     self.request_store[sender] = (method, path, headers, body) = ("POST", path, headers, body)
        #     logging.debug("\n\n\nUEH\n\n\n")

        await self.forward_request()
        await self.events[sender].wait()
        logging.debug(f"Sending response to {sender}")
        response = aiohttp.web.Response(status=self.response[sender][0], body=self.response[sender][1], headers=self.response[sender][2])
        
        # Clear all variables
        self.request_store = defaultdict(tuple)

        return response

    async def verify_requests_equal(self):
        """
        Verify that all stored requests have identical method, path, body, and
        filtered headers (i.e. after removing headers in IGNORE_HEADERS_RECEIVED).
        If they are identical, return a tuple:
            (method, path, original_headers, body, filtered_headers)
        Otherwise, return None.
        """
        all_requests = list(self.request_store.items())
        if not all_requests:
            return None

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
                logging.error(f"Mismatch for sender '{sender}' vs '{ref_sender}': expected '{ref_method, ref_path, ref_filtered, ref_body}', got '{method, path, current_filtered, body}'")
                return None
        return (ref_method, ref_path, ref_headers, ref_body, ref_filtered)

    async def forward_request(self):
        """Forwards the request to the original destination and returns the response."""
        senders = list(self.request_store.keys())

        if len(self.request_store) == self.concurrency:
            # TODO -> VERIFY IF EQUAL
            verified = await self.verify_requests_equal()
            if verified is None:
                logging.debug("Requests do not match. Potential attack happening.")
                for sender in senders:
                    self.response[sender] = (400, b"Requests did not match!", {})
                    self.events[sender].set()
                return
        
            method, path, original_headers, body, filtered_headers = verified
            proto = original_headers.get("X-Forwarded-Proto")
            host = original_headers.get("X-Forwarded-Host")
            
            url = f"{proto}://{host}{path}"
            logging.debug(f"Making <{method}> request to <{url}> with headers ({list(filtered_headers.items())}) and body <{body}>")
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=filtered_headers, **{'json' if type(body) == dict else 'data': body}) as resp:  # , headers=headers, data=body
                    logging.debug(f"Response status: {resp.status}")
                    response_body = await resp.read()
                    logging.debug(f"Response body: {response_body}")
                    for sender in senders:
                        self.response[sender] = (resp.status, response_body, {k:v for k, v in dict(resp.headers).items() if k.lower() not in IGNORE_HEADERS_SEND})
                    logging.debug(f"Response headers: {self.response[sender][2]}")
                    
                    # Clear state
                    self.request_store = defaultdict(tuple)

                    for sender in senders:
                        self.events[sender].set()

def main():
    concurrency = int(os.environ.get("CONCURRENCY") or DEFAULT_CONCURRENCY)

    # Create the aiohttp application and route
    app = aiohttp.web.Application()
    proxy = MoFaaSProxy(concurrency)
    app.router.add_route("*", "/{path_info:.*}", proxy.proxy_handler)
    aiohttp.web.run_app(app, port=8080, access_log=None)


if __name__ == "__main__":
    main()

import os
import aiohttp
import aiohttp.web
import logging
import asyncio
from collections import defaultdict


logging.basicConfig(level=logging.DEBUG)
logging.getLogger("http.client").setLevel(logging.DEBUG)

DEFAULT_CONCURRENCY = 2
SENDER_HEADER = "x-original-hostname"
IGNORE_HEADERS_RECEIVED = ("host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "accept-encoding",
                           "x-forwarded-proto", "x-request-id", "x-original-hostname", "x-envoy-expected-rq-timeout-ms", "x-forwarded-host", )
IGNORE_HEADERS_SEND = ("transfer-encoding", "connection", "content-encoding")

class MoFaaSProxy:
    def __init__(self, concurrency):
        self.concurrency = concurrency
        
        self.request_store = defaultdict(tuple)
        self.event = asyncio.Event()
        self.response = None

    async def proxy_handler(self, request):
        """Handles incoming HTTP requests and verifies identical ones before forwarding."""
        method = request.method
        body = await request.read()
        headers = dict(request.headers)
        path = request.path

        logging.debug(f"Received request: {method}")
        logging.debug(f"Received headers: {headers}")
        
        sender = headers[SENDER_HEADER][:headers[SENDER_HEADER].find("deployment") - 1]
        request_data = (method, path, headers, body)
        self.request_store[sender] = request_data
        
        await self.forward_request()
        await self.event.wait()
        logging.debug(f"Sending response to {sender}")
        response = aiohttp.web.Response(status=self.response[0], body=self.response[1], headers=self.response[2])

        return response

    async def forward_request(self):
        """Forwards the request to the original destination and returns the response."""
        if len(self.request_store) == self.concurrency:
            # TODO -> VERIFY IF EQUAL
            (method, path, headers, body) = self.request_store[list(self.request_store.keys())[0]]
            filtered_headers = {k: v for k, v in headers.items() if k.lower() not in IGNORE_HEADERS_RECEIVED}
            logging.debug(f"Making request with headers ({list(filtered_headers.items())})")
            async with aiohttp.ClientSession() as session:
                async with session.request(method, f"{headers['X-Forwarded-Proto']}://{headers['X-Forwarded-Host']}/{path}", headers=filtered_headers, data=body) as resp:  # , headers=headers, data=body
                    logging.debug(f"Response status: {resp.status}")
                    response_body = await resp.read()
                    self.response = (resp.status, response_body, {k:v for k, v in dict(resp.headers).items() if k.lower() not in IGNORE_HEADERS_SEND})
                    logging.debug(f"Response headers: {self.response[2]}")
                    self.event.set()

def main():
    concurrency = int(os.environ.get("CONCURRENCY") or DEFAULT_CONCURRENCY)

    # Create the aiohttp application and route
    app = aiohttp.web.Application()
    proxy = MoFaaSProxy(concurrency)
    app.router.add_route("*", "/{path_info:.*}", proxy.proxy_handler)
    aiohttp.web.run_app(app, port=8080, access_log=None)


if __name__ == "__main__":
    main()

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
        url = str(request.url)
        headers = dict(request.headers)

        logging.debug(f"Received request: {method} {url}")
        logging.debug(f"Received headers: {headers}")
        
        sender = headers[SENDER_HEADER][:headers[SENDER_HEADER].find("deployment") - 1]
        request_data = (method, url, headers, body)
        self.request_store[sender] = request_data
        
        await self.forward_request()
        await self.event.wait()
        logging.debug("Sending response")
        logging.debug(self.response[2])
        response = aiohttp.web.Response(status=self.response[0], body=self.response[1], headers=self.response[2])
        if self.response[2].get('Transfer-Encoding') == 'chunked':
            response.enable_chunked_encoding()
        logging.debug(response.headers)
        return response
        # async with self.lock:
        #     # Check if all stored requests are identical
        #     requests = self.request_store[url]
        #     if len(requests) == self.expected_count and all(req == requests[0] for req in requests):
        #         logging.debug("All requests match! Forwarding...")
        #         del self.request_store[url]  # Reset for the next batch
        #         return await self.forward_request(*requests[0])
        #     else:
        #         logging.debug(f"Stored {len(requests)}/{self.expected_count} requests for {url}.")
        #         return aiohttp.web.Response(status=202, text="Waiting for more matching requests...")

    async def forward_request(self):
        """Forwards the request to the original destination and returns the response."""
        if len(self.request_store) == self.concurrency:
            # TODO -> VERIFY IF EQUAL
            (method, url, headers, body) = self.request_store[list(self.request_store.keys())[0]]
            async with aiohttp.ClientSession() as session:
                async with session.request(method, f"{headers['X-Forwarded-Proto']}://{headers['X-Forwarded-Host']}") as resp:  # , headers=headers, data=body
                    logging.debug(f"{headers['X-Forwarded-Proto']}://{headers['X-Forwarded-Host']}")
                    logging.debug(f"Making request")
                    logging.debug(resp.status)
                    response_body = await resp.read()
                    logging.debug(response_body)
                    self.response = (resp.status, response_body, dict(resp.headers))
                    # self.response[2].pop("Transfer-Encoding")
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

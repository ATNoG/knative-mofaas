import aiohttp
import aiohttp.web
import logging
import asyncio
from collections import defaultdict


logging.basicConfig(level=logging.DEBUG)
logging.getLogger("http.client").setLevel(logging.DEBUG)

class MoFaaSProxy:
    def __init__(self):
        self.request_store = defaultdict(list)
        self.expected_count = 2  # Change this to the number of identical requests required
        self.lock = asyncio.Lock()

    async def proxy_handler(self, request):
        """Handles incoming HTTP requests and verifies identical ones before forwarding."""
        method = request.method
        body = await request.read()
        url = str(request.url)
        headers = dict(request.headers)
        
        logging.debug(f"Received request: {method} {url}")
        logging.debug(f"Received headers: {headers}")

        request_data = (method, url, headers, body)
        async with self.lock:
            self.request_store[url].append(request_data)

            # Check if all stored requests are identical
            requests = self.request_store[url]
            if len(requests) == self.expected_count and all(req == requests[0] for req in requests):
                logging.debug("All requests match! Forwarding...")
                del self.request_store[url]  # Reset for the next batch
                return await self.forward_request(*requests[0])
            else:
                logging.debug(f"Stored {len(requests)}/{self.expected_count} requests for {url}.")
                return aiohttp.web.Response(status=202, text="Waiting for more matching requests...")

    async def forward_request(self, method, url, headers, body):
        """Forwards the request to the original destination and returns the response."""
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, data=body) as resp:
                response_body = await resp.read()
                return aiohttp.web.Response(status=resp.status, body=response_body, headers=dict(resp.headers))


def main():
    # Create the aiohttp application and route
    app = aiohttp.web.Application()
    proxy = MoFaaSProxy()
    app.router.add_route("*", "/{path_info:.*}", proxy.proxy_handler)
    aiohttp.web.run_app(app, port=8080, access_log=None)


if __name__ == "__main__":
    main()

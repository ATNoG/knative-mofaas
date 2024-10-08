import os
import base64
import logging
import random
import asyncio
import urllib
import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("http.client").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.DEBUG)

PORT = 8080
DEFAULT_CONCURRENCY = 1

async def proxy_handler(request, services_list, concurrency):
    """This method only works for HTTP at the moment!!! Do not try to use the Proxy for HTTPS, it will fail miserably!!!"""
    # Extract information from the incoming request
    method = request.method
    headers = request.headers.copy()
    body = await request.read()
    
    # Choosing the function to execute and change the Host header accordingly
    chosen_funcs = random.sample(services_list, k=concurrency)
    logging.debug(f"Chosen functions: {chosen_funcs}")
    headers["Host"] = urllib.parse.urlparse(chosen_funcs[0]).netloc
    
    target_url = f"{chosen_funcs[0]}{request.path}"

    async with aiohttp.ClientSession() as session:
        async with session.request(method, target_url, headers=headers, data=body) as response:
            # Forward the response from the target server
            proxied_response = web.Response(
                status=response.status,
                body=await response.read(),
                headers=response.headers
            )
            return proxied_response


def main():
    # Using a first class function just to the entry arguments to the proxy
    def proxy_handler_parameters(services_list, concurrency):
        async def inner(request):
            response = await proxy_handler(request, services_list, concurrency)
            return response
        return inner
    
    if not (services := os.environ.get("SERVICES")):
        logging.error("There were no given services")
        exit(1)
    services_list = [base64.b64decode(s).decode() for s in services.split(",")]
    concurrency = int(os.environ.get("CONCURRENCY") or DEFAULT_CONCURRENCY)

    # signal.signal(signal.SIGTERM, signal_handler)
    # Create the aiohttp application and route
    app = web.Application()
    app.router.add_route('*', '/{path_info:.*}', proxy_handler_parameters(services_list, concurrency))
    web.run_app(app, port=PORT)


if __name__ == '__main__':
    main()

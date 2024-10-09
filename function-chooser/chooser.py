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

async def do_request(session: aiohttp.ClientSession, method, url, headers, body):
    logging.debug(f"Doing a request to: {url}")
    async with session.request(method, url, headers=headers, data=body) as response:
        # Forward the response from the target server
        # proxied_response = web.Response(
        #     status=response.status,
        #     body=await response.read(),
        #     headers=response.headers
        # )
        # print(i)
        return {
            'url': url, 
            'status': response.status, 
            'body': await response.read(),
            'headers': response.headers
        }


async def proxy_handler(request, services_list, concurrency, ignore_headers):
    """This method only works for HTTP at the moment!!! Do not try to use the Proxy for HTTPS, it will fail miserably!!!"""
    # Extract information from the incoming request
    method = request.method
    headers = request.headers.copy()
    body = await request.read()

    # Choosing the function to execute and change the Host header accordingly
    chosen_funcs = random.sample(services_list, k=concurrency)
    logging.debug(f"Chosen functions: {chosen_funcs}")
    headers["Host"] = urllib.parse.urlparse(chosen_funcs[0]).netloc

    async with aiohttp.ClientSession() as session:
        tasks = []
        for url in chosen_funcs:
            target_url = f"{url}{request.path}"
            tasks.append(asyncio.create_task(do_request(session=session, method=method, url=target_url, headers=headers, body=body)))
        responses = await asyncio.gather(*tasks)
        proxied_response = web.Response(
            status=200,
            body='done',
            headers=headers
        )
        differences_matrixes = {
            'status': {},
            'body': {},
            'headers': {}
        }
        for r1 in responses:
            for r2 in responses:
                if r1 == r2:
                    continue
                for k in differences_matrixes:
                    if r1['url'] not in differences_matrixes[k]:
                        differences_matrixes[k][r1['url']] = {}
                    if r2['url'] not in differences_matrixes[k]:
                        differences_matrixes[k][r2['url']] = {}

                    # By default, everything is OK
                    differences_matrixes[k][r1['url']][r1['url']] = 0 if k != 'headers' else {}
                    differences_matrixes[k][r1['url']][r2['url']] = 0 if k != 'headers' else {}

                    if r1[k] != r2[k]:
                        if k != 'headers':
                            logging.error(f"{k.capitalize()} different between response from the URL <{r1['url']}> and <{r2['url']}>")
                            differences_matrixes[k][r1['url']][r2['url']] = 1
                            differences_matrixes[k][r2['url']][r1['url']] = 1
                        else:
                            for header in list(r1[k].keys()) + list(r2[k].keys()):
                                if header not in differences_matrixes[k][r1['url']][r2['url']]:
                                    differences_matrixes[k][r1['url']][r2['url']][header] = {}
                                if header not in differences_matrixes[k][r2['url']][r1['url']]:
                                    differences_matrixes[k][r2['url']][r1['url']][header] = {}
                                
                                # By default, everything is OK
                                differences_matrixes[k][r1['url']][r2['url']][header] = 0
                                differences_matrixes[k][r2['url']][r1['url']][header] = 0
                                
                                if header not in r1[k] and header in r2[k]:
                                    message = f"Header <{header}> not found in the response from the URL <{r1['url']}>, but found in the URL <{r2['url']}>."
                                    if header in ignore_headers:
                                        logging.warning(message + " Ignoring, because it is in the given IGNORE HEADERS list.")
                                    else:
                                        logging.error(message + " It will be flagged.")
                                        differences_matrixes[k][r1['url']][r2['url']][header] = 1
                                        differences_matrixes[k][r2['url']][r1['url']][header] = 1
                                elif header not in r2[k] and header in r1[k]:
                                    message = f"Header <{header}> not found in the response from the URL <{r2['url']}>, but found in the URL <{r1['url']}>."
                                    if header in ignore_headers:
                                        logging.warning(message + " Ignoring, because it is in the given IGNORE HEADERS list.")
                                    else:
                                        logging.error(message + " It will be flagged.")
                                        differences_matrixes[k][r1['url']][r2['url']][header] = 1
                                        differences_matrixes[k][r2['url']][r1['url']][header] = 1
                                elif r1[k][header] != r2[k][header]:
                                    message = f"Header <{header}> from URL <{r1['url']}> (value: <{r1[k][header]}>) not equal to the one from URL <{r2['url']}> (value: <{r2[k][header]}>)."
                                    if header in ignore_headers:
                                        logging.warning(message + " Ignoring, because it is in the given IGNORE HEADERS list.")
                                    else:
                                        logging.error(message + " It will be flagged.")
                                        differences_matrixes[k][r1['url']][r2['url']][header] = 1
                                        differences_matrixes[k][r2['url']][r1['url']][header] = 1

        print(differences_matrixes)
        return proxied_response

def main():
    # Using a first class function just to give entry arguments to the proxy
    def proxy_handler_parameters(services_list, concurrency, ignore_headers):
        async def inner(request):
            response = await proxy_handler(request, services_list, concurrency, ignore_headers)
            return response
        return inner
    
    if not (services := os.environ.get("SERVICES")):
        logging.error("There were no given services")
        exit(1)
    services_list = [base64.b64decode(s).decode() for s in services.split(",")]
    concurrency = int(os.environ.get("CONCURRENCY") or DEFAULT_CONCURRENCY)
    ignore_headers = []
    if (ignore_headers_enc := os.environ.get("IGNORE_HEADERS")):
        ignore_headers = [base64.b64decode(s).decode() for s in ignore_headers_enc.split(",")]

    # signal.signal(signal.SIGTERM, signal_handler)
    # Create the aiohttp application and route
    app = web.Application()
    app.router.add_route('*', '/{path_info:.*}', proxy_handler_parameters(services_list, concurrency, ignore_headers))
    web.run_app(app, port=PORT)


if __name__ == '__main__':
    main()

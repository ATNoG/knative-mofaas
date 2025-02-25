import os
import json
import math
import random
import logging
import base64
import asyncio
import urllib
import aiohttp
import aiohttp.web

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("http.client").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.DEBUG)

PORT = 8080
DEFAULT_CONCURRENCY = 1
K_SINK_HEADER = "X-K-Sink"
CE_OVERRIDES_HEADER = "X-Ce-Overrides"
EGRESS_START_HEADER = "x-start-request"
EGRESS_STOP_HEADER = "x-stop-request"

class MoFaaSProxy:
    def __init__(self, services, concurrency, ignore_headers, egress_url, k_sink=None, ce_overrides=None):
        self.services = services
        self.concurrency = concurrency
        self.ignore_headers = ignore_headers
        self.egress_url = egress_url
        self.k_sink = k_sink
        self.ce_overrides = ce_overrides

    async def proxy_handler(self, request):
        """This method only works for HTTP at the moment!!! Do not try to use the Proxy for HTTPS, it will fail miserably!!!"""
        # Extract information from the incoming request
        method = request.method
        body = await request.read()
        request_id = request.headers.get("ce-id")

        # Choosing the function to execute and change the Host header accordingly
        chosen_funcs = random.sample(list(self.services.keys()), k=self.concurrency)
        logging.debug(f"Chosen functions: {chosen_funcs}")
        await self.__egress_request({EGRESS_START_HEADER: "true"}, {"services": chosen_funcs, "id": request_id})

        async with aiohttp.ClientSession() as session:
            tasks = []
            for func in chosen_funcs:
                url = self.services[func]
                target_url = f"{url}{request.path}"
                headers = request.headers.copy()
                headers["Host"] = urllib.parse.urlparse(url).netloc
                if self.k_sink:
                    headers[K_SINK_HEADER] = self.k_sink
                if self.ce_overrides:
                    headers[CE_OVERRIDES_HEADER] = self.ce_overrides
                tasks.append(
                    asyncio.create_task(
                        self.__do_request(
                            session=session,
                            method=method,
                            url=target_url,
                            headers=headers,
                            body=body,
                        )
                    )
                )
            responses = await asyncio.gather(*tasks)
            
            verified, response = await self.__verify_responses(responses)

            if verified:
                status = response["status"]
                body = json.dumps(response["body"]) if type(response["body"]) == dict else response["body"]
                headers = {k: v for k,v in response["headers"].items() if k.lower() != 'content-length'}
                logging.debug(f"Sending response with status <{status}>, body <{body}>, headers {headers}")
                proxied_response = aiohttp.web.Response(
                    status=status,
                    body=body,
                    headers=headers,
                )
                await self.__egress_request({EGRESS_STOP_HEADER: "true"}, {"id": request_id})
                return proxied_response
            else:
                # Notice the Egress Proxy that this request ended
                await self.__egress_request({EGRESS_STOP_HEADER: "true"}, {"id": request_id})
                
                await self.__idependet_sinkbinding_forward_result(request_id, response)

                proxied_response = aiohttp.web.Response(
                    status=400, body=json.dumps({"message": "Responses did not match!"}), headers={"Content-Type": "application/json"}
                )
                return proxied_response
    
    async def __verify_responses(self, responses):
        ref_response = responses[0]
        for response in responses[1:]:    
            for k in ref_response:
                if k not in ("headers", "url"):
                    if ref_response[k] != response[k]:
                        err_message = f"{k.capitalize()} different between response from the URL <{ref_response['url']}> ({ref_response[k]}) and <{response['url']} ({response[k]})>"
                        logging.error(err_message)
                        return False, err_message
                elif k == "headers":
                    for header in list(ref_response[k].keys()) + list(response[k].keys()):
                        if (
                            header not in ref_response[k]
                            and header in response[k]
                        ):
                            message = f"Header <{header}> not found in the response from the URL <{ref_response['url']}>, but found in the URL <{response['url']}>."
                            ignore, message = await self.__verify_ignore_headers(header=header, message=message)
                            if not ignore:
                                return False, message
                        elif (
                            header not in response[k]
                            and header in ref_response[k]
                        ):
                            message = f"Header <{header}> not found in the response from the URL <{response['url']}>, but found in the URL <{ref_response['url']}>."
                            ignore, message = await self.__verify_ignore_headers(header=header, message=message)
                            if not ignore:
                                return False, message
                        elif (
                            ref_response[k][header]
                            != response[k][header]
                        ):
                            message = f"Header <{header}> from URL <{ref_response['url']}> (value: <{ref_response[k][header]}>) not equal to the one from URL <{response['url']}> (value: <{response[k][header]}>)."
                            ignore, message = await self.__verify_ignore_headers(header=header, message=message)
                            if not ignore:
                                return False, message
        return True, ref_response

    async def __egress_request(self, headers, data):
        if not self.egress_url:
            logging.warning("Will not send a request to the egress, as there is none")
            return 
        async with aiohttp.ClientSession() as session:
            logging.debug(f"Sending {data} to the egress with headers {headers}")
            async with session.post(self.egress_url, headers=headers, json=data) as response:
                if response.status != 200:
                    logging.error(f"The response from the Egress was not successful: status code <{response.status}> and body <{response.content}>")
        

    async def __do_request(
        self, session: aiohttp.ClientSession, method, url, headers, body
    ):
        logging.debug(f"Doing a request to: {url}")
        async with session.request(method, url, headers=headers, data=body) as response:
            body = await response.read()
            if response.headers.get('content-type') == 'application/json':
                body = json.loads(body)
            return {
                "url": url,
                "status": response.status,
                "body": body,
                "headers": response.headers,
            }
    
    async def __verify_ignore_headers(
        self,
        header,
        message,
    ):
        if header in self.ignore_headers:
            logging.warning(
                message + " Ignoring, because it is in the given IGNORE HEADERS list."
            )
            return True, message
        else:
            logging.error(message + " It will be flagged.")
            return False, message

    async def __idependet_sinkbinding_forward_result(self, req_id, message):
        if k_sink := os.getenv("K_SINK"):
            headers = {
                "Ce-Id": req_id,
                "Ce-Specversion": "1.0",
                "Ce-Type": "chooser-error",
                "Ce-Source": "chooser",
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(k_sink, json={"error_message": message}, headers=headers) as resp:
                    logging.debug(f"Made request to ksink {k_sink}")

def main():
    if not (services_names := os.environ.get("SERVICES")):
        logging.error("There were no given services")
        exit(1)
    if not (services_urls := os.environ.get("SERVICES_URLS")):
        logging.error("There were no given services URLs")
        exit(1)

    egress_url = None           # Default value
    if egress_url_b64 := os.environ.get("EGRESS_URL"):
        egress_url = base64.b64decode(egress_url_b64).decode()
    
    services = {}
    services_urls_b64_list = services_urls.split(",")
    for i in range(len(services_list := services_names.split(","))):
        services[services_list[i]] = base64.b64decode(services_urls_b64_list[i]).decode()
    concurrency = int(os.environ.get("CONCURRENCY") or DEFAULT_CONCURRENCY)
    ignore_headers = []
    if ignore_headers_enc := os.environ.get("IGNORE_HEADERS"):
        ignore_headers = [
            base64.b64decode(s).decode() for s in ignore_headers_enc.split(",")
        ]
    logging.debug(
        f"""======== Starting MoFaaS Chooser ========
           Services: {', '.join(services.keys())}
           Services URLs: {', '.join(services.values())}
           Concurrency: {concurrency}
           Ignore headers: {', '.join(ignore_headers)}
           Egress URL: {egress_url}
           ========================================="""
    )

    # Create the aiohttp application and route
    app = aiohttp.web.Application()
    proxy = MoFaaSProxy(services, concurrency, ignore_headers, egress_url, os.environ.get("K_SINK"), os.environ.get("CE_OVERRIDES"))
    app.router.add_route("*", "/{path_info:.*}", proxy.proxy_handler)
    aiohttp.web.run_app(app, port=PORT)


if __name__ == "__main__":
    main()

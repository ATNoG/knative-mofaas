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

            differences_matrixes = {"status": {}, "body": {}, "headers": {}}
            equal_results = [
                [r2["url"] for r2 in responses if r2 != r1] for r1 in responses
            ]
            for i1 in range(len(responses)):
                for i2 in range(len(responses)):
                    if responses[i1] == responses[i2]:
                        continue
                    for k in differences_matrixes:
                        await self.__fill_resultant_structs_defaults(
                            differences_matrixes, responses, key=k, index1=i1, index2=i2
                        )

                        if responses[i1][k] != responses[i2][k]:
                            if k != "headers":
                                logging.error(
                                    f"{k.capitalize()} different between response from the URL <{responses[i1]['url']}> ({responses[i1][k]}) and <{responses[i2]['url']} ({responses[i2][k]})>"
                                )
                                await self.__fill_resultant_structs(
                                    differences_matrixes,
                                    equal_results,
                                    responses,
                                    key=k,
                                    index1=i1,
                                    index2=i2,
                                )
                            else:
                                for header in list(responses[i1][k].keys()) + list(
                                    responses[i2][k].keys()
                                ):
                                    await self.__fill_resultant_structs_defaults(
                                        differences_matrixes,
                                        responses,
                                        key=k,
                                        index1=i1,
                                        index2=i2,
                                        header=header,
                                    )

                                    if (
                                        header not in responses[i1][k]
                                        and header in responses[i2][k]
                                    ):
                                        message = f"Header <{header}> not found in the response from the URL <{responses[i1]['url']}>, but found in the URL <{responses[i2]['url']}>."
                                        await self.__verify_ignore_headers(
                                            differences_matrixes,
                                            equal_results,
                                            responses,
                                            key=k,
                                            index1=i1,
                                            index2=i2,
                                            header=header,
                                            message=message,
                                        )
                                    elif (
                                        header not in responses[i2][k]
                                        and header in responses[i1][k]
                                    ):
                                        message = f"Header <{header}> not found in the response from the URL <{responses[i2]['url']}>, but found in the URL <{responses[i1]['url']}>."
                                        await self.__verify_ignore_headers(
                                            differences_matrixes,
                                            equal_results,
                                            responses,
                                            key=k,
                                            index1=i1,
                                            index2=i2,
                                            header=header,
                                            message=message,
                                        )
                                    elif (
                                        responses[i1][k][header]
                                        != responses[i2][k][header]
                                    ):
                                        message = f"Header <{header}> from URL <{responses[i1]['url']}> (value: <{responses[i1][k][header]}>) not equal to the one from URL <{responses[i2]['url']}> (value: <{responses[i2][k][header]}>)."
                                        await self.__verify_ignore_headers(
                                            differences_matrixes,
                                            equal_results,
                                            responses,
                                            key=k,
                                            index1=i1,
                                            index2=i2,
                                            header=header,
                                            message=message,
                                        )

            # TODO -> This should be sent to a controller!!!
            logging.info(f"Differences matrix: {differences_matrixes}")

            accepted_minimum = math.floor(self.concurrency / 2) + 1
            for i in range(len(equal_results)):
                # Plus 1 because it is counting with the request itself being verified
                if len(equal_results[i]) + 1 >= accepted_minimum:
                    proxied_response = aiohttp.web.Response(
                        status=responses[i]["status"],
                        body=json.dumps(responses[i]["body"]) if type(responses[i]["body"]) == dict else responses[i]["body"],
                        headers={k: v for k,v in responses[i]["headers"].items() if k.lower() != 'content-length'},
                    )
                    await self.__egress_request({EGRESS_STOP_HEADER: "true"}, {"id": request_id})
                    return proxied_response

        # Notice the Egress Proxy that this request ended
        await self.__egress_request({EGRESS_STOP_HEADER: "true"}, {"id": request_id})

        proxied_response = aiohttp.web.Response(
            status=400, body="yeet", headers=headers
        )
        return proxied_response

    async def __egress_request(self, headers, data):
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

    async def __fill_resultant_structs_defaults(
        self, differences_matrixes, responses, key, index1, index2, header=None
    ):
        if not header:
            if responses[index1]["url"] not in differences_matrixes[key]:
                differences_matrixes[key][responses[index1]["url"]] = {}
            if responses[index2]["url"] not in differences_matrixes[key]:
                differences_matrixes[key][responses[index2]["url"]] = {}

            # By default, everything is O key
            differences_matrixes[key][responses[index1]["url"]][
                responses[index2]["url"]
            ] = (0 if key != "headers" else {})
            differences_matrixes[key][responses[index2]["url"]][
                responses[index1]["url"]
            ] = (0 if key != "headers" else {})
        else:
            if (
                header
                not in differences_matrixes[key][responses[index1]["url"]][
                    responses[index2]["url"]
                ]
            ):
                differences_matrixes[key][responses[index1]["url"]][
                    responses[index2]["url"]
                ][header] = {}
            if (
                header
                not in differences_matrixes[key][responses[index2]["url"]][
                    responses[index1]["url"]
                ]
            ):
                differences_matrixes[key][responses[index2]["url"]][
                    responses[index1]["url"]
                ][header] = {}

            # By default, everything is O key
            differences_matrixes[key][responses[index1]["url"]][
                responses[index2]["url"]
            ][header] = 0
            differences_matrixes[key][responses[index2]["url"]][
                responses[index1]["url"]
            ][header] = 0

    async def __fill_resultant_structs(
        self,
        differences_matrixes,
        equal_results,
        responses,
        key,
        index1,
        index2,
        header=None,
    ):
        if header:
            differences_matrixes[key][responses[index1]["url"]][
                responses[index2]["url"]
            ][header] = 1
            differences_matrixes[key][responses[index2]["url"]][
                responses[index1]["url"]
            ][header] = 1
        else:
            differences_matrixes[key][responses[index1]["url"]][
                responses[index2]["url"]
            ] = 1
            differences_matrixes[key][responses[index2]["url"]][
                responses[index1]["url"]
            ] = 1
        if responses[index2]["url"] in equal_results[index1]:
            equal_results[index1].pop(
                equal_results[index1].index(responses[index2]["url"])
            )
        if responses[index1]["url"] in equal_results[index2]:
            equal_results[index2].pop(
                equal_results[index2].index(responses[index1]["url"])
            )

    async def __verify_ignore_headers(
        self,
        differences_matrixes,
        equal_results,
        responses,
        key,
        index1,
        index2,
        header,
        message,
    ):
        if header in self.ignore_headers:
            logging.warning(
                message + " Ignoring, because it is in the given IGNORE HEADERS list."
            )
        else:
            logging.error(message + " It will be flagged.")
            await self.__fill_resultant_structs(
                differences_matrixes,
                equal_results,
                responses,
                key=key,
                index1=index1,
                index2=index2,
                header=header,
            )


def main():
    if not (services_names := os.environ.get("SERVICES")):
        logging.error("There were no given services")
        exit(1)
    if not (services_urls := os.environ.get("SERVICES_URLS")):
        logging.error("There were no given services URLs")
        exit(1)
    if not (egress_url_b64 := os.environ.get("EGRESS_URL")):
        logging.error("There was no given egress URL")
        exit(1)

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

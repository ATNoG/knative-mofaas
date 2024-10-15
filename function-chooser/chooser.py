import os
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


class MoFaaSProxy:
    def __init__(self, services_list, concurrency, ignore_headers):
        self.services_list = services_list
        self.concurrency = concurrency
        self.ignore_headers = ignore_headers

    async def proxy_handler(self, request):
        """This method only works for HTTP at the moment!!! Do not try to use the Proxy for HTTPS, it will fail miserably!!!"""
        # Extract information from the incoming request
        method = request.method
        body = await request.read()

        # Choosing the function to execute and change the Host header accordingly
        chosen_funcs = random.sample(self.services_list, k=self.concurrency)
        logging.debug(f"Chosen functions: {chosen_funcs}")

        async with aiohttp.ClientSession() as session:
            tasks = []
            for url in chosen_funcs:
                target_url = f"{url}{request.path}"
                headers = request.headers.copy()
                headers["Host"] = urllib.parse.urlparse(url).netloc
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
                                    f"{k.capitalize()} different between response from the URL <{responses[i1]['url']}> and <{responses[i2]['url']}>"
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
                        body=responses[i]["body"],
                        headers=responses[i]["headers"],
                    )
                    return proxied_response

        proxied_response = aiohttp.web.Response(
            status=400, body="yeet", headers=headers
        )
        return proxied_response

    async def __do_request(
        self, session: aiohttp.ClientSession, method, url, headers, body
    ):
        logging.debug(f"Doing a request to: {url}")
        async with session.request(method, url, headers=headers, data=body) as response:
            return {
                "url": url,
                "status": response.status,
                "body": await response.read(),
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
    if not (services := os.environ.get("SERVICES")):
        logging.error("There were no given services")
        exit(1)
    services_list = [base64.b64decode(s).decode() for s in services.split(",")]
    concurrency = int(os.environ.get("CONCURRENCY") or DEFAULT_CONCURRENCY)
    ignore_headers = []
    if ignore_headers_enc := os.environ.get("IGNORE_HEADERS"):
        ignore_headers = [
            base64.b64decode(s).decode() for s in ignore_headers_enc.split(",")
        ]
    logging.debug(
        f"""======== Starting MoFaaS Chooser ========
           Services: {', '.join(services_list)}
           Concurrency: {concurrency}
           Ignore headers: {', '.join(ignore_headers)}
           ========================================="""
    )

    # Create the aiohttp application and route
    app = aiohttp.web.Application()
    proxy = MoFaaSProxy(services_list, concurrency, ignore_headers)
    app.router.add_route("*", "/{path_info:.*}", proxy.proxy_handler)
    aiohttp.web.run_app(app, port=PORT)


if __name__ == "__main__":
    main()

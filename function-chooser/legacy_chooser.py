from http import HTTPStatus
import http.server
import socketserver
import os, requests
import signal
import logging
import urllib
import random

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("http.client").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.DEBUG)

PORT = 8080
DEFAULT_CONCURRENCY = 1

class Proxy(http.server.BaseHTTPRequestHandler):
    def __init__(self, *args, **kargs):
        if not (services := os.environ.get("SERVICES")):
            logging.error("There were no given services")
            exit(1)
        self.services_list = services.split(",")
        self.concurrency = os.environ.get("CONCURRENCY") or DEFAULT_CONCURRENCY

        super().__init__(*args, **kargs)

    def do_proxy(self):
        # Extract headers
        headers = {key: value for key, value in self.headers.items()}

        # Prepare the request body for methods like POST, PUT, etc.
        body = None
        if 'Content-Length' in self.headers:
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)

        chosen_func_i = int(random.random() * len(self.services_list))
        logging.debug(f"Function of index <{chosen_func_i}> chosen")
        headers["Host"] = urllib.parse.urlparse(self.services_list[chosen_func_i]).netloc
        response = requests.request(self.command, self.services_list[chosen_func_i], headers=headers, data=body)

        # Send the response back to the client
        self.send_response(response.status_code)
        for key, value in response.headers.items():
            self.send_header(key, value)
            self.end_headers()

        # Write the response content back to the client
        logging.debug(response.content)
        self.wfile.write(response.content)

    def handle_one_request(self):
        """This method was overridden from the inherited class
        """
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                self.send_error(HTTPStatus.REQUEST_URI_TOO_LONG)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                # An error code has been sent, just exit
                return
            ########################## THIS IS THE OVERRIDDEN PART ##########################
            # mname = 'do_' + self.command
            # if not hasattr(self, mname):
            #     self.send_error(
            #         HTTPStatus.NOT_IMPLEMENTED,
            #         "Unsupported method (%r)" % self.command)
            #     return
            # method = getattr(self, mname)
            # method()
            self.do_proxy()
            ########################## FINISH OVERWRITING ##########################
            self.wfile.flush() #actually send the response if not already done.
        except TimeoutError as e:
            #a read or a write timed out.  Discard this connection
            self.log_error("Request timed out: %r", e)
            self.close_connection = True
            return

def signal_handler(signum, frame):
    logging.info("Exiting gracefully")
    exit(0)

def main():
    signal.signal(signal.SIGTERM, signal_handler)
    # Run the server
    with socketserver.TCPServer(("", PORT), Proxy) as httpd:
        logging.info(f"Serving proxy on port {PORT}")
        httpd.serve_forever()


if __name__ == '__main__':
    main()

import http.server
import socketserver
from urllib.parse import urlparse
import os, requests


PORT = 8080

class Proxy(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kargs):
        if not (services := os.environ.get("SERVICES")):
            print("There were no given services")
        self.services_list = services.split(",")

        super().__init__(*args, **kargs)

    def handle_one_request(self):
        # Parse the incoming request URL
        parsed_url = urlparse(self.path)
        
        # Extract headers
        headers = {key: value for key, value in self.headers.items()}
        
        # Prepare the request body for methods like POST, PUT, etc.
        body = None
        if 'Content-Length' in self.headers:
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)

        # Forward the request to the target server based on the method
        method = self.command
        response = requests.request(method, self.services_list[0], headers=headers, data=body)

        # Send the response back to the client
        self.send_response(response.status_code)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        
        # Write the response content back to the client
        self.wfile.write(response.content)


def main():
    # Run the server
    with socketserver.TCPServer(("", PORT), Proxy) as httpd:
        print(f"Serving proxy on port {PORT}")
        httpd.serve_forever()

if __name__ == '__main__':
    main()
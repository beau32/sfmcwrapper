#!/usr/bin/env python3
import http.server
import ssl
import os

PORT = 8000
ALLOWED_FILES = ["cytoscaple.html", "activities.json","automations.json"]

class MultiFileHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Serve root as cytoscaple.html
        if self.path == "/":
            self.path = "cytoscaple.html"
        elif self.path.startswith("/"):
            requested_file = self.path[1:]  # remove leading '/'
            if requested_file not in ALLOWED_FILES:
                self.send_error(404, "File not found")
                return
            self.path = requested_file
        super().do_GET()

# Ensure files exist
for f in ALLOWED_FILES:
    if not os.path.exists(f):
        raise FileNotFoundError(f"{f} not found in current directory")

httpd = http.server.HTTPServer(("0.0.0.0", PORT), MultiFileHandler)

# SSL using modern SSLContext
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile="server.crt", keyfile="server.key")
httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

print(f"Serving HTTPS on port {PORT} (only {', '.join(ALLOWED_FILES)})...")
httpd.serve_forever()

#!/usr/bin/env python3
"""
Simple HTTP server to serve the example reference data locally for testing
and demonstration of remote URL retrieval.

Usage:
    python serve_reference.py [port]
"""

import http.server
from pathlib import Path
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
DIRECTORY = Path(__file__).resolve().parent / "reference_data"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)


def main():
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"[*] Serving reference data from '{DIRECTORY}' at http://127.0.0.1:{PORT}/")
        print("[*] Press Ctrl+C to terminate.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[*] Server stopped.")


if __name__ == "__main__":
    main()

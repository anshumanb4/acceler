#!/usr/bin/env python3
"""Warmline local API server — runs agents in background from the dashboard."""

import http.server
import json
import os
import subprocess
import sys
import threading

PORT = 8788
AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Shared state
_proc = None
_output_lines = []
_agent_name = None
_lock = threading.Lock()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        global _proc, _agent_name
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/run":
            agent = body.get("agent", "enrich")
            args = body.get("args", [])

            with _lock:
                if _proc and _proc.poll() is None:
                    self._json(409, {"error": "Agent already running", "agent": _agent_name})
                    return

                cmd = [sys.executable, f"{agent}.py"] + args
                _proc = subprocess.Popen(
                    cmd,
                    cwd=AGENTS_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                _output_lines.clear()
                _agent_name = agent

                def reader():
                    for line in _proc.stdout:
                        stripped = line.rstrip()
                        print(f"[{agent}] {stripped}", flush=True)
                        with _lock:
                            _output_lines.append(stripped)

                threading.Thread(target=reader, daemon=True).start()

            self._json(200, {"status": "started", "agent": agent})
        else:
            self._json(404, {"error": "Not found"})

    def do_GET(self):
        if self.path == "/status":
            with _lock:
                running = _proc is not None and _proc.poll() is None
                exit_code = _proc.returncode if _proc and not running else None
                lines = list(_output_lines[-100:])
            self._json(
                200,
                {
                    "running": running,
                    "agent": _agent_name,
                    "exit_code": exit_code,
                    "output": lines,
                },
            )
        else:
            self._json(404, {"error": "Not found"})

    def _json(self, code, data):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        pass  # Suppress per-request logs


if __name__ == "__main__":
    print(f"Warmline agent server on http://localhost:{PORT}")
    server = http.server.HTTPServer(("", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

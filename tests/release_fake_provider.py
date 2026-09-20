"""Disposable CI Responses server. Never imported by production code.

Runs across container recreations; an event pauses module calls so the probe can
send real SIGTERM while a provider request is in flight. No external network.
"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from app.marketing_copilot.contracts import IntentKind
from tests.test_copilot_application import intent_model
from tests.test_strategy_builder import StrategyModel

lock = threading.Lock()
release = threading.Event()
state = {"module_calls": 0, "waiting": 0, "hold_after": 2}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # No request/prompt/body logs, including fake traffic.

    def reply(self, value):
        raw = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Killed worker abandoned its response.

    def do_GET(self):
        with lock:
            result = dict(state)
        self.reply(result)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/release":
            release.set()
            self.reply({"released": True})
            return
        schema = body["text"]["format"]["schema"]
        if "kind" in schema["properties"]:
            output = asyncio.run(intent_model(IntentKind.MARKETING_STRATEGY)())
        else:
            with lock:
                state["module_calls"] += 1
                hold = state["module_calls"] >= state["hold_after"] and not release.is_set()
                if hold:
                    state["waiting"] += 1
            if hold:
                if not release.wait(timeout=120):
                    self.send_error(503)
                    return
                with lock:
                    state["waiting"] -= 1
            output = asyncio.run(StrategyModel(use_parents=True)(instruction=body["input"][0]["content"],
                text=body["input"][1]["content"], response_schema=schema))
        self.reply({"status": "completed", "output_text": output})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()

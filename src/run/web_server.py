from flask import Flask, Response, send_from_directory
import os
import json
import time
from config import BASE_DIR
from state import AppState

class WebServer:
    def __init__(self):
        self.app = Flask(__name__)
        self.app_state = AppState.get_instance()
        self._setup_routes()

    def _setup_routes(self):
        self.app.add_url_rule('/', 'index', self.index)
        self.app.add_url_rule('/stream', 'stream', self.stream)

    def index(self):
        return send_from_directory(os.path.join(BASE_DIR, 'ui'), 'index.html')

    def stream(self):
        return Response(self._generate_events(), mimetype="text/event-stream")

    def _generate_events(self):
        stats = self.app_state.stats
        last_sent = {}
        
        while True:
            # Include advice, advice_status, and humidity in the change tracking
            for key in ["count", "similarity", "is_moving", "mode", "advice", "advice_status", "humidity"]:
                if stats.get(key) != last_sent.get(key):
                    yield f"data: {json.dumps({'type': 'update', **stats})}\n\n"
                    last_sent = stats.copy()
                    break
            time.sleep(0.1)

    def run(self):
        self.app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)

def run_flask_server():
    server = WebServer()
    server.run()

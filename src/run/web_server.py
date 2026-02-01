from flask import Flask, Response, send_from_directory
import os
import json
import time
from config import BASE_DIR, GRAPH_DIR
from state import AppState

class WebServer:
    def __init__(self):
        self.app = Flask(__name__)
        self.app_state = AppState.get_instance()
        self._setup_routes()

    def _setup_routes(self):
        self.app.add_url_rule('/', 'index', self.index)
        self.app.add_url_rule('/stream', 'stream', self.stream)
        self.app.add_url_rule('/connect_dumbbell', 'connect_dumbbell', self.connect_dumbbell, methods=['POST'])
        self.app.add_url_rule('/graph/<path:filename>', 'get_graph', self.get_graph)

    def index(self):
        return send_from_directory(os.path.join(BASE_DIR, 'ui'), 'index.html')

    def stream(self):
        return Response(self._generate_events(), mimetype="text/event-stream")

    def get_graph(self, filename):
        return send_from_directory(GRAPH_DIR, filename)

    def connect_dumbbell(self):
        print("\n[WEB] '아령 연결하기' 버튼 클릭됨! 아령 연결을 허용합니다.")
        self.app_state.stats["allow_dumbbell"] = True
        self.app_state.stats["connection_phase"] = "WAITING_DUMBBELL"
        return {"status": "success", "message": "Dumbbell connection allowed"}

    def _generate_events(self):
        stats = self.app_state.stats
        last_sent = {}
        
        while True:
            # Include advice, advice_status, humidity, and latest_graph in the change tracking
            for key in ["count", "similarity", "is_moving", "mode", "advice", "advice_status", "humidity", "connection_phase", "is_set_active", "set_count", "latest_graph"]:
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

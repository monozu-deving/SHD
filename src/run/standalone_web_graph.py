from flask import Flask, Response, send_from_directory
import os
import socket
import threading
import time
import json
import collections
from config import HOST, PORT

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI_DIR = os.path.join(BASE_DIR, 'ui')

app = Flask(__name__)

# Global Data Buffer
data_lock = threading.Lock()
# Store last known values to send to client
current_data = {
    "ax": 0, "ay": 0, "az": 0,
    "timestamp": 0
}

is_running = True

def socket_server_thread():
    """
    Runs a socket server to receive data from the ESP32/Dumbbell.
    """
    global is_running
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, PORT))
        except OSError as e:
            print(f"Error binding to {HOST}:{PORT}: {e}")
            is_running = False
            return

        s.listen(1)
        print(f"Socket Server listening on {HOST}:{PORT}...")

        conn = None
        raw_buf = b""
        
        try:
            while is_running:
                # Accept connection
                if conn is None:
                    s.settimeout(1.0)
                    try:
                        conn, addr = s.accept()
                        print(f">>> Device connected: {addr}")
                        conn.settimeout(10.0)
                    except socket.timeout:
                        continue
                    except Exception as e:
                        print(f"Accept error: {e}")
                        continue
                
                # Receive data
                try:
                    data = conn.recv(4096)
                    if not data:
                        print(">>> Connection closed by device.")
                        conn.close()
                        conn = None
                        continue
                    
                    raw_buf += data
                    
                    while b"\n" in raw_buf:
                        line_bytes, raw_buf = raw_buf.split(b"\n", 1)
                        line = line_bytes.decode(errors="ignore").strip()
                        if not line: continue
                        
                        parts = line.split(",")
                        if len(parts) >= 3: # Expecting at least ax,ay,az
                            try:
                                val_ax = int(parts[0])
                                val_ay = int(parts[1])
                                val_az = int(parts[2])
                                
                                with data_lock:
                                    current_data["ax"] = val_ax
                                    current_data["ay"] = val_ay
                                    current_data["az"] = val_az
                                    current_data["timestamp"] = time.time()
                                    
                            except ValueError:
                                pass
                                
                except socket.timeout:
                    # Keep connection alive, just check loop
                    continue
                except Exception as e:
                    print(f"Socket error: {e}")
                    if conn:
                        conn.close()
                        conn = None

        except Exception as e:
            print(f"Server loop error: {e}")
        finally:
            if conn:
                conn.close()
            print("Socket server stopped.")

@app.route('/')
def index():
    return send_from_directory(UI_DIR, 'graph.html')

@app.route('/stream')
def stream():
    def generate():
        last_ts = 0
        while True:
            with data_lock:
                # If we have new data
                if current_data["timestamp"] > last_ts:
                    json_data = json.dumps(current_data)
                    yield f"data: {json_data}\n\n"
                    last_ts = current_data["timestamp"]
            
            time.sleep(0.02) # Check at 50Hz
            
    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    # Start socket server
    t = threading.Thread(target=socket_server_thread, daemon=True)
    t.start()
    
    print("="*60)
    print("Web Grapher running at http://localhost:5000")
    print("="*60)
    
    # Run Flask
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

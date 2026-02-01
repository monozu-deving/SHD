import threading
import socket
from config import HOST, PORT
from web_server import WebServer
from device_handler import DeviceHandler

class DumbbellApp:
    def __init__(self):
        self.host = HOST
        self.port = PORT

    def start_web_server(self):
        web_server = WebServer()
        web_thread = threading.Thread(target=web_server.run, daemon=True)
        web_thread.start()
        print("="*60)
        print("Web UI available at http://localhost")
        print("="*60)

    def print_usage(self):
        print("\nButton Controls (Arduino toggle button):")
        print("  1st press (ON):  Start EXPERT recording")
        print("           Keep button ON and perform the movement")
        print("  2nd press (OFF): End EXPERT recording & save")
        print("  3rd press (ON):  Start COUNTING mode")
        print("  4th+ press:      Continue counting or toggle off")
        print("="*60)

    def run(self):
        self.start_web_server()
        self.print_usage()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen(5) # Support multiple connections
            
            while True:
                print("\nWaiting for device connections...")
                conn, addr = s.accept()
                print(f">>> New connection accepted from: {addr}")
                
                # Start a new thread for each connection
                handler = DeviceHandler(conn, addr)
                threading.Thread(target=handler.run, daemon=True).start()

if __name__ == "__main__":
    app = DumbbellApp()
    app.run()

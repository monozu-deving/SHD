import threading
import socket
import time
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

        from state import AppState
        app_state = AppState.get_instance()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen(5)
            
            # Phase 1: Wait for ENV sensor connection
            print("\n" + "="*60)
            print("온습도 센서 연결 대기 중...")
            print("온습도 센서의 전원을 켜주세요")
            print("="*60)
            
            # Reset all flags for new session
            app_state.ai_advice_triggered = False
            app_state.ai_advice_completed = False
            app_state.stats["allow_dumbbell"] = False
            app_state.stats["connection_phase"] = "WAITING_ENV"
            
            conn, addr = s.accept()
            print(f">>> 온습도 센서 연결됨: {addr[0]}:{addr[1]}")
            
            # Handle ENV sensor
            handler = DeviceHandler(conn, addr, is_env_only=True)
            env_thread = threading.Thread(target=handler.run, daemon=True)
            env_thread.start()
            
            # Wait for ENV sensor to finish (it will auto-disconnect)
            env_thread.join()
            
            # Phase 2: Prompt user
            print("\n" + "="*60)
            print("온습도 센서 연결 완료!")
            print("="*60)
            print("\n이제 온습도 센서 전원을 끄고")
            print("아령 기기의 전원을 켜주세요")
            print("웹 UI에서 '아령 연결' 버튼을 눌러주세요")
            print("="*60 + "\n")
            
            app_state.stats["connection_phase"] = "ENV_DONE"
            
            # Phase 3: Wait for button press
            print(">>> 웹 UI에서 버튼 클릭을 기다리는 중...")
            while not app_state.stats["allow_dumbbell"]:
                time.sleep(0.5)
            
            print("\n" + "="*60)
            print("아령 기기 연결 대기 중...")
            print("="*60)
            
            while True:
                try:
                    # Accept dumbbell connection
                    conn, addr = s.accept()
                    print(f">>> 아령 기기 연결됨: {addr[0]}:{addr[1]}")
                    app_state.stats["connection_phase"] = "DUMBBELL_CONNECTED"
                    
                    # Handle dumbbell - this will run indefinitely unless disconnected
                    # 명시적으로 is_env_only=False 설정
                    handler = DeviceHandler(conn, addr, is_env_only=False)
                    handler.run()
                    
                    print("\n>>> 기기 연결이 종료되었습니다. 다음 연결을 기다립니다...")
                    app_state.stats["connection_phase"] = "ENV_DONE"
                    app_state.stats["allow_dumbbell"] = True # Keep allowed for retry
                    
                except Exception as e:
                    import traceback
                    print(f"\n[ERROR] 아령 처리 중 오류 발생: {e}")
                    traceback.print_exc()
                    print(">>> 5초 후 다시 대기합니다...")
                    time.sleep(5)

if __name__ == "__main__":
    try:
        app = DumbbellApp()
        app.run()
    except Exception as e:
        import traceback
        print(f"\n[FATAL ERROR] 프로그램 실행 중 치명적 오류 발생: {e}")
        traceback.print_exc()
        input("\n엔터 키를 누르면 종료합니다...")

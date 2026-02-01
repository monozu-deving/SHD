import socket
import time
import random
import math
from config import HOST, PORT

def run_mock_sender():
    print(f"Connecting to {HOST}:{PORT}...")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOST, PORT))
            print("Connected! Sending mock data...")
            
            t = 0
            while True:
                # Simulate sine waves for accel
                ax = int(10000 * math.sin(t * 0.1) + random.randint(-500, 500))
                ay = int(10000 * math.cos(t * 0.1) + random.randint(-500, 500))
                az = int(5000 + random.randint(-100, 100)) # Gravity offset
                
                # Mock Gyro (not used by grapher but part of protocol)
                gx, gy, gz = 0, 0, 0
                
                # Format: "ax,ay,az,gx,gy,gz"
                message = f"{ax},{ay},{az},{gx},{gy},{gz}\n"
                s.sendall(message.encode())
                
                time.sleep(0.05) # 20Hz ~ 50ms
                t += 1
                
                if t % 20 == 0:
                    print(f"Sent: {message.strip()}")

    except ConnectionRefusedError:
        print("Connection refused. Make sure `standalone_accel_graph.py` is running first.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_mock_sender()

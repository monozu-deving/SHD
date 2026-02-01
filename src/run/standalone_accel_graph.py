import socket
import threading
import time
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from config import HOST, PORT

# Configuration
WINDOW_SIZE = 200  # Number of samples to show on graph
UPDATE_INTERVAL = 50  # Plot update interval in ms

# Global Data Buffer
data_lock = threading.Lock()
ax_buf = collections.deque(maxlen=WINDOW_SIZE)
ay_buf = collections.deque(maxlen=WINDOW_SIZE)
az_buf = collections.deque(maxlen=WINDOW_SIZE)

# Global State
is_running = True

def socket_server_thread():
    """
    Runs a socket server that mimics the logic in device_handler.py/dumbell.py
    to receive data from the ESP32/Dumbbell.
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
        print(f"Waiting for connection on {HOST}:{PORT}...")

        conn = None
        raw_buf = b""
        
        try:
            while is_running:
                # Accept connection
                if conn is None:
                    s.settimeout(1.0)
                    try:
                        conn, addr = s.accept()
                        print(f"Connected by {addr}")
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
                        print("Connection closed by device.")
                        conn.close()
                        conn = None
                        continue
                    
                    raw_buf += data
                    
                    # Process lines similar to device_handler.py
                    while b"\n" in raw_buf:
                        line_bytes, raw_buf = raw_buf.split(b"\n", 1)
                        line = line_bytes.decode(errors="ignore").strip()
                        if not line: continue
                        
                        # Data format logic from device_handler.py
                        # We ignore "ENV:" and "TEMP:" for this grapher, focused on Accel
                        # "ax, ay, az, gx, gy, gz"
                        
                        parts = line.split(",")
                        if len(parts) >= 6:
                            try:
                                val_ax = int(parts[0])
                                val_ay = int(parts[1])
                                val_az = int(parts[2])
                                
                                with data_lock:
                                    ax_buf.append(val_ax)
                                    ay_buf.append(val_ay)
                                    az_buf.append(val_az)
                            except ValueError:
                                pass
                                
                except socket.timeout:
                    print("Socket timeout (no data).")
                    if conn:
                        conn.close()
                        conn = None
                except Exception as e:
                    print(f"Socket error: {e}")
                    if conn:
                        conn.close()
                        conn = None

        except KeyboardInterrupt:
            # Main thread will handle this mostly, but good to have
            pass
        finally:
            if conn:
                conn.close()
            print("Socket server stopped.")

def run_grapher():
    """
    Main thread function for Matplotlib visualization.
    """
    # Initialize buffers with zeros for clean startup
    with data_lock:
        for _ in range(WINDOW_SIZE):
            ax_buf.append(0)
            ay_buf.append(0)
            az_buf.append(0)

    fig = plt.figure(figsize=(10, 6))
    ax = fig.add_subplot(1, 1, 1)
    
    # Lines
    line_x, = ax.plot([], [], 'r-', label='AX', alpha=0.8)
    line_y, = ax.plot([], [], 'g-', label='AY', alpha=0.8)
    line_z, = ax.plot([], [], 'b-', label='AZ', alpha=0.8)
    
    ax.set_title(f"Real-time Acceleration ({HOST}:{PORT})")
    ax.set_ylim(-30000, 30000) # Typical MPU6050 raw range, adjust if needed
    ax.set_xlim(0, WINDOW_SIZE)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right')

    x_data = list(range(WINDOW_SIZE))

    def update(frame):
        with data_lock:
            y_ax = list(ax_buf)
            y_ay = list(ay_buf)
            y_az = list(az_buf)
        
        line_x.set_data(x_data, y_ax)
        line_y.set_data(x_data, y_ay)
        line_z.set_data(x_data, y_az)
        
        # Dynamic Y-axis adjustment (optional, capable of auto-scaling)
        # current_min = min(min(y_ax), min(y_ay), min(y_az))
        # current_max = max(max(y_ax), max(y_ay), max(y_az))
        # ax.set_ylim(current_min - 1000, current_max + 1000)

        return line_x, line_y, line_z

    # Use a simpler update mechanism without blit for better stability on Windows/TkInter
    ani = animation.FuncAnimation(fig, update, interval=UPDATE_INTERVAL, blit=False, cache_frame_data=False)
    
    # Handle window close
    def on_close(event):
        global is_running
        print("Window closed, stopping server...")
        is_running = False
        
    fig.canvas.mpl_connect('close_event', on_close)

    print("Starting Grapher... Close the plot window to exit.")
    try:
        plt.show()
    except Exception as e:
        print(f"Plot error: {e}")
        is_running = False

if __name__ == "__main__":
    # Start socket server in a separate daemon thread
    t = threading.Thread(target=socket_server_thread, daemon=True)
    t.start()
    
    try:
        run_grapher()
    except KeyboardInterrupt:
        is_running = False
        print("\nInterrupted by user.")

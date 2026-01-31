import socket
import time
import json
import os
import threading
from datetime import datetime
from flask import Flask, Response, send_from_directory
import matplotlib.pyplot as plt
import math

# --- CONFIGURATION ---
HOST = "0.0.0.0"
PORT = 5000
REFERENCE_FILE = "reference_data.json"
MAX_SAMPLES = 5000

# Movement Detection Params
THRESHOLD = 3000
STILL_TIME_LIMIT = 1.5
MIN_MOVEMENT_SAMPLES = 15  # Lowered for single rep expert

# Flask App for Web UI
app = Flask(__name__)
stats = {
    "count": 0,
    "similarity": 0,
    "is_moving": False,
    "mode": "IDLE",
    "current_distribution": [],
    "expert_distribution": []
}

# Global state
button_press_count = 0

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/stream')
def stream():
    return Response(generate_events(), mimetype="text/event-stream")

def generate_events():
    global stats
    last_sent = {}
    
    while True:
        for key in ["count", "similarity", "is_moving", "mode"]:
            if stats.get(key) != last_sent.get(key):
                yield f"data: {json.dumps({'type': 'update', **stats})}\n\n"
                last_sent = stats.copy()
                break
        time.sleep(0.1)

def run_flask():
    app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)

# --- LOGIC ---

def extract_movement_segment(ax_list, ay_list, az_list):
    """Extract only the active movement portion by detecting where values change"""
    if len(ax_list) < 10:
        return ax_list, ay_list, az_list
    
    # Calculate absolute differences between consecutive samples
    changes = []
    for i in range(1, len(ax_list)):
        diff_ax = abs(ax_list[i] - ax_list[i-1])
        diff_ay = abs(ay_list[i] - ay_list[i-1])
        diff_az = abs(az_list[i] - az_list[i-1])
        total_change = diff_ax + diff_ay + diff_az
        changes.append(total_change)
    
    if not changes:
        return ax_list, ay_list, az_list
    
    # Find threshold - use a small value to detect any change
    max_change = max(changes)
    avg_change = sum(changes) / len(changes)
    CHANGE_THRESHOLD = max(10, avg_change * 0.5)  # Very sensitive to changes
    
    print(f">>> Change analysis: max={max_change:.0f}, avg={avg_change:.0f}, threshold={CHANGE_THRESHOLD:.0f}")
    
    # Find first significant change (movement start)
    start_idx = 0
    for i, change in enumerate(changes):
        if change > CHANGE_THRESHOLD:
            start_idx = max(0, i - 1)  # Include one sample before
            break
    
    # Find last significant change (movement end)
    end_idx = len(ax_list)
    for i in range(len(changes) - 1, -1, -1):
        if changes[i] > CHANGE_THRESHOLD:
            end_idx = min(len(ax_list), i + 3)  # Include a couple samples after
            break
    
    trimmed_len = end_idx - start_idx
    print(f">>> Trimmed: {len(ax_list)} -> {trimmed_len} samples (start={start_idx}, end={end_idx})")
    
    return ax_list[start_idx:end_idx], ay_list[start_idx:end_idx], az_list[start_idx:end_idx]

def calculate_similarity(ref_list, cur_list):
    if not ref_list or not cur_list: return 0.0
    n_ref = len(ref_list)
    n_cur = len(cur_list)
    if n_cur < 10: return 0.0
    
    resampled_cur = []
    for i in range(n_ref):
        pos = i * (n_cur - 1) / (n_ref - 1) if n_ref > 1 else 0
        idx, frac = int(pos), pos - int(pos)
        if idx >= n_cur - 1: val = cur_list[-1]
        else: val = cur_list[idx] * (1 - frac) + cur_list[idx + 1] * frac
        resampled_cur.append(val)

    diff_sum = sum(abs(r - c) for r, c in zip(ref_list, resampled_cur))
    ref_range = max(max(ref_list) - min(ref_list), 1000)
    max_diff = ref_range * n_ref
    
    sim = max(0, 100 * (1 - (diff_sum / max_diff)))
    return sim

def save_movement_graph(ax_list, ay_list, az_list, movement_num, similarity=None):
    if len(ax_list) < 10: return
    
    plt.figure(figsize=(12, 6))
    
    if similarity is not None and os.path.exists(REFERENCE_FILE):
        with open(REFERENCE_FILE, "r") as f:
            ref_data = json.load(f)
        
        plt.subplot(1, 2, 1)
        plt.plot(ref_data["ax"], 'r--', alpha=0.5, label="ax (Expert)")
        plt.plot(ref_data["ay"], 'g--', alpha=0.5, label="ay (Expert)")
        plt.plot(ref_data["az"], 'b--', alpha=0.5, label="az (Expert)")
        plt.title("Expert Movement")
        plt.xlabel("Sample")
        plt.ylabel("Raw Value")
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        plt.subplot(1, 2, 2)
        plt.plot(ax_list, 'r-', label="ax (Current)")
        plt.plot(ay_list, 'g-', label="ay (Current)")
        plt.plot(az_list, 'b-', label="az (Current)")
        plt.title(f"Rep #{movement_num} | Similarity: {similarity:.1f}%")
        plt.xlabel("Sample")
        plt.ylabel("Raw Value")
        plt.legend()
        plt.grid(True, alpha=0.3)
    else:
        plt.plot(ax_list, 'r-', label="ax")
        plt.plot(ay_list, 'g-', label="ay")
        plt.plot(az_list, 'b-', label="az")
        plt.title(f"Expert Movement")
        plt.xlabel("Sample")
        plt.ylabel("Raw Value")
        plt.legend()
        plt.grid(True, alpha=0.3)
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"movement_{movement_num}_{ts}.png"
    plt.tight_layout()
    plt.savefig(filename, dpi=150)
    plt.close()
    print(f">>> Graph saved: {filename}")

def handle_one_connection(conn, addr):
    global stats, button_press_count
    print(f"\n{'='*50}")
    print(f"Connection from {addr}")
    
    # Increment button press count on each new connection
    button_press_count += 1
    print(f">>> Button press count: {button_press_count}")
    
    # Determine mode based on button press count
    if button_press_count == 1:
        mode = "RECORDING_EXPERT"
        stats["mode"] = "RECORDING_EXPERT"
        print(">>> Mode: RECORDING EXPERT")
        print(">>> Perform the movement slowly and carefully, then press button again")
    else:  # button_press_count >= 2
        mode = "COUNTING"
        stats["mode"] = "COUNTING"
        if button_press_count == 2:
            stats["count"] = 0
            stats["similarity"] = 0
        print(">>> Mode: COUNTING")
    
    # Buffers
    expert_ax, expert_ay, expert_az = [], [], []
    current_ax, current_ay, current_az = [], [], []
    
    # Movement detection
    is_moving = False
    still_start_time = None
    recent_magnitudes = []
    WINDOW_SIZE = 10
    
    raw_buf = b""
    conn.settimeout(2.0)
    last_rx = time.time()

    while True:
        try:
            data = conn.recv(4096)
            if not data:
                print(">>> Connection closed (button toggled OFF)")
                break
            last_rx = time.time()
            raw_buf += data
        except socket.timeout:
            if time.time() - last_rx > 5:
                print(">>> No data timeout")
                break
            continue
        except Exception as e:
            print(f">>> Recv error: {e}")
            break

        while b"\n" in raw_buf:
            line_bytes, raw_buf = raw_buf.split(b"\n", 1)
            line = line_bytes.decode(errors="ignore").strip()
            if not line: continue
            
            # Parse sensor data
            try:
                parts = line.split(",")
                if len(parts) < 6: continue  # Need all 6 values
                ax, ay, az, gx, gy, gz = map(int, parts[:6])
                
                # Mode-specific handling
                if mode == "RECORDING_EXPERT":
                    expert_ax.append(ax)
                    expert_ay.append(ay)
                    expert_az.append(az)
                    if len(expert_ax) % 100 == 0:
                        print(f">>> Recording expert: {len(expert_ax)} samples")
                
                elif mode == "COUNTING":
                    # Movement detection
                    mag = math.sqrt(ax**2 + ay**2 + az**2)
                    recent_magnitudes.append(mag)
                    if len(recent_magnitudes) > WINDOW_SIZE:
                        recent_magnitudes.pop(0)
                    
                    if len(recent_magnitudes) >= WINDOW_SIZE:
                        avg_mag = sum(recent_magnitudes) / len(recent_magnitudes)
                        variance = sum((m - avg_mag)**2 for m in recent_magnitudes) / len(recent_magnitudes)
                        
                        if variance > THRESHOLD:
                            if not is_moving:
                                is_moving = True
                                current_ax, current_ay, current_az = [], [], []
                                stats["is_moving"] = True
                                print(">>> Movement STARTED")
                            still_start_time = None
                        else:
                            if is_moving:
                                if still_start_time is None:
                                    still_start_time = time.time()
                                elif time.time() - still_start_time > STILL_TIME_LIMIT:
                                    is_moving = False
                                    stats["is_moving"] = False
                                    print(f">>> Movement ENDED ({len(current_ax)} samples)")
                                    
                                    # Process movement
                                    if len(current_ax) >= MIN_MOVEMENT_SAMPLES and os.path.exists(REFERENCE_FILE):
                                        with open(REFERENCE_FILE, "r") as f:
                                            ref_data = json.load(f)
                                        
                                        # Trim current movement
                                        trimmed_ax, trimmed_ay, trimmed_az = extract_movement_segment(
                                            current_ax, current_ay, current_az
                                        )
                                        
                                        s1 = calculate_similarity(ref_data["ax"], trimmed_ax)
                                        s2 = calculate_similarity(ref_data["ay"], trimmed_ay)
                                        s3 = calculate_similarity(ref_data["az"], trimmed_az)
                                        avg_sim = (s1 + s2 + s3) / 3.0
                                        
                                        stats["count"] += 1
                                        stats["similarity"] = avg_sim
                                        print(f">>> Rep #{stats['count']} | Similarity: {avg_sim:.1f}%")
                                        save_movement_graph(trimmed_ax, trimmed_ay, trimmed_az, stats["count"], avg_sim)
                                        
                                        # Clear distribution after movement ends
                                        stats["current_distribution"] = []
                                    
                                    current_ax, current_ay, current_az = [], [], []
                                    still_start_time = None
                    
                    if is_moving:
                        current_ax.append(ax)
                        current_ay.append(ay)
                        current_az.append(az)
                        
                        # Update real-time distribution (sample every 5th point to reduce data)
                        if len(current_ax) % 5 == 0:
                            # Calculate magnitude distribution
                            current_mags = [math.sqrt(a**2 + b**2 + c**2) for a, b, c in zip(current_ax, current_ay, current_az)]
                            stats["current_distribution"] = current_mags[-50:]  # Last 50 samples
                            
                            # Load expert distribution
                            if os.path.exists(REFERENCE_FILE):
                                with open(REFERENCE_FILE, "r") as f:
                                    ref_data = json.load(f)
                                expert_mags = [math.sqrt(a**2 + b**2 + c**2) for a, b, c in zip(ref_data["ax"], ref_data["ay"], ref_data["az"])]
                                stats["expert_distribution"] = expert_mags
                        
            except Exception as e:
                continue
    
    # Connection ended - save expert if in recording mode
    if mode == "RECORDING_EXPERT":
        if len(expert_ax) >= MIN_MOVEMENT_SAMPLES:
            # Extract only the movement portion
            trimmed_ax, trimmed_ay, trimmed_az = extract_movement_segment(expert_ax, expert_ay, expert_az)
            
            if len(trimmed_ax) >= MIN_MOVEMENT_SAMPLES:
                ref_data = {"ax": trimmed_ax, "ay": trimmed_ay, "az": trimmed_az}
                with open(REFERENCE_FILE, "w") as f:
                    json.dump(ref_data, f)
                save_movement_graph(trimmed_ax, trimmed_ay, trimmed_az, 0)
                print(f">>> EXPERT saved ({len(trimmed_ax)} samples)")
                print(f">>> Press button again to start COUNTING mode")
                stats["mode"] = "READY"
            else:
                print(f">>> EXPERT trimmed too short ({len(trimmed_ax)} samples)")
                print(f">>> Please record a longer movement with actual motion")
                stats["mode"] = "IDLE"
                button_press_count = 0  # Reset to try again
        else:
            print(f">>> EXPERT too short ({len(expert_ax)} samples)")
            print(f">>> Please hold the button longer and perform the movement")
            stats["mode"] = "IDLE"
            button_press_count = 0  # Reset to try again
    
    print(f"{'='*50}\n")

def main():
    global button_press_count
    threading.Thread(target=run_flask, daemon=True).start()
    print("="*60)
    print("Web UI available at http://localhost")
    print("="*60)
    print("\nButton Controls (Arduino toggle button):")
    print("  1st press (ON):  Start EXPERT recording")
    print("           Keep button ON and perform the movement")
    print("  2nd press (OFF): End EXPERT recording & save")
    print("  3rd press (ON):  Start COUNTING mode")
    print("  4th+ press:      Continue counting or toggle off")
    print("="*60)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(1)
        while True:
            print("\nWaiting for Arduino connection...")
            conn, addr = s.accept()
            with conn:
                handle_one_connection(conn, addr)

if __name__ == "__main__":
    main()

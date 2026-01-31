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
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOST = "0.0.0.0"
PORT = 5000
REFERENCE_FILE = os.path.join(BASE_DIR, "calibration", "reference_data.json")
CALIBRATION_FILE = os.path.join(BASE_DIR, "calibration", "baseline.json")
GRAPH_DIR = os.path.join(BASE_DIR, "graph")
MAX_SAMPLES = 5000

# Movement Detection Params
THRESHOLD = 3000
STILL_TIME_LIMIT = 0.7
MIN_MOVEMENT_SAMPLES = 5
CALIBRATION_TIME = 5.0
THRESHOLD_PERCENT = 0.05
MIN_ABS_DIFF = 300

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
    return send_from_directory(os.path.join(BASE_DIR, 'ui'), 'index.html')

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

def extract_movement_segment(ax_list, ay_list, az_list, baseline):
    """Extract active movement portion using baseline values and thresholds"""
    if not baseline or len(ax_list) < MIN_MOVEMENT_SAMPLES:
        return ax_list, ay_list, az_list
    
    start_idx = -1
    end_idx = -1
    
    for i in range(len(ax_list)):
        diff_x = abs(ax_list[i] - baseline["ax"])
        diff_y = abs(ay_list[i] - baseline["ay"])
        diff_z = abs(az_list[i] - baseline["az"])
        
        thresh_x = max(abs(baseline["ax"]) * THRESHOLD_PERCENT, MIN_ABS_DIFF)
        thresh_y = max(abs(baseline["ay"]) * THRESHOLD_PERCENT, MIN_ABS_DIFF)
        thresh_z = max(abs(baseline["az"]) * THRESHOLD_PERCENT, MIN_ABS_DIFF)

        if diff_x > thresh_x or diff_y > thresh_y or diff_z > thresh_z:
            if start_idx == -1:
                start_idx = i
            end_idx = i
            
    if start_idx != -1 and end_idx != -1:
        trimmed_len = end_idx - start_idx + 1
        if trimmed_len >= MIN_MOVEMENT_SAMPLES:
            print(f">>> Valid segment found: {len(ax_list)} -> {trimmed_len} samples (range: {start_idx}-{end_idx})")
            return ax_list[start_idx:end_idx+1], ay_list[start_idx:end_idx+1], az_list[start_idx:end_idx+1]
        else:
            print(f">>> Segment too short: {trimmed_len} samples (need {MIN_MOVEMENT_SAMPLES})")
    else:
        # Calculate max diff for debugging
        max_dx = max([abs(x - baseline["ax"]) for x in ax_list]) if ax_list else 0
        max_dy = max([abs(y - baseline["ay"]) for y in ay_list]) if ay_list else 0
        max_dz = max([abs(z - baseline["az"]) for z in az_list]) if az_list else 0
        print(f">>> No movement! Max diffs - X:{max_dx:.0f}, Y:{max_dy:.0f}, Z:{max_dz:.0f} (Threshold: {MIN_ABS_DIFF})")
    
    return [], [], []

def calculate_similarity(ref_list, cur_list):
    if not ref_list or not cur_list: return 0.0
    n_ref = len(ref_list)
    n_cur = len(cur_list)
    if n_cur < 5: return 0.0
    
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

def process_rep(ax_buf, ay_buf, az_buf, baseline, ref_data, stats, session_reps=None):
    """Processes a single movement rep: trim, count, and buffer for later analysis"""
    trimmed_ax, trimmed_ay, trimmed_az = extract_movement_segment(
        ax_buf, ay_buf, az_buf, baseline
    )
    
    if trimmed_ax:
        stats["count"] += 1
        print(f">>> Rep #{stats['count']} detected!")
        
        if session_reps is not None:
            session_reps.append((trimmed_ax, trimmed_ay, trimmed_az))
        
        # In real-time, we just show count. Similarity is calculated at the end.
        stats["similarity"] = 0 
        
        # Clear distribution after movement ends
        stats["current_distribution"] = []
        return True
    return False

def finalize_session(session_reps, ref_data, stats):
    """Calculates final report at the end of the session"""
    if not session_reps or not ref_data:
        print("\n>>> Session ended. No reps to analyze.")
        return

    print("\n" + "="*50)
    print(f" FINAL SESSION REPORT (Total Reps: {len(session_reps)})")
    print("="*50)
    
    total_sim = 0
    for i, (ax, ay, az) in enumerate(session_reps):
        s1 = calculate_similarity(ref_data["ax"], ax)
        s2 = calculate_similarity(ref_data["ay"], ay)
        s3 = calculate_similarity(ref_data["az"], az)
        avg_sim = (s1 + s2 + s3) / 3.0
        total_sim += avg_sim
        print(f" Rep #{i+1:2d} | Accuracy: {avg_sim:5.1f}%")
        
        # Save the last rep's graph with its accuracy
        if i == len(session_reps) - 1:
            save_movement_graph(ax, ay, az, i+1, avg_sim)

    final_avg = total_sim / len(session_reps)
    stats["similarity"] = final_avg
    print("-" * 50)
    print(f" AVERAGE SESSION ACCURACY: {final_avg:.1f}%")
    print("="*50 + "\n")

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
    
    if movement_num == 0:
        filename = "expert_movement.png"
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"movement_{movement_num}_{ts}.png"
    
    filepath = os.path.join(GRAPH_DIR, filename)
    plt.tight_layout()
    plt.savefig(filepath, dpi=150)
    plt.close()
    print(f">>> Graph saved: {filepath}")

def save_calibration_graph(ax_list, ay_list, az_list, baseline):
    plt.figure(figsize=(10, 5))
    plt.plot(ax_list, 'r-', alpha=0.3, label="ax")
    plt.plot(ay_list, 'g-', alpha=0.3, label="ay")
    plt.plot(az_list, 'b-', alpha=0.3, label="az")
    plt.axhline(y=baseline["ax"], color='r', linestyle='--', label=f"Ref ax ({baseline['ax']:.0f})")
    plt.axhline(y=baseline["ay"], color='g', linestyle='--', label=f"Ref ay ({baseline['ay']:.0f})")
    plt.axhline(y=baseline["az"], color='b', linestyle='--', label=f"Ref az ({baseline['az']:.0f})")
    plt.title("Calibration Baseline (5 Seconds)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    filepath = os.path.join(GRAPH_DIR, "calibration_baseline.png")
    plt.savefig(filepath, dpi=150)
    plt.close()
    print(f">>> Calibration graph saved: {filepath}")

def handle_one_connection(conn, addr):
    global stats, button_press_count
    print(f"\n{'='*50}")
    print(f"Connection from {addr}")
    
    # Increment button press count on each new connection
    button_press_count += 1
    print(f">>> Button press count: {button_press_count}")
    
    # Determine mode based on button press count
    calibration_data = {"ax": [], "ay": [], "az": []}
    baseline = None
    calibration_start_time = None
    is_calibrated = False
    expert_started = False

    if button_press_count == 1:
        mode = "RECORDING_EXPERT"
        stats["mode"] = "CALIBRATING"
        calibration_start_time = time.time()
        print(f">>> Mode: {stats['mode']}")
        print(f">>> Hold STILL for {CALIBRATION_TIME} seconds for calibration...")
    else:  # button_press_count >= 2
        mode = "COUNTING"
        stats["mode"] = "COUNTING"
        if button_press_count == 2:
            stats["count"] = 0
            stats["similarity"] = 0
        if os.path.exists(CALIBRATION_FILE):
            with open(CALIBRATION_FILE, "r") as f:
                baseline = json.load(f)
            is_calibrated = True
        print(">>> Mode: COUNTING")
    
    # Buffers
    expert_ax, expert_ay, expert_az = [], [], []
    current_ax, current_ay, current_az = [], [], []
    session_reps = [] # To store all reps for final analysis
    
    # Movement detection
    is_moving = False
    still_start_time = None
    recent_magnitudes = []
    WINDOW_SIZE = 10
    
    # Expert Recording Buffers
    expert_buffer = {"ax": [], "ay": [], "az": []}
    
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
                if len(parts) < 6: continue  # Need 6 values (accel, gyro)
                ax, ay, az, gx, gy, gz = map(int, parts[:6])
                
                # Mode-specific handling
                if mode == "RECORDING_EXPERT":
                    if not is_calibrated:
                        if not calibration_start_time:
                            calibration_start_time = time.time()
                            stats["mode"] = "CALIBRATING"
                            print(">>> Connection established! Starting Calibration...")
                        
                        elapsed = time.time() - calibration_start_time
                        if elapsed < CALIBRATION_TIME:
                            calibration_data["ax"].append(ax)
                            calibration_data["ay"].append(ay)
                            calibration_data["az"].append(az)
                            if len(calibration_data["ax"]) % 50 == 0:
                                print(f">>> Calibrating... {elapsed:.1f}s / {CALIBRATION_TIME}s")
                        else:
                            # Calibration finished
                            baseline = {
                                "ax": sum(calibration_data["ax"]) / len(calibration_data["ax"]),
                                "ay": sum(calibration_data["ay"]) / len(calibration_data["ay"]),
                                "az": sum(calibration_data["az"]) / len(calibration_data["az"])
                            }
                            is_calibrated = True
                            save_calibration_graph(calibration_data["ax"], calibration_data["ay"], calibration_data["az"], baseline)
                            with open(CALIBRATION_FILE, "w") as f:
                                json.dump(baseline, f)
                            stats["mode"] = "READY_TO_RECORD"
                            print(f">>> Calibration DONE: {baseline}")
                            print(f">>> Perform movement, then press button again to STOP recording")
                    
                    else:
                        if not expert_started:
                            expert_started = True
                            stats["mode"] = "RECORDING_EXPERT"
                            print(">>> Expert recording STARTED! Perform your movement.")
                            print(">>> Press button again (disconnect) to STOP and SAVE.")
                        
                        expert_buffer["ax"].append(ax)
                        expert_buffer["ay"].append(ay)
                        expert_buffer["az"].append(az)
                        if len(expert_buffer["ax"]) % 100 == 0:
                            print(f">>> Buffering expert data: {len(expert_buffer['ax'])} samples")
                
                elif mode == "COUNTING":
                    # Movement detection
                    mag = math.sqrt(ax**2 + ay**2 + az**2)
                    recent_magnitudes.append(mag)
                    if len(recent_magnitudes) > WINDOW_SIZE:
                        recent_magnitudes.pop(0)

                    # Expert data reference for duration and profile
                    if os.path.exists(REFERENCE_FILE):
                        with open(REFERENCE_FILE, "r") as f:
                            ref_data = json.load(f)
                        expert_len = len(ref_data["ax"])
                    else:
                        expert_len = 0

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
                                    if len(current_ax) >= MIN_MOVEMENT_SAMPLES and expert_len > 0:
                                        process_rep(current_ax, current_ay, current_az, baseline, ref_data, stats, session_reps)
                                    
                                    current_ax, current_ay, current_az = [], [], []
                                    still_start_time = None
                    
                    if is_moving:
                        current_ax.append(ax)
                        current_ay.append(ay)
                        current_az.append(az)
                        
                        # Stop if we exceed 1.5x expert length (safety) or use STILL_TIME_LIMIT
                        if expert_len > 0 and len(current_ax) > expert_len * 1.5:
                            # If it keeps moving too long, we might need to force end or just let STILL_TIME_LIMIT handle
                            pass
                        
                        # Update real-time distribution (sample every 5th point to reduce data)
                        if len(current_ax) % 5 == 0:
                            current_mags = [math.sqrt(a**2 + b**2 + c**2) for a, b, c in zip(current_ax, current_ay, current_az)]
                            stats["current_distribution"] = current_mags[-50:]  # Last 50 samples
                            
                            if expert_len > 0:
                                expert_mags = [math.sqrt(a**2 + b**2 + c**2) for a, b, c in zip(ref_data["ax"], ref_data["ay"], ref_data["az"])]
                                stats["expert_distribution"] = expert_mags
                        
            except Exception as e:
                continue
    
    # Connection ended
    if mode == "COUNTING":
        if is_moving and len(current_ax) >= MIN_MOVEMENT_SAMPLES:
            print(">>> Capturing final rep before closure...")
            process_rep(current_ax, current_ay, current_az, baseline, ref_data, stats, session_reps)
        
        if os.path.exists(REFERENCE_FILE):
            with open(REFERENCE_FILE, "r") as f:
                ref_data = json.load(f)
            finalize_session(session_reps, ref_data, stats)

    # Connection ended - save expert if in recording mode
    if mode == "RECORDING_EXPERT" and is_calibrated:
        print(f">>> Connection closed. Processing {len(expert_buffer['ax'])} buffered samples...")
        
        # Trim using unified logic
        trimmed_ax, trimmed_ay, trimmed_az = extract_movement_segment(
            expert_buffer["ax"], expert_buffer["ay"], expert_buffer["az"], baseline
        )
        
        if len(trimmed_ax) >= MIN_MOVEMENT_SAMPLES: # If we have a valid trimmed movement
            
            ref_data = {"ax": trimmed_ax, "ay": trimmed_ay, "az": trimmed_az}
            with open(REFERENCE_FILE, "w") as f:
                json.dump(ref_data, f)
            save_movement_graph(trimmed_ax, trimmed_ay, trimmed_az, 0)
            
            print(f">>> EXPERT saved: {len(trimmed_ax)} samples (from {len(expert_buffer['ax'])} buffered)")
            stats["mode"] = "READY"
        else:
            print(f">>> EXPERT movement too subtle or short")
            stats["mode"] = "IDLE"
            button_press_count = 0
    
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

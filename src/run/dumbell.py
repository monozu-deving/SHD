import socket
import time
import json
import os
import threading
from datetime import datetime
from flask import Flask, Response, send_from_directory
import matplotlib.pyplot as plt
import math
from openai import OpenAI
from dotenv import load_dotenv

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(BASE_DIR, ".env"))
api_key = os.getenv("OPENAI_API_KEY")
client_ai = OpenAI(api_key=api_key) if api_key else None

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
    "expert_distribution": [],
    "advice": "",
    "advice_status": "",
    "humidity": 0
}

# AI Advice Control
ai_advice_triggered = False
ai_advice_completed = False

# Global state
# removed button_press_count

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
        # Include advice, advice_status, and humidity in the change tracking
        for key in ["count", "similarity", "is_moving", "mode", "advice", "advice_status", "humidity"]:
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

def process_rep(ax_buf, ay_buf, az_buf, stats, session_reps=None):
    """Simple activity burst counting: count any significant movement that stopped"""
    if len(ax_buf) >= MIN_MOVEMENT_SAMPLES:
        stats["count"] += 1
        print(f">>> Rep #{stats['count']} counted! (Movement stopped)")
        
        if session_reps is not None:
            # Store the raw burst for later analysis
            session_reps.append((list(ax_buf), list(ay_buf), list(az_buf)))
        
        stats["similarity"] = 0 
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
        # Trim each buffered rep before analysis
        t_ax, t_ay, t_az = extract_movement_segment(ax, ay, az, {"ax": ref_data["ax"][0], "ay": ref_data["ay"][0], "az": ref_data["az"][0]}) # approximation using ref start
        # Better: use the actual baseline or a dummy if not available
        if not t_ax: t_ax, t_ay, t_az = ax, ay, az # fallback if trim fails
        
        s1 = calculate_similarity(ref_data["ax"], t_ax)
        s2 = calculate_similarity(ref_data["ay"], t_ay)
        s3 = calculate_similarity(ref_data["az"], t_az)
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

def get_ai_advice(temperature, humidity=0):
    """Fetch exercise advice from GPT based on current temperature and humidity"""
    global stats
    try:
        if not client_ai:
            print(">>> Skipping AI advice: OPENAI_API_KEY is not set in .env")
            stats["advice_status"] = "❌ AI 설정 미흡"
            stats["advice"] = ".env 파일에 OpenAI API 키를 설정하면 스마트한 운동 조언을 받을 수 있습니다!"
            return

        stats["advice_status"] = f"🌡️ 온습도 수신 완료: {temperature:.1f}°C / {humidity}%"
        time.sleep(0.5) 
        
        print(f">>> Fetching AI advice for {temperature:.1f}C, {humidity}%...")
        stats["advice_status"] = "🧠 AI 전문 트레이너의 온습도 분석 중..."
        stats["advice"] = "AI 조언을 생성하고 있습니다..."
        
        response = client_ai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "너는 전문 헬스 트레이너야. 사용자의 현재 운동 환경 온도(Celsius)와 습도(%)를 보고, 해당 환경에서 운동할 때의 주의사항(부상 방지, 수분 섭취, 불쾌지수 등)과 덤벨 운동 팁을 딱 3문장 정도로 친절하고 전문적으로 말해줘."},
                {"role": "user", "content": f"현재 온도는 {temperature:.1f}도이고 습도는 {humidity}%야."}
            ],
            max_tokens=200
        )
        stats["advice"] = response.choices[0].message.content
        stats["advice_status"] = "✅ 맞춤 온습도 가이드 생성 완료!"
        print(f">>> AI Advice: {stats['advice']}")
        
        # Mark AI advice as completed
        global ai_advice_completed
        ai_advice_completed = True
    except Exception as e:
        print(f">>> AI Advice Error: {e}")
        stats["advice_status"] = "⚠️ AI 분석 중 오류 발생"
        stats["advice"] = "AI 조언을 가져오는 데 실패했습니다. 평소처럼 안전하게 운동하세요!"

def handle_one_connection(conn, addr):
    global stats
    print(f"\n{'='*50}")
    print(f"Connection from {addr}")
    
    # Reset per-session stats
    stats["count"] = 0
    stats["similarity"] = 0
    stats["is_moving"] = False
    
    # Determine mode based on expert data existence
    calibration_data = {"ax": [], "ay": [], "az": []}
    baseline = None
    calibration_start_time = None
    is_calibrated = False
    expert_started = False

    if not os.path.exists(REFERENCE_FILE):
        mode = "RECORDING_EXPERT"
        stats["mode"] = "WAITING_FOR_EXPERT"
        # We don't set calibration_start_time here anymore. 
        # It should start when the first sensor data arrives AND after advice (if any).
        print(f">>> Mode: EXPERT RECORDING (Pending connection)")
    else:
        mode = "COUNTING"
        stats["mode"] = "COUNTING"
        if os.path.exists(CALIBRATION_FILE):
            with open(CALIBRATION_FILE, "r") as f:
                baseline = json.load(f)
            is_calibrated = True
        print(">>> Mode: COUNTING (Pattern Recognition)")
    
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
            
            # Sync mode from global stats
            mode = stats.get("mode", mode)
            
            # Parse sensor data
            try:
                if line.startswith("ENV:"):
                    try:
                        env_data = line.split(":")[1].split(",")
                        temp_val = float(env_data[0])
                        humi_val = float(env_data[1])
                        
                        print(f">>> Received Env: {temp_val:.1f}C / {humi_val:.1f}%")
                        stats["humidity"] = humi_val 
                        
                        # Trigger AI advice ONLY ONCE
                        global ai_advice_triggered
                        if not ai_advice_triggered:
                            ai_advice_triggered = True
                            threading.Thread(target=get_ai_advice, args=(temp_val, humi_val), daemon=True).start()
                        
                    except Exception as e:
                        print(f">>> ENV Parse Error: {e}")
                    continue 

                if line.startswith("TEMP:"):
                    try:
                        temp_val = float(line.split(":")[1])
                        print(f">>> Received Temperature: {temp_val:.1f}C")
                        threading.Thread(target=get_ai_advice, args=(temp_val,), daemon=True).start()
                    except:
                        pass
                    continue

                parts = line.split(",")
                if len(parts) < 6: continue 
                ax, ay, az, gx, gy, gz = map(int, parts[:6])
                
                # Wait for AI advice completion before processing sensor data
                global ai_advice_completed
                if ai_advice_triggered and not ai_advice_completed:
                    continue
                
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
                                    
                                    # Simple activity burst counting
                                    if expert_len > 0:
                                        process_rep(current_ax, current_ay, current_az, stats, session_reps)
                                    
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
        if is_moving:
            print(">>> Capturing final rep before closure...")
            process_rep(current_ax, current_ay, current_az, stats, session_reps)
        
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
    
    print(f"{'='*50}\n")

def main():
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
        s.listen(5) # Support multiple connections
        while True:
            print("\nWaiting for device connections...")
            conn, addr = s.accept()
            print(f">>> New connection accepted from: {addr}")
            # Start a new thread for each connection
            threading.Thread(target=handle_one_connection, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    main()

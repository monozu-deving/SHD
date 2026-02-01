import threading
import time
import socket
import json
import os
import math

from config import *
from state import AppState
from analysis import extract_movement_segment, calculate_similarity, process_rep
from visualizer import save_movement_graph, save_calibration_graph
from ai_coach import AICoach

class DeviceHandler:
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.app_state = AppState.get_instance()
        self.stats = self.app_state.stats
        self.ai_coach = AICoach()

    def run(self):
        print(f"\n{'='*50}")
        print(f"Connection from {self.addr}")
        
        # Reset per-session stats
        self.stats["count"] = 0
        self.stats["similarity"] = 0
        self.stats["is_moving"] = False
        
        # Determine mode based on expert data existence
        calibration_data = {"ax": [], "ay": [], "az": []}
        baseline = None
        calibration_start_time = None
        is_calibrated = False
        expert_started = False
        
        mode = "IDLE"
        device_type = "UNKNOWN"  # "DUMBBELL" or "ENV_SENSOR"
        
        # We DO NOT set global stats mode here immediately to avoid overwriting 
        # the current mode when a simple environment sensor connects.
        # We will determine the mode only if we detect it's a dumbbell.
        
        # Buffers
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
        self.conn.settimeout(10.0) # Increased timeout
        last_rx = time.time()
        
        # Initial stats mode set
        
        try:
            while True:
                try:
                    data = self.conn.recv(4096)
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
                    mode = self.stats.get("mode", mode)                    
                    # Parse sensor data
                    try:
                        if line.startswith("ENV:"):
                            device_type = "ENV_SENSOR"
                            try:
                                env_data = line.split(":")[1].split(",")
                                temp_val = float(env_data[0])
                                humi_val = float(env_data[1])
                                
                                self.stats["humidity"] = humi_val 
                                
                                # Trigger AI advice ONLY ONCE
                                if not self.app_state.ai_advice_triggered:
                                    self.app_state.ai_advice_triggered = True
                                    threading.Thread(target=self.ai_coach.get_advice, args=(temp_val, humi_val), daemon=True).start()
                                
                            except Exception as e:
                                print(f">>> ENV Parse Error: {e}")
                            continue 

                        if line.startswith("TEMP:"):
                            device_type = "ENV_SENSOR"
                            try:
                                temp_val = float(line.split(":")[1])
                                print(f">>> Received Temperature: {temp_val:.1f}C")
                                threading.Thread(target=self.ai_coach.get_advice, args=(temp_val,), daemon=True).start()
                            except:
                                pass
                            continue

                        parts = line.split(",")
                        if len(parts) >= 6: 
                            # It is a DUMBBELL
                            if device_type == "UNKNOWN":
                                device_type = "DUMBBELL"
                                # Initialize mode only for Dumbbell
                                if not os.path.exists(REFERENCE_FILE):
                                    mode = "RECORDING_EXPERT"
                                    self.stats["mode"] = "WAITING_FOR_EXPERT"
                                    print(f">>> Mode: EXPERT RECORDING (Pending connection)")
                                else:
                                    mode = "COUNTING"
                                    self.stats["mode"] = "COUNTING"
                                    if os.path.exists(CALIBRATION_FILE):
                                        with open(CALIBRATION_FILE, "r") as f:
                                            baseline = json.load(f)
                                        is_calibrated = True
                                    print(">>> Mode: COUNTING (Pattern Recognition)")

                            ax, ay, az, gx, gy, gz = map(int, parts[:6])
                        
                        # Wait for AI advice completion before processing sensor data
                        if self.app_state.ai_advice_triggered and not self.app_state.ai_advice_completed:
                            continue
                        
                        # Mode-specific handling
                        if mode in ["RECORDING_EXPERT", "READY_TO_RECORD", "CALIBRATING"]:
                            if not is_calibrated:
                                if not calibration_start_time:
                                    calibration_start_time = time.time()
                                    self.stats["mode"] = "CALIBRATING"
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
                                    self.stats["mode"] = "READY_TO_RECORD"
                                    print(f">>> Calibration DONE: {baseline}")
                                    print(f">>> Perform movement, then press button again to STOP recording")
                            
                            else:
                                if not expert_started:
                                    expert_started = True
                                    self.stats["mode"] = "RECORDING_EXPERT"
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
                            expert_len = 0
                            ref_data = None
                            if os.path.exists(REFERENCE_FILE):
                                with open(REFERENCE_FILE, "r") as f:
                                    ref_data = json.load(f)
                                expert_len = len(ref_data["ax"])
                            
                            if len(recent_magnitudes) >= WINDOW_SIZE:
                                avg_mag = sum(recent_magnitudes) / len(recent_magnitudes)
                                variance = sum((m - avg_mag)**2 for m in recent_magnitudes) / len(recent_magnitudes)
                                
                                if variance > THRESHOLD:
                                    if not is_moving:
                                        is_moving = True
                                        current_ax, current_ay, current_az = [], [], []
                                        self.stats["is_moving"] = True
                                        print(">>> Movement STARTED")
                                    still_start_time = None
                                else:
                                    if is_moving:
                                        if still_start_time is None:
                                            still_start_time = time.time()
                                        elif time.time() - still_start_time > STILL_TIME_LIMIT:
                                            is_moving = False
                                            self.stats["is_moving"] = False
                                            print(f">>> Movement ENDED ({len(current_ax)} samples)")
                                            
                                            # Simple activity burst counting
                                            if expert_len > 0:
                                                process_rep(current_ax, current_ay, current_az, self.stats, session_reps)
                                            
                                            current_ax, current_ay, current_az = [], [], []
                                            still_start_time = None
                        
                            if is_moving:
                                current_ax.append(ax)
                                current_ay.append(ay)
                                current_az.append(az)
                                
                                # Stop if we exceed 1.5x expert length (safety) or use STILL_TIME_LIMIT
                                if expert_len > 0 and len(current_ax) > expert_len * 1.5:
                                    pass
                                
                            # Update real-time distribution (sample every 5th point to reduce data)
                            if len(current_ax) % 5 == 0:
                                current_mags = [math.sqrt(a**2 + b**2 + c**2) for a, b, c in zip(current_ax, current_ay, current_az)]
                                self.stats["current_distribution"] = current_mags[-50:]  # Last 50 samples
                                
                                if expert_len > 0:
                                    expert_mags = [math.sqrt(a**2 + b**2 + c**2) for a, b, c in zip(ref_data["ax"], ref_data["ay"], ref_data["az"])]
                                    self.stats["expert_distribution"] = expert_mags
                                
                    except Exception as e:
                        print(f"[ERROR] Data parse loop error: {e}")
                        continue
            
            # Connection ended cleanup
            if mode == "COUNTING":
                if is_moving:
                    print(">>> Capturing final rep before closure...")
                    process_rep(current_ax, current_ay, current_az, self.stats, session_reps)
                
                if os.path.exists(REFERENCE_FILE):
                    with open(REFERENCE_FILE, "r") as f:
                        ref_data = json.load(f)
                    self._finalize_session(session_reps, ref_data, self.stats)

            # Connection ended - save expert if in recording mode
            if (mode == "RECORDING_EXPERT" or mode == "READY_TO_RECORD") and is_calibrated:
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
                    self.stats["mode"] = "READY"
                else:
                    print(f">>> EXPERT movement too subtle or short")
                    self.stats["mode"] = "IDLE"
            
            print(f"{'='*50}\n")
        
        finally:
            self.conn.close()

    def _finalize_session(self, session_reps, ref_data, stats):
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

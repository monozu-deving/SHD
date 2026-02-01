import threading
import time
import socket
import json
import os
import math

from config import *
from state import AppState
from analysis import extract_movement_segment, calculate_similarity, process_rep, save_set_to_json, get_expert_peak, get_active_axes
from visualizer import save_movement_graph, save_calibration_graph
from ai_coach import AICoach

class DeviceHandler:
    def __init__(self, conn, addr, is_env_only=False):
        self.conn = conn
        self.addr = addr
        self.app_state = AppState.get_instance()
        self.stats = self.app_state.stats
        self.ai_coach = AICoach()
        self.is_env_only = is_env_only

    def run(self):
        print(f"\n{'='*50}")
        print(f"Connection from {self.addr} | Role: {'ENV_ONLY' if self.is_env_only else 'DUMBBELL'}")
        
        # Reset per-session stats only for dumbbell
        if not self.is_env_only:
            self.stats["count"] = 0
            self.stats["similarity"] = 0
            self.stats["is_moving"] = False
            self.stats["is_set_active"] = False
            print(f">>> [DUMBBELL] Session stats initialized for {self.addr}")
        
        # Determine mode based on required files
        calibration_data = {"ax": [], "ay": [], "az": []}
        baseline = None
        calibration_start_time = None
        is_calibrated = False
        
        expert_peak = 0.0
        active_axes = ["ax", "ay", "az"] # Default
        mode = "IDLE" # Default
        
        if not self.is_env_only:
            # 1. 베이스라인 파일 확인
            has_baseline = os.path.exists(CALIBRATION_FILE)
            # 2. 전문가 동작 파일 확인 
            has_reference = os.path.exists(REFERENCE_FILE)

            if not has_baseline:
                mode = "CALIBRATING"
                self.stats["mode"] = "CALIBRATING"
                calibration_start_time = time.time()
                print(">>> Initial Mode: CALIBRATING (Baseline file missing)")
            elif not has_reference:
                mode = "RECORDING_EXPERT"
                self.stats["mode"] = "WAITING_FOR_EXPERT"
                print(">>> Initial Mode: RECORDING_EXPERT (Reference file missing)")
                # 베이스라인은 있으므로 로드
                try:
                    with open(CALIBRATION_FILE, "r") as f:
                        baseline = json.load(f)
                        is_calibrated = True
                except Exception as e:
                    print(f"[ERROR] Failed to load baseline: {e}")
                    is_calibrated = False
            else:
                # 둘 다 있으면 즉시 카운팅 모드로!
                mode = "COUNTING"
                self.stats["mode"] = "COUNTING"
                print(">>> Initial Mode: COUNTING (Data exists, skipping setup)")
                try:
                    with open(CALIBRATION_FILE, "r") as f:
                        baseline = json.load(f)
                        is_calibrated = True
                    with open(REFERENCE_FILE, "r") as f:
                        ref_data = json.load(f)
                        active_axes = get_active_axes(ref_data, baseline)
                        expert_peak = get_expert_peak(ref_data, active_axes)
                        print(f">>> Active Axes: {active_axes}")
                        print(f">>> Pre-loaded Expert Peak (Active axes only): {expert_peak:.0f}")
                except Exception as e:
                    print(f"[ERROR] Failed to skip setup: {e}")
                    is_calibrated = False
        
        # Buffers
        current_ax, current_ay, current_az = [], [], []
        session_reps = [] # To store all reps for final analysis
        
        # Movement detection
        is_moving = False
        still_start_time = None
        entered_peak_this_burst = False # 피크 구역 진입 여부
        has_counted_this_burst = False   # 해당 버스트에서 이미 카운트했는지 여부
        
        # Expert Recording Buffers
        expert_buffer = {"ax": [], "ay": [], "az": []}
        
        raw_buf = b""
        # ENV 센서면 30초, 아령이면 길게 대기
        self.conn.settimeout(30.0 if self.is_env_only else 60.0) 
        last_rx = time.time()
        
        try:
            set_raw_buffer = {"ax": [], "ay": [], "az": []}
            movement_offsets = [] # 세트 내 각 회차 시작 지점 저장
            
            while True:
                try:
                    data = self.conn.recv(4096)
                    if not data:
                        print(f">>> Connection closed ({'Env' if self.is_env_only else 'Dumbbell'})")
                        break
                    last_rx = time.time()
                    raw_buf += data
                except socket.timeout:
                    if time.time() - last_rx > (30 if self.is_env_only else 60):
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
                    
                    # [SIGNAL LOGGING] 오직 아령(DUMBBELL) 연결일 때만 터미널에 원시 신호 출력
                    if not self.is_env_only:
                        print(f"[RAW_SIGNAL] {line}")

                    try:
                        # 1. 온습도 센서 (ENV_ONLY) 처리
                        if self.is_env_only and line.startswith("ENV:"):
                            try:
                                env_data = line.split(":")[1].split(",")
                                temp_val = float(env_data[0])
                                humi_val = float(env_data[1])
                                self.stats["humidity"] = humi_val 
                                print(f">>> 온습도 데이터 수신: 온도={temp_val}°C, 습도={humi_val}%")
                                
                                if not self.app_state.ai_advice_triggered:
                                    self.app_state.ai_advice_triggered = True
                                    print(">>> AI 조언 생성 중...")
                                    threading.Thread(target=self.ai_coach.get_advice, args=(temp_val, humi_val), daemon=True).start()
                                
                                # [요청 반영] 잔여 데이터 정리(Drain) 및 깨끗한 종료
                                print(">>> 잔여 데이터 정리 중...")
                                self.conn.setblocking(False)
                                try:
                                    time.sleep(0.3)
                                    while self.conn.recv(1024): pass
                                except: pass
                                
                                print(">>> 온습도 측정 완료. 기기 연결을 안전하게 종료합니다.")
                                self.app_state.env_sensor_connected = True
                                try:
                                    self.conn.shutdown(socket.SHUT_RDWR)
                                except: pass
                                self.conn.close()
                                return
                            except Exception as e:
                                print(f">>> ENV Parse Error: {e}")
                            continue

                        # 2. 아령 (DUMBBELL) 처리
                        if not self.is_env_only:
                            # 아령 모드에서 오는 ENV 정보는 습도만 업데이트 (로깅 없이)
                            if line.startswith("ENV:"):
                                try:
                                    env_data = line.split(":")[1].split(",")
                                    self.stats["humidity"] = float(env_data[1])
                                except: pass
                                continue

                            # 3. 아령 데이터 처리 (7열 CSV: ax,ay,az,gx,gy,gz,btn)
                            parts = line.split(",")
                            if len(parts) >= 7: 
                                ax, ay, az, gx, gy, gz = map(int, parts[:6])
                                btn_val = int(parts[6])
                                is_now_active = (btn_val == 1)
                                was_active = self.stats.get("is_set_active", False)

                                # [통합 로직] 버튼 상태 변화 감지
                                # 세트 시작 (False -> True)
                                if not was_active and is_now_active:
                                    session_reps = []
                                    set_raw_buffer = {"ax": [], "ay": [], "az": []} # 초기화
                                    movement_offsets = [] # 초기화
                                    self.stats["count"] = 0
                                    print(f"[ACTION] Set #{self.stats['set_count'] + 1} STARTED! (Sync via Data Column)")
                                
                                # 세트 진행 중 데이터 누적
                                if is_now_active:
                                    set_raw_buffer["ax"].append(ax)
                                    set_raw_buffer["ay"].append(ay)
                                    set_raw_buffer["az"].append(az)

                                # 세트 종료 (True -> False)
                                if was_active and not is_now_active:
                                    # [요청 반영] 세트 종료 시 움직임 중이었다면 해당 동작까지 강제 포함
                                    if is_moving and len(current_ax) >= MIN_MOVEMENT_SAMPLES:
                                        print(f"[ACTION] Finalizing ongoing movement before set end...")
                                        self._process_and_save_rep(current_ax, current_ay, current_az, baseline, session_reps)
                                        is_moving = False
                                        self.stats["is_moving"] = False

                                    self.stats["set_count"] += 1
                                    print(f"[ACTION] Set #{self.stats['set_count']} COMPLETED! (Sync via Data Column)")
                                    if os.path.exists(REFERENCE_FILE):
                                        try:
                                            with open(REFERENCE_FILE, "r") as f:
                                                ref_data = json.load(f)
                                            # [요청 반영] 전체 세트 데이터 및 회차 오프셋 전달 (시각화용)
                                            self._finalize_session(session_reps, ref_data, self.stats, baseline, set_raw_buffer, movement_offsets)
                                        except Exception as e:
                                            print(f"[ERROR] Finalization failed: {e}")

                                self.stats["is_set_active"] = is_now_active
                                
                                # A. Calibration Mode
                                if mode == "CALIBRATING":
                                    calibration_data["ax"].append(ax)
                                    calibration_data["ay"].append(ay)
                                    calibration_data["az"].append(az)
                                    
                                    elapsed = time.time() - calibration_start_time
                                    if elapsed >= CALIBRATION_TIME:
                                        baseline = {
                                            "ax": sum(calibration_data["ax"]) / len(calibration_data["ax"]),
                                            "ay": sum(calibration_data["ay"]) / len(calibration_data["ay"]),
                                            "az": sum(calibration_data["az"]) / len(calibration_data["az"])
                                        }
                                        with open(CALIBRATION_FILE, "w") as f:
                                            json.dump(baseline, f)
                                        is_calibrated = True
                                        save_calibration_graph(calibration_data["ax"], calibration_data["ay"], calibration_data["az"], baseline)
                                        print(f">>> Calibration DONE. Baseline: {baseline}")
                                        
                                        if not os.path.exists(REFERENCE_FILE):
                                            mode = "RECORDING_EXPERT"
                                            self.stats["mode"] = "WAITING_FOR_EXPERT"
                                        else:
                                            mode = "COUNTING"
                                            self.stats["mode"] = "COUNTING"
                                    continue

                                # B. Regular Analysis
                                if is_calibrated:
                                    # MOVEMENT_TOLERANCE_PERCENT 기준으로 임계치 계산
                                    tol_x = max(abs(baseline["ax"]) * MOVEMENT_TOLERANCE_PERCENT, MIN_ABS_DIFF)
                                    tol_y = max(abs(baseline["ay"]) * MOVEMENT_TOLERANCE_PERCENT, MIN_ABS_DIFF)
                                    tol_z = max(abs(baseline["az"]) * MOVEMENT_TOLERANCE_PERCENT, MIN_ABS_DIFF)

                                    diff_x = abs(ax - baseline["ax"])
                                    diff_y = abs(ay - baseline["ay"])
                                    diff_z = abs(az - baseline["az"])

                                    # 허용 오차 범위를 벗어나면 움직임으로 간주
                                    is_out_of_range = (diff_x > tol_x or diff_y > tol_y or diff_z > tol_z)

                                    if is_out_of_range:
                                        # [요청 반영] 버튼이 켜져 있거나 '전문가 대기' 상태일 때 움직임 감지 시작
                                        can_start_move = self.stats.get("is_set_active") or (mode == "RECORDING_EXPERT")
                                        
                                        if not is_moving and can_start_move:
                                            # [요청 반영] 현재 세트 버퍼에서의 시작 인덱스 기록
                                            # Note: cur_mag and threshold are only defined in COUNTING mode.
                                            # Applying this condition universally might lead to NameError or unexpected behavior.
                                            # Assuming the user wants to add the offset recording here,
                                            # and the `if cur_mag > threshold:` condition is either a typo or
                                            # intended for a specific mode that's not universally applied here.
                                            # For now, I'll add the offset recording directly when movement starts.
                                            movement_offsets.append(len(set_raw_buffer["ax"]) - 1)
                                            print(f"[ACTION] Movement detected at offset {len(set_raw_buffer['ax'])-1}!")

                                            is_moving = True
                                            current_ax, current_ay, current_az = [], [], []
                                            self.stats["is_moving"] = True
                                            print(f"[ACTION] Movement STARTED ({mode})")
                                        still_start_time = None
                                    else:
                                        # 범위 내로 들어오면 정지 판정 대기
                                        if is_moving:
                                            if still_start_time is None:
                                                still_start_time = time.time()
                                            elif time.time() - still_start_time > STILL_TIME_LIMIT:
                                                is_moving = False
                                                self.stats["is_moving"] = False
                                                print(f"[ACTION] Movement ENDED ({len(current_ax)} samples)")
                                                
                                                if mode == "RECORDING_EXPERT":
                                                    # [요청 반영] 전문가 동작 처리 및 피크치 업데이트
                                                    r_ax, r_ay, r_az = extract_movement_segment(current_ax, current_ay, current_az, baseline)
                                                    if r_ax:
                                                        ref_data = {"ax": r_ax, "ay": r_ay, "az": r_az}
                                                        with open(REFERENCE_FILE, "w") as f:
                                                            json.dump(ref_data, f)
                                                        active_axes = get_active_axes(ref_data, baseline)
                                                        expert_peak = get_expert_peak(ref_data, active_axes)
                                                        print(f">>> Expert Reference SAVED! Active Axes: {active_axes}, Peak Intensity: {expert_peak:.0f}")
                                                        try:
                                                            fname = save_movement_graph(r_ax, r_ay, r_az, 0)
                                                            self.stats["latest_graph"] = fname
                                                        except: pass
                                                        mode = "COUNTING"
                                                        self.stats["mode"] = "COUNTING"
                                                else:
                                                    # [요청 반영] 회차 정산 (JSON 저장 -> 분석 -> 유사도)
                                                    # 카운트는 이미 피크 지점에서 수행됨
                                                    if self.stats.get("is_set_active") and len(current_ax) >= MIN_MOVEMENT_SAMPLES:
                                                        self._process_and_save_rep(current_ax, current_ay, current_az, baseline, session_reps)
                                                
                                                current_ax, current_ay, current_az = [], [], []
                                                still_start_time = None
                                                entered_peak_this_burst = False
                                                has_counted_this_burst = False
                                    
                                    if is_moving:
                                        current_ax.append(ax)
                                        current_ay.append(ay)
                                        current_az.append(az)

                                        # [요청 반영] 실시간 피크 감지: 진입(Enter) 후 이탈(Exit) 시 카운트 (COUNTING 모드 전용)
                                        # [요청 반영] 실시간 피크 감지: 활성 축(Active Axes) 기반 진입/이탈 체크
                                        if mode == "COUNTING" and not has_counted_this_burst and expert_peak > 0:
                                            # 활성 축들의 데이터만으로 현재 Magnitude 계산
                                            sum_sq = 0
                                            for axis_name in active_axes:
                                                val = {"ax": ax, "ay": ay, "az": az}[axis_name]
                                                sum_sq += val**2
                                            cur_mag = math.sqrt(sum_sq)
                                            
                                            threshold = expert_peak * (1 - PEAK_TOLERANCE_PERCENT)
                                            
                                            if not entered_peak_this_burst:
                                                if cur_mag >= threshold:
                                                    entered_peak_this_burst = True
                                                    print(f"[DEBUG] Peak Zone ENTERED (Active Axes Mag: {cur_mag:.0f})")
                                            else:
                                                if cur_mag < threshold:
                                                    self.stats["count"] += 1
                                                    has_counted_this_burst = True
                                                    print(f"[ACTION] Peak Zone EXITED! Rep #{self.stats['count']} counted (Mag: {cur_mag:.0f})")

                                # C. Update Visualization
                                if self.stats.get("is_set_active") or mode == "RECORDING_EXPERT":
                                    if len(current_ax) % 5 == 0:
                                        current_mags = [math.sqrt(a**2+b**2+c**2) for a,b,c in zip(current_ax, current_ay, current_az)]
                                        self.stats["current_distribution"] = current_mags[-50:]
                                else:
                                    if len(parts) % 5 == 0:
                                        live_mag = math.sqrt(ax**2 + ay**2 + az**2)
                                        if "current_distribution" not in self.stats: self.stats["current_distribution"] = []
                                        self.stats["current_distribution"].append(live_mag)
                                        if len(self.stats["current_distribution"]) > 50: self.stats["current_distribution"].pop(0)
                    except Exception as e:
                        print(f"[ERROR] Signal handle error: {e}")

        except Exception as e:
            print(f"[FATAL] DeviceHandler error: {e}")
        finally:
            self.conn.close()
            print(f">>> Connection closed: {self.addr}")

    def _finalize_session(self, session_reps, ref_data, stats, baseline=None, set_raw_data=None, movement_offsets=None):
        """세트 종료 후 전체 운동에 대한 유사도 정산 및 전문가 오버레이 그래프 생성"""
        if not session_reps or not ref_data:
            print("\n>>> 세트 종료. 분석할 운동 데이터가 없습니다.")
            return

        print("\n" + "="*50)
        print(f" FINAL SESSION REPORT (Total Reps: {len(session_reps)})")
        print(f" (Comparison with Expert Reference)")
        print("="*50)
        
        # 실제 베이스라인(0점)이 없으면 전문가 데이터의 첫 샘플을 임시로 사용
        if baseline is None:
            baseline = {"ax": ref_data["ax"][0], "ay": ref_data["ay"][0], "az": ref_data["az"][0]}
            print(">>> [WARNING] 세션 베이스라인(0점)을 찾을 수 없어 Reference의 시작점을 대신 사용합니다.")

        total_sim = 0
        valid_reps = 0
        for i, (ax, ay, az) in enumerate(session_reps):
            # 1. 베이스라인(0점)을 기준으로 실제 움직임 구간만 추출
            t_ax, t_ay, t_az = extract_movement_segment(ax, ay, az, baseline)
            
            # 추출 실패 시 원본 데이터 유지
            if not t_ax: 
                t_ax, t_ay, t_az = ax, ay, az
            
            # 2. 추출된 데이터를 전문가 Reference와 비교하여 유사도 계산
            s1 = calculate_similarity(ref_data["ax"], t_ax)
            s2 = calculate_similarity(ref_data["ay"], t_ay)
            s3 = calculate_similarity(ref_data["az"], t_az)
            avg_sim = (s1 + s2 + s3) / 3.0
            
            total_sim += avg_sim
            valid_reps += 1
            print(f" Rep #{i+1:2d} | Accuracy: {avg_sim:5.1f}%")
            
        if valid_reps > 0:
            final_avg = total_sim / valid_reps
            stats["similarity"] = final_avg
            print("-" * 50)
            print(f" AVERAGE SESSION ACCURACY: {final_avg:.1f}%")
            print(f">>> (Reference 대비 세트 평균 유사도 업데이트: {final_avg:.1f}%)")
            
            # [요청 반영] 세트(스텝) 통합 JSON 저장
            if set_raw_data:
                save_set_to_json(set_raw_data, self.stats["set_count"], final_avg)
            
            # [요청 반영] 세트(스텝) 종료 보고서용 전체 파형 및 전문가 가이드 오버레이 그래프 저장
            if set_raw_data:
                fname = save_movement_graph(set_raw_data["ax"], set_raw_data["ay"], set_raw_data["az"], self.stats["set_count"], final_avg, movement_offsets)
                self.stats["latest_graph"] = fname
        else:
            print(">>> 유효한 운동 회차가 없어 유사도를 정산할 수 없습니다.")
        
        print("="*50 + "\n")

    def _process_and_save_rep(self, current_ax, current_ay, current_az, baseline, session_reps):
        """동작 1회에 대한 JSON 저장, 이미지 생성 및 유사도 분석 수행"""
        try:
            # 1. 전문가 데이터 로드
            if not os.path.exists(REFERENCE_FILE):
                print("[WARNING] 전문가 데이터가 없어 정산을 건너뜁니다.")
                return
                
            with open(REFERENCE_FILE, "r") as f:
                ref_data = json.load(f)
            
            # 2. 현재 동작 세그먼트 정밀 추출 (TOLERANCE 기반)
            cur_ax, cur_ay, cur_az = extract_movement_segment(
                current_ax, current_ay, current_az, baseline
            )
            
            if cur_ax:
                # 3. 유사도 계산
                sim_x = calculate_similarity(ref_data["ax"], cur_ax)
                sim_y = calculate_similarity(ref_data["ay"], cur_ay)
                sim_z = calculate_similarity(ref_data["az"], cur_az)
                avg_sim = (sim_x + sim_y + sim_z) / 3.0
                
                # [요청 반영] 카운트는 이미 피크 지점에서 올라갔으므로 현재 카운트 사용
                rep_num = self.stats["count"]
                
                # 4. [요청 반영] 개별 JSON 저장 제거 (세트 종료 시 일괄 저장)
                # save_rep_to_json(current_ax, current_ay, current_az, rep_num, avg_sim)
                
                # 5. [요청 반영] 그래프 저장 제거 (세트 종료 시 일괄 출력 예정)
                # save_movement_graph(current_ax, current_ay, current_az, rep_num, avg_sim)
                
                # 6. 통계 업데이트 (유사도 반영)
                self.stats["similarity"] = avg_sim
                session_reps.append((list(current_ax), list(current_ay), list(current_az)))
                
                print(f"[ACTION] Rep #{rep_num} ANALYZED & ARCHIVED: {avg_sim:.1f}%")
            else:
                print(f"[ACTION] Burst ended but no valid segment extracted (discarded)")
        except Exception as e:
            print(f"[ERROR] Rep processing failure: {e}")

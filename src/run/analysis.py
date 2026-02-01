import json
import os
import math
from datetime import datetime
from config import *

def get_active_axes(ref_data, baseline):
    """Identify axes that show significant movement compared to baseline in expert data"""
    if not ref_data or not baseline:
        return ["ax", "ay", "az"] # Default to all if missing
    
    active = []
    # 전문가 데이터에서 각 축의 최대 변화량이 임계치(TOLERANCE)를 넘는지 확인
    for axis in ["ax", "ay", "az"]:
        max_val = max(ref_data[axis])
        min_val = min(ref_data[axis])
        base_val = baseline[axis]
        
        # 베이스라인 대비 최대 거리가 MOVEMENT_TOLERANCE_PERCENT 이상인 경우만 활성축으로 간주
        tol = max(abs(base_val) * MOVEMENT_TOLERANCE_PERCENT, MIN_ABS_DIFF)
        if abs(max_val - base_val) > tol or abs(min_val - base_val) > tol:
            active.append(axis)
            
    return active if active else ["ax", "ay", "az"]

def get_expert_peak(ref_data, active_axes=None):
    """Calculate maximum magnitude using only active axes"""
    if not ref_data: return 0.0
    if active_axes is None: active_axes = ["ax", "ay", "az"]
    
    mags = []
    for i in range(len(ref_data["ax"])):
        sum_sq = 0
        for axis in active_axes:
            sum_sq += ref_data[axis][i]**2
        mags.append(math.sqrt(sum_sq))
        
    return max(mags) if mags else 0.0

def save_set_to_json(set_data, set_num, avg_similarity):
    """Archive entire set data into a single JSON file"""
    if not set_data or not set_data.get("ax"): return
    
    os.makedirs(REPS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"set_{set_num}_{ts}.json"
    filepath = os.path.join(REPS_DIR, filename)
    
    data = {
        "set_num": set_num,
        "timestamp": ts,
        "avg_similarity": avg_similarity,
        "data": set_data
    }
    
    with open(filepath, "w") as f:
        json.dump(data, f)
    print(f">>> Full Set #{set_num} Data Archived: {filepath}")

# def save_rep_to_json(ax_list, ay_list, az_list, rep_num, similarity):
#     """(Deprecated) Archive single rep data"""

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
        
        # MOVEMENT_TOLERANCE_PERCENT 기준으로 임계치 계산
        tol_x = max(abs(baseline["ax"]) * MOVEMENT_TOLERANCE_PERCENT, MIN_ABS_DIFF)
        tol_y = max(abs(baseline["ay"]) * MOVEMENT_TOLERANCE_PERCENT, MIN_ABS_DIFF)
        tol_z = max(abs(baseline["az"]) * MOVEMENT_TOLERANCE_PERCENT, MIN_ABS_DIFF)

        if diff_x > tol_x or diff_y > tol_y or diff_z > tol_z:
            if start_idx == -1:
                start_idx = i
            end_idx = i
            
    if start_idx != -1 and end_idx != -1:
        # 시작과 종료 지점에 약간의 마진(Padding) 추가
        final_start = max(0, start_idx - 2)
        final_end = min(len(ax_list) - 1, end_idx + 2)
        
        trimmed_len = final_end - final_start + 1
        if trimmed_len >= MIN_MOVEMENT_SAMPLES:
            return ax_list[final_start:final_end+1], ay_list[final_start:final_end+1], az_list[final_start:final_end+1]
    
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
        print(f"[ACTION] Rep #{stats['count']} counted!")
        
        if session_reps is not None:
            # Store the raw burst for later analysis
            session_reps.append((list(ax_buf), list(ay_buf), list(az_buf)))
        
        stats["similarity"] = 0 
        stats["current_distribution"] = []
        return True
    return False

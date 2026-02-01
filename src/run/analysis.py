from config import *

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

import matplotlib.pyplot as plt
import os
import json
from datetime import datetime
from config import GRAPH_DIR, REFERENCE_FILE

def save_movement_graph(ax_list, ay_list, az_list, movement_num, similarity=None, offsets=None):
    if len(ax_list) < 5: return
    
    plt.figure(figsize=(12, 6))
    
    if movement_num == 0:
        # 전문가 동작 시각화
        plt.plot(ax_list, 'r-', label="ax")
        plt.plot(ay_list, 'g-', label="ay")
        plt.plot(az_list, 'b-', label="az")
        plt.title("Expert Movement (Reference)")
        filename = "expert_movement.png"
    else:
        # [요청 반영] 전문가 가이드(점선) 오버레이
        if offsets and os.path.exists(REFERENCE_FILE):
            try:
                with open(REFERENCE_FILE, "r") as f:
                    ref = json.load(f)
                
                for idx, offset in enumerate(offsets):
                    x_range = range(offset, offset + len(ref["ax"]))
                    # 범례가 중복되지 않도록 처음 한 번만 label 추가
                    lbl_prefix = "Expert " if idx == 0 else ""
                    plt.plot(x_range, ref["ax"], 'r--', alpha=0.3, label=f"{lbl_prefix}ax" if idx == 0 else None)
                    plt.plot(x_range, ref["ay"], 'g--', alpha=0.3, label=f"{lbl_prefix}ay" if idx == 0 else None)
                    plt.plot(x_range, ref["az"], 'b--', alpha=0.3, label=f"{lbl_prefix}az" if idx == 0 else None)
            except Exception as e:
                print(f"[ERROR] Failed to overlay expert data: {e}")

        # 사용자 세트(스텝) 전체 운동 파형
        plt.plot(ax_list, 'r-', alpha=0.8, label="User ax")
        plt.plot(ay_list, 'g-', alpha=0.8, label="User ay")
        plt.plot(az_list, 'b-', alpha=0.8, label="User az")
        
        title = f"Workout Set #{movement_num}"
        if similarity: title += f" | Avg Accuracy: {similarity:.1f}%"
        plt.title(title)
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"set_{movement_num}_{ts}.png"
    
    plt.xlabel("Sample Index")
    plt.ylabel("Raw Intensity")
    plt.legend(loc='upper right', ncol=2, fontsize='small')
    plt.grid(True, alpha=0.2)
    
    filepath = os.path.join(GRAPH_DIR, filename)
    plt.tight_layout()
    plt.savefig(filepath, dpi=150)
    plt.close()
    print(f">>> Graph saved: {filepath}")
    return filename

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

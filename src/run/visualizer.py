import matplotlib.pyplot as plt
import os
import json
from datetime import datetime
from config import GRAPH_DIR, REFERENCE_FILE

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

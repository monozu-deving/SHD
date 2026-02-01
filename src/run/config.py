import os

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REFERENCE_FILE = os.path.join(BASE_DIR, "calibration", "reference_data.json")
CALIBRATION_FILE = os.path.join(BASE_DIR, "calibration", "baseline.json")
GRAPH_DIR = os.path.join(BASE_DIR, "graph")
REPS_DIR = os.path.join(BASE_DIR, "reps")

# Network
HOST = "0.0.0.0"
PORT = 5000

# Params
MAX_SAMPLES = 5000
THRESHOLD = 3000
STILL_TIME_LIMIT = 0.5
MIN_MOVEMENT_SAMPLES = 5
CALIBRATION_TIME = 5.0
THRESHOLD_PERCENT = 0.05
MIN_ABS_DIFF = 300
MOVEMENT_TOLERANCE_PERCENT = 0.08  # Baseline 대비 8% 이상 변화 시 움직임으로 간주
STILL_TIME_LIMIT = 0.6            # 0.6초간 범위 내에 머물면 종료
PEAK_TOLERANCE_PERCENT = 0.2      # 전문가 피크의 80% 도달 시 카운트

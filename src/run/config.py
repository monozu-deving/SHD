import os

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REFERENCE_FILE = os.path.join(BASE_DIR, "calibration", "reference_data.json")
CALIBRATION_FILE = os.path.join(BASE_DIR, "calibration", "baseline.json")
GRAPH_DIR = os.path.join(BASE_DIR, "graph")

# Network
HOST = "0.0.0.0"
PORT = 5000

# Params
MAX_SAMPLES = 5000
THRESHOLD = 3000
STILL_TIME_LIMIT = 0.7
MIN_MOVEMENT_SAMPLES = 5
CALIBRATION_TIME = 5.0
THRESHOLD_PERCENT = 0.05
MIN_ABS_DIFF = 300

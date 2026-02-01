import threading

class AppState:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(AppState, cls).__new__(cls)
                    cls._instance.stats = {
                        "count": 0,
                        "similarity": 0,
                        "is_moving": False,
                        "mode": "IDLE",
                        "current_distribution": [],
                        "expert_distribution": [],
                        "advice": "",
                        "advice_status": "",
                        "humidity": 0,
                        "connection_phase": "WAITING_ENV",
                        "allow_dumbbell": False,
                        "is_set_active": False,
                        "set_count": 0,
                        "latest_graph": ""
                    }
                    cls._instance.ai_advice_triggered = False
                    cls._instance.ai_advice_completed = False
                    cls._instance.env_sensor_connected = False
        return cls._instance

    @classmethod
    def get_instance(cls):
        return cls()

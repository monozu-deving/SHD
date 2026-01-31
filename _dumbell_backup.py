import socket
import time
from datetime import datetime
import math
import matplotlib.pyplot as plt

HOST = "0.0.0.0"
PORT = 5000
ACC_LSB_PER_G = 16384.0
G = 9.80665
GYRO_LSB_PER_DPS = 131.0
DEG2RAD = math.pi / 180.0

# 전역 보정 저장소
saved_calib = {"done": False, "r": 0.0, "p": 0.0, "gb": [0.0, 0.0, 0.0]}

def rot_matrix_from_euler(r, p, y):
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    return [
        [cy*cp, cy*sp*sr - sy*cr, cy*sp*cr + sy*sr],
        [sy*cp, sy*sp*sr + cy*cr, sy*sp*cr - cy*sr],
        [-sp,   cp*sr,            cp*cr]
    ]

def handle_one_connection(conn, addr, session_id):
    global saved_calib
    print(f"\n[Session {session_id}] Connected.")
    
    history = {'t': [], 'pz': []}
    vx = vy = vz = px = py = pz = 0.0
    acc_sum = [0, 0, 0]; gyro_sum = [0, 0, 0]; c_count = 0
    
    buf = b""
    conn.settimeout(2.0)
    t0 = last_time = None

    while True:
        try:
            data = conn.recv(4096)
            if not data: break
            buf += data
        except: break

        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            try:
                vals = list(map(int, line.decode(errors="ignore").strip().split(',')))
                if len(vals) < 6: continue
                
                now = time.time()
                if t0 is None: t0 = now; last_time = now; continue
                dt = now - last_time
                last_time = now

                # 물리값 변환
                ax, ay, az = [(v / ACC_LSB_PER_G) * G for v in vals[:3]]
                gx, gy, gz = [(v / GYRO_LSB_PER_DPS) * DEG2RAD for v in vals[3:6]]

                # --- 보정 로직 ---
                if not saved_calib["done"]:
                    acc_sum[0]+=ax; acc_sum[1]+=ay; acc_sum[2]+=az
                    gyro_sum[0]+=gx; gyro_sum[1]+=gy; gyro_sum[2]+=gz
                    c_count += 1
                    # 5개 샘플(약 0.1초)만 수집
                    if c_count >= 5:
                        ax0, ay0, az0 = [s/c_count for s in acc_sum]
                        saved_calib["gb"] = [g/c_count for g in gyro_sum]
                        saved_calib["r"] = math.atan2(ay0, az0)
                        saved_calib["p"] = math.atan2(-ax0, math.sqrt(ay0**2 + az0**2))
                        saved_calib["done"] = True
                        print("\a>>> 최초 1회 보정 완료! 이제부터 바로 시작됩니다.")
                    continue

                # --- 실시간 분석 (보정 완료 상태) ---
                gx -= saved_calib["gb"][0]; gy -= saved_calib["gb"][1]; gz -= saved_calib["gb"][2]
                
                # 가속도 월드 변환 및 중력 제거 (Z축 중심)
                R = rot_matrix_from_euler(saved_calib["r"], saved_calib["p"], 0)
                awz = R[2][0]*ax + R[2][1]*ay + R[2][2]*az
                alin_z = awz - G 

                if abs(alin_z) < 0.3: alin_z = 0 # 노이즈 컷
                
                vz += alin_z * dt
                pz += vz * dt

                history['t'].append(now - t0)
                history['pz'].append(pz)

            except: continue

    if history['t']:
        plt.figure(figsize=(8, 4))
        plt.plot(history['t'], history['pz'], 'r-')
        plt.title(f"Height Analysis - Session {session_id}")
        plt.grid(True)
        plt.savefig(f"dumpbell_{session_id}.png")
        plt.close()
        print(f"Saved: dumpbell_{session_id}.png")

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT)); s.listen(1)
        print(f"Server ON: {HOST}:{PORT}")
        sid = 0
        while True:
            conn, addr = s.accept()
            sid += 1
            handle_one_connection(conn, addr, sid)

if __name__ == "__main__":
    main()
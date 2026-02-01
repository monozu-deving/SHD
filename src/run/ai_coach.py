from openai import OpenAI
from dotenv import load_dotenv
import os
import time
from config import BASE_DIR
from state import AppState

class AICoach:
    def __init__(self):
        load_dotenv(os.path.join(BASE_DIR, ".env"))
        api_key = os.getenv("OPENAI_API_KEY")
        self.client_ai = OpenAI(api_key=api_key) if api_key else None
        self.app_state = AppState.get_instance()

    def get_advice(self, temperature, humidity=0):
        """Fetch exercise advice from GPT based on current temperature and humidity"""
        stats = self.app_state.stats
        
        try:
            if not self.client_ai:
                print(">>> Skipping AI advice: OPENAI_API_KEY is not set in .env")
                stats["advice_status"] = "❌ AI 설정 미흡"
                stats["advice"] = ".env 파일에 OpenAI API 키를 설정하면 스마트한 운동 조언을 받을 수 있습니다!"
                return

            stats["advice_status"] = f"🌡️ 온습도 수신 완료: {temperature:.1f}°C / {humidity}%"
            time.sleep(0.5) 
            
            print(f">>> Fetching AI advice for {temperature:.1f}C, {humidity}%...")
            stats["advice_status"] = "🧠 AI 전문 트레이너의 온습도 분석 중..."
            stats["advice"] = "AI 조언을 생성하고 있습니다..."
            
            response = self.client_ai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "너는 전문 헬스 트레이너야. 사용자의 현재 운동 환경 온도(Celsius)와 습도(%)를 보고, 해당 환경에서 운동할 때의 주의사항(부상 방지, 수분 섭취, 불쾌지수 등)과 덤벨 운동 팁을 딱 3문장 정도로 친절하고 전문적으로 말해줘."},
                    {"role": "user", "content": f"현재 온도는 {temperature:.1f}도이고 습도는 {humidity}%야."}
                ],
                max_tokens=200
            )
            stats["advice"] = response.choices[0].message.content
            stats["advice_status"] = "✅ 맞춤 온습도 가이드 생성 완료!"
            print(f">>> AI Advice: {stats['advice']}")
            
            # Mark AI advice as completed
            self.app_state.ai_advice_completed = True
            
        except Exception as e:
            print(f">>> AI Advice Error: {e}")
            stats["advice_status"] = "⚠️ AI 분석 중 오류 발생"
            stats["advice"] = "AI 조언을 가져오는 데 실패했습니다. 평소처럼 안전하게 운동하세요!"

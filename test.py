import os
from dotenv import load_dotenv

# .env 파일에서 환경변수 로드
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")  # 환경 변수명만 입력!
print("OpenAI API Key:", api_key[:8] + "..." if api_key else "Not found")

try:
    import openai
    client = openai.OpenAI(api_key=api_key)
    models = client.models.list()
    print("OpenAI API 연결 성공! 사용 가능한 모델 수:", len(models.data))
except Exception as e:
    print("OpenAI API 연결 실패:", e)

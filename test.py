import os
from langsmith import Client

# 발급받은 LangSmith API 키를 환경 변수에 저장하거나 직접 입력합니다
os.environ["LANGSMITH_API_KEY"] = "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"

try:
    client = Client()
    # 간단한 접근 테스트. 프로젝트 리스트를 불러옵니다.
    projects = client.list_projects()
    print("API Key가 정상적으로 작동합니다.")
    print("프로젝트 리스트:", list(projects))
except Exception as e:
    print("API Key가 유효하지 않거나, 연결에 문제가 있습니다.")
    print("오류 내용:", e)

# 월급아 어디가니?

사회초년생이 월급, 지출, 자산, 투자 성향과 이번 달 상황을 입력하면
생활비·저축·투자 배분안을 보여주는 Streamlit MVP입니다.

## 로컬 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

## AI 연결(선택)

`.streamlit/secrets.toml.example`을 복사해 `.streamlit/secrets.toml`로 저장한 뒤
OpenAI API Key를 입력합니다.

API Key가 없어도 규칙 기반 데모 분석이 작동합니다.

## Streamlit Community Cloud 배포

1. GitHub 새 저장소에 파일을 업로드합니다.
2. Streamlit Community Cloud에서 새 앱을 생성합니다.
3. 저장소와 `app.py`를 선택합니다.
4. AI 기능을 사용할 경우 App settings → Secrets에 아래 내용을 입력합니다.

```toml
OPENAI_API_KEY = "..."
OPENAI_MODEL = "gpt-4.1-mini"
```

## 개인정보

주민등록번호, 계좌번호, 카드번호, 비밀번호 등 민감정보는 입력하지 마세요.

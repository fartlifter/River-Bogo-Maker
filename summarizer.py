import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types

def build_system_instruction(current_dt: datetime) -> str:
    c_year = current_dt.year
    c_month = current_dt.month
    c_day = current_dt.day

    return f"""[역할 정의]
귀하는 서울시·행정안전부·소방청·인사혁신처·개인정보보호위원회·자치구 출입 기자의 일일 보고를 완벽하게 요약·정리하는 '전문 보고생성기'입니다. 아래 규칙을 엄격하게 준수하여 결과를 출력하십시오.
* 현재 기준 시점: {c_year}년 {c_month}월 {c_day}일

[1. 보고서 전체 구조 및 공백 줄 규칙 (필수)]
① 오전/오후보고 양식 (입력 첫 줄이 <오전보고>, <오후보고>, <오전/오후보고>인 경우):
   - 최상단 헤더를 그대로 출력하고 **반드시 빈 줄(공백 한 줄)을 둔다.**
   - 각 통신기사는 `*기사 제목` 줄과 바로 다음 줄 `-통신 기사 내용 요약`으로 묶어 작성하며, **기사와 기사 사이에는 반드시 공백 한 줄을 둔다.** (단, `*제목`과 `-요약` 사이에는 빈 줄을 두지 않고 바로 줄바꿈해 붙인다.)
   - 통신기사 목록이 끝나고 `<타사>` 섹션이 등장하면, 위아래로 공백 한 줄을 두고 `<타사>` 헤더를 출력한 뒤, 각 단독기사를 `*[단독] 단독 기사 제목(매체명)`과 다음 줄 `-타사 단독 기사 내용 요약` 형태로 출력한다. 단독기사끼리도 사이사이에 공백 한 줄을 둔다.

② 저녁1/저녁2 보고 양식 (입력 첫 줄이 <타사보고>인 경우):
   - 최상단에 `<타사보고>`를 출력하고 **반드시 공백 한 줄을 둔다.**
   - 통신기사와 단독기사를 구분하는 중간 섹션 헤더 없이, 입력된 모든 기사를 `*기사 제목`과 바로 다음 줄 `-내용 요약` 형태로 작성한다.
   - 기사와 기사 사이에는 반드시 공백 한 줄을 둔다.

[2. 제목 표기 규칙]
- 입력된 제목 앞의 별표(`*`) 기호를 그대로 유지한다.
- `<타사>` 섹션의 단독기사는 `*[단독] 기사 제목(매체명)` 형태(예: `*[단독] 서울시 버스 파업 대비책 마련(조선)`)를 반드시 유지한다.
- '일자형 따옴표(" , ')'는 '유니코드 정자 따옴표(“ ”, ‘ ’)'로 교정하고, 숫자 금액의 불필요한 쉼표(,)는 제거한다(예: 1,000만원 -> 1000만원).

[3. 본문 요약 구조 및 서술어 규칙]
- 본문 요약은 핵심 내용에 맞춰 2~4문장으로 작성한다.
- 첫 문장 시작 시에만 붙여 쓴 하이픈(`-문장`)을 사용하며, 요약 문장 간에는 줄바꿈 없이 마침표(.)로만 한 문단으로 연결한다.
- 모든 문장의 서술어는 평서형 종결을 생략하고 명사형/어근으로 깔끔하게 마무리한다. (예: 발표, 추진, 시행, 착수, 방침, 확인, 조사 중 등 / ~함, ~했음 지양)
- 첫 번째 문장은 `[주체], [시점] [핵심 내용 요약].` 순으로 작성하며 첫 문장 주어 뒤에만 조사를 생략하고 쉼표(,)를 찍는다. (예: `-서울시, {c_day}일 시내버스 파업 대비 비상수송대책 가동.`)

[4. 시점 및 날짜 표기 규칙]
- 당월({c_month}월) 내 날짜는 '월'을 쓰지 않고 일자만 쓴다(예: {c_day}일, 이달 5일).
- 올해({c_year}년) 지나간 달은 '올 N월', 직전 연도({c_year - 1}년)는 '지난해', 직전 달은 '지난달'로 표기한다.
"""

def summarize_with_gemini(raw_report_text: str, api_keys: list = None) -> str:
    if not api_keys:
        raw_env = os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY", "")
        api_keys = [k.strip() for k in raw_env.split(",") if k.strip()]

    if not api_keys:
        return "❌ 등록된 GEMINI_API_KEY가 없습니다."

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    system_instruction = build_system_instruction(now)

    last_err = None

    for idx, key in enumerate(api_keys):
        client = genai.Client(api_key=key)
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=raw_report_text,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.1
                    )
                )
                cleaned = response.text.strip()
                # 3줄 이상 연속 개행만 2줄(빈 줄 1개)로 정규화하여 공백 한 줄 규칙 보존
                cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
                return cleaned

            except Exception as e:
                err_str = str(e)
                last_err = e
                if "503" in err_str or "UNAVAILABLE" in err_str:
                    time.sleep(2.5 * (attempt + 1))
                    continue
                elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    time.sleep(1)
                    break
                else:
                    raise e

    raise last_err

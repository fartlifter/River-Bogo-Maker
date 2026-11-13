import streamlit as st
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import os
import re
import html
from collector import (
    KEYWORD_GROUPS, parse_yonhap, parse_newsis, parse_naver_exclusive
)
from summarizer import summarize_with_gemini

# === 보안 인증 정보 로드 ===
def get_secret(key_name, default_val=""):
    try:
        if key_name in st.secrets:
            return st.secrets[key_name]
    except Exception:
        pass
    return os.environ.get(key_name, default_val)

NAVER_CLIENT_ID = get_secret("NAVER_CLIENT_ID", "R7Q2OeVNhj8wZtNNFBwL")
NAVER_CLIENT_SECRET = get_secret("NAVER_CLIENT_SECRET", "49E810CBKY")

raw_keys = get_secret("GEMINI_API_KEYS", get_secret("GEMINI_API_KEY", ""))
GEMINI_API_KEYS = [k.strip() for k in str(raw_keys).split(",") if k.strip()]

st.set_page_config(page_title="법조 단독·통신기사 보고 생성기", layout="wide")

# === st.code 박스 내부 글자 잘림 방지 (자동 줄바꿈 & 복사 아이콘 유지) ===
st.markdown("""
<style>
div[data-testid="stCode"] pre {
    white-space: pre-wrap !important;
    word-break: break-all !important;
    overflow-x: hidden !important;
}
div[data-testid="stCode"] code {
    white-space: pre-wrap !important;
    word-break: break-all !important;
}
</style>
""", unsafe_allow_html=True)

st.title("📰 법조 단독·통신기사 보고 생성기")

now = datetime.now(ZoneInfo("Asia/Seoul"))

if "report_slot" not in st.session_state:
    st.session_state.report_slot = "오전"
if "start_dt" not in st.session_state:
    st.session_state.start_dt = datetime.combine(now.date(), dtime(0, 0)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
if "end_dt" not in st.session_state:
    st.session_state.end_dt = datetime.combine(now.date(), dtime(9, 0)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
if "wire_articles" not in st.session_state:
    st.session_state.wire_articles = []
if "naver_articles" not in st.session_state:
    st.session_state.naver_articles = []
if "gemini_summary" not in st.session_state:
    st.session_state.gemini_summary = ""

def format_highlighted_content(content_text: str, keywords: list) -> str:
    safe_text = html.escape(content_text)
    for kw in keywords:
        if kw:
            safe_text = re.sub(
                f"({re.escape(kw)})",
                r'<mark style="background-color: #fffb91; font-weight: bold;">\1</mark>',
                safe_text
            )
    return safe_text.replace("\n", "<br><br>")

st.subheader("⏱️ 수집 시간대 선택")
col_b1, col_b2, col_b3, col_b4 = st.columns(4)

def set_time_range(slot: str, start_h: int, start_m: int, end_h: int, end_m: int):
    st.session_state.report_slot = slot
    current_time = datetime.now(ZoneInfo("Asia/Seoul"))
    slot_start = datetime.combine(current_time.date(), dtime(start_h, start_m)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
    slot_end = datetime.combine(current_time.date(), dtime(end_h, end_m)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
    if current_time < slot_end:
        slot_end = current_time
    st.session_state.start_dt = slot_start
    st.session_state.end_dt = slot_end

with col_b1:
    if st.button("🌅 오전 (00:00~09:00)", use_container_width=True):
        set_time_range("오전", 0, 0, 9, 0)
with col_b2:
    if st.button("☀️ 오후 (09:00~12:00)", use_container_width=True):
        set_time_range("오후", 9, 0, 12, 0)
with col_b3:
    if st.button("🌇 저녁 (12:00~17:00)", use_container_width=True):
        set_time_range("저녁", 12, 0, 17, 0)
with col_b4:
    if st.button("⚙️ 수동 설정", use_container_width=True):
        st.session_state.report_slot = "수동"

col_d1, col_d2 = st.columns(2)
with col_d1:
    s_date = st.date_input("시작 날짜", value=st.session_state.start_dt.date())
    s_time = st.time_input("시작 시각", value=st.session_state.start_dt.time())
with col_d2:
    e_date = st.date_input("종료 날짜", value=st.session_state.end_dt.date())
    e_time = st.time_input("종료 시각", value=st.session_state.end_dt.time())

start_dt = datetime.combine(s_date, s_time).replace(tzinfo=ZoneInfo("Asia/Seoul"))
end_dt = datetime.combine(e_date, e_time).replace(tzinfo=ZoneInfo("Asia/Seoul"))
st.session_state.start_dt = start_dt
st.session_state.end_dt = end_dt

st.info(f"선택 모드: **{st.session_state.report_slot}보고** | 수집 범위: `{start_dt.strftime('%Y-%m-%d %H:%M')}` ~ `{end_dt.strftime('%Y-%m-%d %H:%M')}`")

selected_groups = st.multiselect("키워드 그룹 선택", options=list(KEYWORD_GROUPS.keys()), default=['법원'])
selected_keywords = [kw for g in selected_groups for kw in KEYWORD_GROUPS[g]]

# === 기사 수집 실행 ===
if st.button("🚀 기사 수집 시작", type="primary", use_container_width=True):
    progress_bar = st.progress(0.0)
    status_text = st.empty()

    def update_progress(val, text):
        progress_bar.progress(min(max(val, 0.0), 1.0))
        status_text.info(text)

    yonhap = parse_yonhap(start_dt, end_dt, selected_keywords, progress_callback=update_progress)
    newsis = parse_newsis(start_dt, end_dt, selected_keywords, progress_callback=update_progress)
    wire = yonhap + newsis
    naver = parse_naver_exclusive(start_dt, end_dt, selected_keywords, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, progress_callback=update_progress)

    progress_bar.empty()
    status_text.empty()

    st.session_state.wire_articles = wire
    st.session_state.naver_articles = naver
    st.session_state.gemini_summary = ""
    st.success(f"✅ 수집 완료: 통신기사 {len(wire)}건 (연합 {len(yonhap)}건 / 뉴시스 {len(newsis)}건) | 단독기사 {len(naver)}건")

# === 기사 리스트: 1단 세로 배치 ===
selected_wires = []
selected_navers = []

st.divider()
st.subheader(f"◆ 통신기사 ({len(st.session_state.wire_articles)}건)")
if st.session_state.wire_articles:
    for idx, art in enumerate(st.session_state.wire_articles):
        matched = art.get('matched_kw', [])
        with st.expander(f"{art['source']} | {art['title']}"):
            checked = st.checkbox("이 기사 선택", key=f"w_chk_{idx}")
            st.markdown(f"[🔗 원문 링크]({art['url']})")
            st.caption(f"{art['datetime'].strftime('%Y-%m-%d %H:%M')} | **일치 키워드:** {', '.join(matched) if matched else '없음'}")
            
            highlighted = format_highlighted_content(art['content'], matched)
            st.markdown(f'<div style="line-height: 1.8;">{highlighted}</div>', unsafe_allow_html=True)
            
            if checked:
                selected_wires.append(art)
else:
    st.caption("수집된 통신기사가 없습니다.")

st.divider()
st.subheader(f"◆ 단독기사 ({len(st.session_state.naver_articles)}건)")
if st.session_state.naver_articles:
    for idx, art in enumerate(st.session_state.naver_articles):
        matched = art.get('matched_kw', [])
        with st.expander(f"[{art['매체']}] {art['title']}"):
            checked = st.checkbox("이 기사 선택", key=f"n_chk_{idx}")
            st.markdown(f"[🔗 원문 링크]({art['url']})")
            st.caption(f"{art['datetime'].strftime('%Y-%m-%d %H:%M')} | **일치 키워드:** {', '.join(matched) if matched else '없음'}")
            
            highlighted = format_highlighted_content(art['content'], matched)
            st.markdown(f'<div style="line-height: 1.8;">{highlighted}</div>', unsafe_allow_html=True)
            
            if checked:
                selected_navers.append(art)
else:
    st.caption("수집된 단독기사가 없습니다.")

# === 공백 줄 없는 보고서 빌더 ===
def build_raw_report(slot, groups, wires, navers):
    if set(groups) == {'법원'}:
        tag = "법원"
    elif set(groups) == {'검찰'}:
        tag = "검찰"
    else:
        tag = "법조"
    
    slot_name = "오전" if slot == "수동" else slot
    lines = [f"<{slot_name}보고>{tag}"]
    
    if slot_name == "오전":
        section_wire, wire_prefix = "【사회면】", "△"
    elif slot_name == "오후":
        section_wire, wire_prefix = "【사회면】", "△추가/"
    else:
        section_wire, wire_prefix = "【2판】", "△NEW/"
        
    if wires:
        lines.append(section_wire)
        for w in wires:
            lines.append(f"{wire_prefix}{w['title']}")
            lines.append(f"-{w['content'].strip()}")
            
    if navers:
        lines.append("【타지】")
        for n in navers:
            lines.append(f"△{n['매체']}/{n['title']}")
            lines.append(f"-{n['content'].strip()}")
            
    return "\n".join(lines).strip()

raw_report_text = build_raw_report(st.session_state.report_slot, selected_groups, selected_wires, selected_navers)

# === 최종 보고서 생성창 (좌우 2열 분할 + 자동 줄바꿈 & 기본 복사 아이콘) ===
st.divider()
st.subheader("📋 최종 보고서 생성 및 복사")

col_t1, col_t2 = st.columns([1, 1])

with col_t1:
    st.markdown("**1️⃣ 원문 취합본 (선택된 기사)**")
    display_raw = raw_report_text if (selected_wires or selected_navers) else "선택된 기사가 없습니다."
    st.code(display_raw, language="markdown")
    st.caption("↗️ 박스 우측 상단의 기본 복사 아이콘을 누르면 전체 복사됩니다.")

with col_t2:
    st.markdown("**2️⃣ Gemini 정제 요약본**")
    if st.button("🤖 선택 기사 Gemini 요약 실행", type="primary", use_container_width=True):
        if not (selected_wires or selected_navers):
            st.warning("요약할 기사를 먼저 체크박스로 선택해주세요.")
        else:
            with st.spinner("Gemini가 정제 요약 중입니다..."):
                try:
                    summary_result = summarize_with_gemini(raw_report_text, GEMINI_API_KEYS)
                    st.session_state.gemini_summary = summary_result
                except Exception as e:
                    st.error(f"요약 중 오류가 발생했습니다: {e}")
                
    display_sum = st.session_state.gemini_summary if st.session_state.gemini_summary else "요약 실행 버튼을 누르면 정제된 결과가 여기에 표시됩니다."
    st.code(display_sum, language="markdown")
    if st.session_state.gemini_summary:
        st.caption("↗️ 박스 우측 상단의 기본 복사 아이콘을 누르면 전체 복사됩니다.")

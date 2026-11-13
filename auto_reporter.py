import os
import sys
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import httpx
from collector import KEYWORD_GROUPS, parse_yonhap, parse_newsis, parse_naver_exclusive
from summarizer import summarize_with_gemini

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        httpx.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk})

def run_auto_report(slot: str):
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    
    if slot == "morning":
        slot_name = "오전"
        start_dt = datetime.combine(now.date(), dtime(0, 0)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
        end_dt = datetime.combine(now.date(), dtime(8, 30)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
        section_wire, wire_prefix = "【사회면】", "△"
    elif slot == "afternoon":
        slot_name = "오후"
        start_dt = datetime.combine(now.date(), dtime(9, 0)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
        end_dt = datetime.combine(now.date(), dtime(11, 30)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
        section_wire, wire_prefix = "【사회면】", "△추가/"
    elif slot == "evening":
        slot_name = "저녁"
        start_dt = datetime.combine(now.date(), dtime(12, 0)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
        end_dt = datetime.combine(now.date(), dtime(16, 30)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
        section_wire, wire_prefix = "【2판】", "△NEW/"
    else:
        raise ValueError("Invalid slot")

    all_keywords = KEYWORD_GROUPS['법원'] + KEYWORD_GROUPS['검찰']
    wire = parse_yonhap(start_dt, end_dt, all_keywords) + parse_newsis(start_dt, end_dt, all_keywords)
    naver = parse_naver_exclusive(start_dt, end_dt, all_keywords, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET)
    
    if not wire and not naver:
        send_telegram_message(f"<{slot_name}보고>법조\n해당 시간대({start_dt.strftime('%H:%M')}~{end_dt.strftime('%H:%M')}) 수집된 기사가 없습니다.")
        return

    lines = [f"<{slot_name}보고>법조"]
    if wire:
        lines.append(section_wire)
        for w in wire:
            lines.append(f"{wire_prefix}{w['title']}")
            lines.append(f"-{w['content'].strip()}")
    if naver:
        lines.append("【타지】")
        for n in naver:
            lines.append(f"△{n['매체']}/{n['title']}")
            lines.append(f"-{n['content'].strip()}")
            
    raw_text = "\n".join(lines).strip()
    summarized_report = summarize_with_gemini(raw_text, GEMINI_API_KEY)
    send_telegram_message(summarized_report)

if __name__ == "__main__":
    slot_arg = sys.argv[1] if len(sys.argv) > 1 else "morning"
    run_auto_report(slot_arg)

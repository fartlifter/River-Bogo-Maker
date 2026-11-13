import html
import re
import time as t
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup

# 1. '서울' 단어가 없어도 무조건 수집할 고유 키워드 (중앙부처 + 서울 고유 23개 자치구 + 공사/노조)
ALWAYS_PASS_KEYWORDS = [
    "서울시", "행정안전부", "행안부", "인사혁신처", "소방청", "개인정보보호위원회", "개보위",
    "서울교통공사", "버스노조",
    "강남구", "강동구", "강북구", "관악구", "광진구", "금천구", "구로구",
    "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구",
    "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중랑구"
]

# 2. 타 광역시(부산·대구·인천·대전·울산)와 이름이 겹쳐 본문에 '서울'이 함께 있어야만 통과시킬 자치구
AMBIGUOUS_GU_KEYWORDS = ["중구", "강서구"]

# 전체 키워드 리스트 (외부 참조용)
TARGET_KEYWORDS = ALWAYS_PASS_KEYWORDS + AMBIGUOUS_GU_KEYWORDS

# 지방 발신 기사 판별용 패턴 (예: (울산=연합뉴스), 【부산=뉴시스】 등)
LOCAL_DATELINE_PATTERN = re.compile(r"[\(\[【]\s*(부산|대구|인천|광주|대전|울산|경기|강원|충북|충남|전북|전남|경북|경남|제주)\s*=")

MEDIA_MAPPING = {
    "chosun": "조선", "joongang": "중앙", "donga": "동아", "hani": "한겨레",
    "khan": "경향", "hankookilbo": "한국", "segye": "세계", "seoul": "서울",
    "kmib": "국민", "munhwa": "문화", "kbs": "KBS", "sbs": "SBS", "mbn.co": "MBN",
    "imnews": "MBC", "jtbc": "JTBC", "ichannela": "채널A", "tvchosun": "TV조선",
    "mk": "매경", "sedaily": "서경", "hankyung": "한경", "news1": "뉴스1", "www.pressian": "프레시안",
    "newsis": "뉴시스", "yna": "연합", "mt": "머투", "weekly": "주간조선", "www.imaeil": "매일신문",
    "biz.chosun": "조선비즈", "fnnews": "파뉴", "etoday.co": "이투데이", "edaily.co": "이데일리", "tf.co": "더팩트",
    "yonhapnewstv.co": "연뉴TV", "ytn.co": "YTN", "nocutnews.co": "노컷", "asiae.co": "아경", "biz.heraldcorp": "헤경",
    "www.sisajournal": "시사저널", "sisajournal.com": "시사저널", "www.ohmynews": "오마이",
    "dailian.co": "데일리안", "ilyo.co": "일요신문", "sisain.co": "시사IN", "lawtimes": "법률신문"
}

def filter_keywords_smart(title: str, content: str) -> list:
    """
    고유 키워드(23개 자치구·부처)는 즉시 매칭하고,
    타 지역 중복 자치구(중구·강서구)는 기사 내 '서울'이 언급된 경우에만 매칭 인정
    """
    full_text = f"{title}\n{content}"
    matched = [kw for kw in ALWAYS_PASS_KEYWORDS if kw in full_text]

    for gu in AMBIGUOUS_GU_KEYWORDS:
        if gu in full_text:
            # 기사에 '서울'이 함께 들어있고, 지방 발신((울산=연합뉴스) 등) 기사가 아닐 때만 서울 중구/강서구로 인정
            if "서울" in full_text and not LOCAL_DATELINE_PATTERN.search(content[:150]):
                matched.append(gu)

    return matched

def get_content(url: str, selector: str) -> str:
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, "html.parser")
        content = soup.select_one(selector)
        if not content:
            return ""

        # 연합뉴스·뉴시스 본문 내 불필요한 기자 구독 버튼, 사진 캡션, 관련뉴스 박스 제거
        for junk in content.select(
            ".writer-zone, .writer-zone01, .byline, .related-zone, .rel-article, "
            ".comp-box, .img-con, .txt-copyright, .ad-box, figure, script, style"
        ):
            junk.decompose()

        text = content.get_text(separator="\n", strip=True)
        # 하단 관련 뉴스 및 저작권 문구 이후 잘라내기
        text = re.split(r"\n(?:관련 뉴스|제보는 카카오톡|<저작권자)", text)[0]
        return text.strip()
    except:
        return ""

def fetch_articles_concurrently(article_list, selector, selected_keywords=None, progress_callback=None, source_name=""):
    results = []
    total = len(article_list)
    if total == 0:
        return results

    with ThreadPoolExecutor(max_workers=25) as executor:
        futures = {executor.submit(get_content, art['url'], selector): art for art in article_list}
        for i, future in enumerate(as_completed(futures)):
            art = futures[future]
            try:
                content = future.result()
                if content:
                    matched = filter_keywords_smart(art['title'], content)
                    if matched:
                        art['content'] = content
                        art['matched_kw'] = matched
                        results.append(art)
            except:
                pass
            if progress_callback:
                progress_callback((i + 1) / total, f"[{source_name}] 본문 키워드 대조 중... ({i+1}/{total}건)")

    results.sort(key=lambda x: x["datetime"], reverse=True)
    return results

def parse_yonhap(start_dt, end_dt, selected_keywords=None, progress_callback=None):
    collected = []
    page = 1
    past_streak = 0
    MAX_PAST_STREAK = 5

    if progress_callback:
        progress_callback(0.0, "🔍 [연합뉴스] 기사 목록 탐색 중...")

    while True:
        url = f"https://www.yna.co.kr/society/all/{page}"
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            if res.status_code != 200:
                break
        except:
            break

        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("ul.list01 > li[data-cid]")
        if not items:
            break

        for item in items:
            cid = item.get("data-cid")
            title_tag = item.select_one(".title01")
            time_tag = item.select_one(".txt-time")
            if not (cid and title_tag and time_tag):
                continue

            try:
                time_str = time_tag.text.strip()
                dt = datetime.strptime(f"{start_dt.year}-{time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Seoul"))
            except:
                continue

            if dt < start_dt:
                past_streak += 1
                if past_streak >= MAX_PAST_STREAK:
                    return fetch_articles_concurrently(collected, "div.story-news.article", selected_keywords, progress_callback, "연합뉴스")
                continue
            else:
                past_streak = 0

            if start_dt <= dt <= end_dt:
                collected.append({
                    "source": "연합뉴스",
                    "datetime": dt,
                    "title": title_tag.text.strip(),
                    "url": f"https://www.yna.co.kr/view/{cid}"
                })

        page += 1

    return fetch_articles_concurrently(collected, "div.story-news.article", selected_keywords, progress_callback, "연합뉴스")

def parse_newsis(start_dt, end_dt, selected_keywords=None, progress_callback=None):
    collected = []
    page = 1
    past_streak = 0
    MAX_PAST_STREAK = 5

    if progress_callback:
        progress_callback(0.0, "🔍 [뉴시스] 기사 목록 탐색 중...")

    while True:
        url = f"https://www.newsis.com/society/list/?cid=10200&scid=10201&page={page}"
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            if res.status_code != 200:
                break
        except:
            break

        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("ul.articleList2 > li")
        if not items:
            break

        for item in items:
            title_tag = item.select_one("p.tit > a")
            time_tag = item.select_one("p.time")
            if not (title_tag and time_tag):
                continue

            match = re.search(r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}", time_tag.text)
            if not match:
                continue

            dt = datetime.strptime(match.group(), "%Y.%m.%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Seoul"))

            if dt < start_dt:
                past_streak += 1
                if past_streak >= MAX_PAST_STREAK:
                    return fetch_articles_concurrently(collected, "div.viewer", selected_keywords, progress_callback, "뉴시스")
                continue
            else:
                past_streak = 0

            if start_dt <= dt <= end_dt:
                collected.append({
                    "source": "뉴시스",
                    "datetime": dt,
                    "title": title_tag.get_text(strip=True),
                    "url": "https://www.newsis.com" + title_tag.get("href", "")
                })

        page += 1

    return fetch_articles_concurrently(collected, "div.viewer", selected_keywords, progress_callback, "뉴시스")

def naver_parse_pubdate(pubdate_str):
    try:
        return datetime.strptime(pubdate_str, "%a, %d %b %Y %H:%M:%S %z")
    except:
        return None

def naver_extract_title_and_body(url):
    try:
        if "n.news.naver.com" not in url:
            return None, None
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if res.status_code != 200:
            return None, None
        soup = BeautifulSoup(res.text, "html.parser")
        title_div = soup.find("div", class_="media_end_head_title")
        content_div = soup.find("div", id="newsct_article")
        title = title_div.get_text(strip=True) if title_div else None
        body = content_div.get_text(separator="\n", strip=True) if content_div else None
        return title, body
    except:
        return None, None

def naver_extract_media_name(url):
    try:
        domain = url.split("//")[-1].split("/")[0]
        parts = domain.split(".")
        composite_key = f"{parts[-3]}.{parts[-2]}" if len(parts) >= 3 else parts[0]
        if composite_key in MEDIA_MAPPING:
            return MEDIA_MAPPING[composite_key]
        for part in reversed(parts):
            if part in MEDIA_MAPPING:
                return MEDIA_MAPPING[part]
        return composite_key.upper()
    except:
        return "기타"

def safe_api_request(url, headers, params, max_retries=3):
    res = None
    for _ in range(max_retries):
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                return res
            t.sleep(0.5)
        except:
            t.sleep(0.5)
    return res

def fetch_and_filter_naver(item_data):
    item, start_dt, end_dt, selected_keywords = item_data
    link = item.get("link")
    if not link or "n.news.naver.com" not in link:
        return None

    pub_dt = naver_parse_pubdate(item.get("pubDate"))
    if not pub_dt or not (start_dt <= pub_dt <= end_dt):
        return None

    title, body = naver_extract_title_and_body(link)
    if not title or not body:
        return None

    if not any(tag in title for tag in ["[단독]", "(단독)", "【단독】", "ⓧ단독", "단독"]):
        return None

    matched_keywords = filter_keywords_smart(title, body)
    if not matched_keywords:
        return None

    media = naver_extract_media_name(item.get("originallink", ""))
    stripped_title = re.sub(r"\[단독\]|\(단독\)|【단독】|ⓧ단독|^단독\s*[:-]?", "", title).strip()
    exclusive_title = f"[단독] {stripped_title}"

    return {
        "매체": media,
        "title": exclusive_title,
        "clean_title": stripped_title,
        "raw_title": title,
        "datetime": pub_dt,
        "content": body,
        "url": link,
        "matched_kw": matched_keywords
    }

def parse_naver_exclusive(start_dt, end_dt, selected_keywords=None, client_id="", client_secret="", progress_callback=None):
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }
    seen_links = set()
    all_articles = []

    steps = list(range(1, 1001, 100))
    total_steps = len(steps)

    for idx, start_index in enumerate(steps, 1):
        if progress_callback:
            progress_callback(idx / total_steps, f"🟡 [단독기사] 수집 중... (현재 {len(all_articles)}건 수집됨)")

        params = {
            "query": "[단독]",
            "sort": "date",
            "display": 100,
            "start": start_index
        }
        res = safe_api_request("https://openapi.naver.com/v1/search/news.json", headers, params)
        if not res or res.status_code != 200:
            break
        items = res.json().get("items", [])
        if not items:
            break

        with ThreadPoolExecutor(max_workers=25) as executor:
            futures = [
                executor.submit(fetch_and_filter_naver, (item, start_dt, end_dt, selected_keywords))
                for item in items
            ]
            for future in as_completed(futures):
                result = future.result()
                if result and result["url"] not in seen_links:
                    seen_links.add(result["url"])
                    all_articles.append(result)

    all_articles.sort(key=lambda x: x["datetime"], reverse=True)
    return all_articles

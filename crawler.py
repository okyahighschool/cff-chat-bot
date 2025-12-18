# crawler/crawler.py

import time
import json
import hashlib
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# -------------------------
# 1. 크롤링 설정
# -------------------------

# 실제로 크롤링을 시작할 학교 홈페이지 URL들
START_URLS = [
    # 교직원 소개 (예시)
    "https://ogya-h.gne.go.kr/ogya-h/main.do",
    # 필요하면 여기 다른 내용 페이지도 추가 가능
]

# 허용할 도메인 (이 도메인 밖 링크는 크롤링하지 않음)
ALLOWED_DOMAIN = "ogya-h.gne.go.kr"

# 최대 크롤링 페이지 수 / 깊이 제한
MAX_PAGES = 100       # 수집할 최대 페이지 수
MAX_DEPTH = 3         # 링크를 최대 몇 단계까지 따라갈지

# 결과 저장 파일
BASE_DIR = Path(__file__).resolve().parent.parent
CRAWL_OUT = BASE_DIR / "data" / "crawled" / "raw_pages.jsonl"

# 요청 간 딜레이 (서버 배려)
REQUEST_DELAY = 0.5

# User-Agent (없으면 접속이 막히는 경우를 방지)
HEADERS = {
    "User-Agent": "SchoolAIBotCrawler/0.1 (local project)"
}

# -------------------------
# 2. 유틸 함수들
# -------------------------

def is_allowed_url(url: str) -> bool:
    """
    도메인 / 스킴 / 파일 타입만 체크해서
    '완전 말도 안 되는 URL'만 걸러냅니다.
    너무 빡세게 막지 않고, 일단 잘 돌아가게 하는 버전.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    # 도메인 체크
    if ALLOWED_DOMAIN not in parsed.netloc:
        return False

    path_lower = parsed.path.lower()

    # 파일 다운로드 등은 제외 (pdf, hwp, xls, 이미지 등)
    blocked_ext = (
        ".pdf", ".hwp", ".hwpx", ".xls", ".xlsx",
        ".doc", ".docx", ".ppt", ".pptx",
        ".jpg", ".jpeg", ".png", ".gif", ".zip"
    )
    if any(path_lower.endswith(ext) for ext in blocked_ext):
        return False

    return True


def fetch_html(url: str) -> str | None:
    """
    해당 URL의 HTML을 가져옵니다. 실패하면 None을 반환합니다.
    """
    try:
        print(f"[FETCH] {url}")
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code != 200:
            print(f"  -> HTTP {res.status_code}, skip")
            return None

        if not res.encoding:
            res.encoding = res.apparent_encoding or "utf-8"
        html = res.text
        return html
    except Exception as e:
        print(f"  -> ERROR: {e}")
        return None


def clean_lines(text: str) -> str:
    """
    본문 텍스트에서 쓸모없는 줄, 잡음 줄을 제거하고 깔끔하게 정리합니다.
    """
    lines = [line.strip() for line in text.splitlines()]
    cleaned_lines: list[str] = []

    for ln in lines:
        if not ln:
            continue

        # 1) 너무 짧은 잡음 줄 제거 (1~2글자 정도)
        if len(ln) <= 2:
            continue

        lower = ln.lower()

        # 2) 주소/저작권/전화 등 매 페이지 반복되는 공통 문구 제거 (예시)
        if "copyright" in lower:
            continue
        if "경상남도" in ln and "교육청" in ln:
            continue
        if "전화" in ln and "-" in ln:
            continue
        if "팩스" in ln and "-" in ln:
            continue
        if "무단 전재" in ln or "재배포 금지" in ln:
            continue

        # 3) 네비게이션 흔적 (예: "홈 > 학교소개 > 교직원 소개")
        if "홈 >" in ln or "home >" in lower:
            continue

        # 4) 이전 줄과 완전히 같은 내용이면 중복 제거
        if cleaned_lines and cleaned_lines[-1] == ln:
            continue

        cleaned_lines.append(ln)

    # 전부 지워버린 경우엔 원본이라도 반환
    if not cleaned_lines:
        return text.strip()

    return "\n".join(cleaned_lines)


def extract_main_text(url: str, html: str) -> tuple[str, str]:
    """
    HTML에서 제목과 '본문 텍스트'를 추출합니다.
    학교 사이트 구조에 맞게 selector를 조정하면서 튜닝할 수 있습니다.
    """
    soup = BeautifulSoup(html, "lxml")

    # 제목 추출: <title> 또는 <h1>
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    else:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            title = h1.get_text(strip=True)

    # 스크립트/스타일/노스크립트 제거
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # 상단/하단/공통 메뉴 영역 제거
    for tag in soup.find_all(["header", "footer", "nav", "aside"]):
        tag.decompose()

    # 사이트 공통 템플릿 영역 (실제 HTML 구조 보고 selector를 추가/수정하면 좋습니다.)
    for selector in [
        "div#gnb",          # 글로벌 메뉴
        "div#lnb",          # 좌측 메뉴
        "div#footer_wrap",  # 하단 전체
        "div.menu",         # 기타 메뉴 블록
    ]:
        for tag in soup.select(selector):
            tag.decompose()

    # 본문이 나올 법한 영역 후보들 (실제 사이트 구조 보고 튜닝)
    main = None
    for selector in [
        "div#contents",
        "div#content",
        "div#container div.contents",
        "div.board_view",
        "div#cms_content",
    ]:
        main = soup.select_one(selector)
        if main:
            break

    # 그래도 못 찾으면 body 전체 사용
    if main is None:
        main = soup.body or soup

    # 줄 바꿈 기준으로 텍스트 추출
    text = main.get_text(separator="\n", strip=True)

    # 라인 단위로 후처리
    cleaned = clean_lines(text)

    return title, cleaned


def extract_links(base_url: str, html: str) -> list[str]:
    """
    페이지 안의 a[href] 링크들을 모아서 절대 URL로 변환한 뒤,
    is_allowed_url로 한 번 더 필터링합니다.
    """
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # 빈 링크, 앵커(#), 자바스크립트 링크는 제외
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue

        abs_url = urljoin(base_url, href)
        if is_allowed_url(abs_url):
            links.append(abs_url)
    return links


def text_hash(text: str) -> str:
    """
    텍스트 내용에 대한 해시값. 변경 감지용으로 사용 가능합니다.
    """
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()


# -------------------------
# 3. 메인 크롤링 루프
# -------------------------

def crawl():
    visited = set()
    out_path = CRAWL_OUT

    # 매번 새로 크롤링한다고 가정하고 결과 파일 초기화
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("", encoding="utf-8")

    queue = deque()

    # START_URLS는 필터 안 거치고 무조건 큐에 넣어줌
    for url in START_URLS:
        print(f"[SEED] {url}")
        queue.append((url, 0))  # (url, depth)

    page_count = 0

    while queue and page_count < MAX_PAGES:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if depth > MAX_DEPTH:
            continue

        # 링크에서 넘어온 것만 필터 적용
        if not is_allowed_url(url):
            print(f"[SKIP] not allowed: {url}")
            continue

        html = fetch_html(url)
        if html is None:
            continue

        title, text = extract_main_text(url, html)
        if not text:
            print(f"[SKIP] empty text: {url}")
            continue

        page_hash = text_hash(text)

        record = {
            "url": url,
            "title": title,
            "depth": depth,
            "text": text,
            "hash": page_hash,
        }

        # JSONL 형식으로 한 줄에 한 페이지씩 저장
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        page_count += 1
        print(f"[SAVE] {url} (depth={depth}, pages={page_count})")

        # 다음에 방문할 링크들 큐에 추가
        links = extract_links(url, html)
        for link in links:
            if link not in visited:
                queue.append((link, depth + 1))

        time.sleep(REQUEST_DELAY)

    print(f"크롤링 완료: {page_count} 페이지 수집, 결과: {out_path}")


if __name__ == "__main__":
    crawl()

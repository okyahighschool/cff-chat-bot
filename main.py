import json
import re
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

STAFF_DB = {}

def load_staff_db():
    global STAFF_DB
    path = Path(__file__).parent.parent / "data" / "staff.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            STAFF_DB = json.load(f)
    else:
        STAFF_DB = {"teachers": [], "staff": []}

load_staff_db()

OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
MODEL_NAME = "qwen2.5:7b"  

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_PATH = BASE_DIR / "data" / "school_knowledge.txt"

def answer_from_staff_db(question: str) -> str | None:
    q = question.strip()
    teachers = STAFF_DB.get("teachers", [])
    staff = STAFF_DB.get("staff", [])

    subject_map = {
        "국어": "국어",
        "수학": "수학",
        "영어": "영어",
        "체육": "체육",
        "물리": "물리",
        "화학": "화학",
        "생명과학": "생명과학",
        "지구과학": "지구과학",
        "사회": "사회",
        "역사": "역사",
        "윤리": "윤리",
        "정보": "정보",
        "중국어": "중국어",
    }

    for keyword, subject in subject_map.items():
        if keyword in q and ("교사" in q or "선생" in q):
            names = [t["name"] for t in teachers if t.get("subject") == subject]
            if names:
                names_str = ", ".join(names)
                return f"{subject} 교사는 {names_str} 선생님입니다."

    # 2) 담임 찾기 (예: "1학년 3반 담임", "1-3반 담임 선생님")
    m = re.search(r"([1-3])학년\s*([1-4])반", q)
    if not m:
        m = re.search(r"([1-3])[- ]\s*([1-4])반?", q)

    if m and "담임" in q:
        grade = m.group(1)
        cls = m.group(2)
        code = f"{grade}-{cls}"
        for t in teachers:
            if t.get("homeroom") == code:
                return f"{grade}학년 {cls}반 담임은 {t['name']} 선생님입니다."
        return f"{grade}학년 {cls}반 담임 정보는 데이터에 없습니다."

    # 3) 부장 / 부서장 찾기 (예: "진로진학부 부장", "교무기획부 부장")
    dept_keywords = [
        "교무기획부",
        "진로진학부",
        "1학년부",
        "2학년부",
        "학력연구부",
        "교육과정부",
        "안전인성부",
        "기숙사부",
    ]
    for dept in dept_keywords:
        if dept in q and "부장" in q:
            for t in teachers:
                if dept in t.get("departments", []) and any(
                    "부장" in r for r in t.get("roles", [])
                ):
                    return f"{dept} 부장은 {t['name']} 선생님입니다."

    # 4) 학교장 / 교감
    if "교장" in q:
        for s in staff:
            if "교장" in s.get("role", ""):
                return f"창녕옥야고등학교 교장은 {s['name']}입니다."

    if "교감" in q:
        for s in staff:
            if "교감" in s.get("role", ""):
                return f"창녕옥야고등학교 교감은 {s['name']}입니다."

    # 여기까지 못 찾으면 None
    return None

# -----------------------------
# 5. FastAPI 기본 설정
# -----------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 필요하면 나중에 도메인 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Question(BaseModel):
    question: str

# -----------------------------
# 6. 학교 지식 파일 로딩
# -----------------------------
def load_knowledge() -> str:
    if KNOWLEDGE_PATH.exists():
        return KNOWLEDGE_PATH.read_text(encoding="utf-8").strip()
    return ""

SCHOOL_KNOWLEDGE = load_knowledge()

# 학교 관련 질문 키워드 (대충 필터)
SCHOOL_KEYWORDS = [
    "창녕옥야고",
    "옥야고",
    "우리학교",
    "학교",
    "교무실",
    "행정실",
    "동아리",
    "학사",
    "학사일정",
    "급식",
    "교복",
    "입학",
    "학생수",
    "시간표",
    "교칙",
    "시설",
    "체육관",
    "도서관",
]

def is_school_question(q: str) -> bool:
    q_lower = q.lower()
    return any(k.lower() in q_lower for k in SCHOOL_KEYWORDS)

# -----------------------------
# 7. 기본 헬스체크
# -----------------------------
@app.get("/")
def read_root():
    return {"status": "ok", "message": "cff_school_ai server running"}

# -----------------------------
# 8. Ollama 대화 호출 함수
# -----------------------------
def call_ollama_chat(user_question: str) -> str:
    knowledge_block = SCHOOL_KNOWLEDGE.strip()

    # 지식이 있으면 학교봇 모드, 없으면 일반 챗봇 모드
    if knowledge_block:
        system_prompt = (
            "당신은 창녕옥야고등학교 안내 챗봇입니다. "
            "반드시 자연스러운 한국어로만 답하십시오. "
            "아래 학교 정보를 최우선으로 참고해 정확히 답하십시오. "
            "학교 정보에 없는 내용은 추측하지 말고 '잘 모르겠습니다'라고 답하십시오. "
            "프롬프트의 라벨이나 학교 정보를 그대로 반복하지 말고, "
            "질문에 대한 최종 답만 간단히 말하십시오.\n\n"
            "학교 정보:\n" + knowledge_block
        )
    else:
        system_prompt = (
            "당신은 친절한 한국어 챗봇입니다. "
            "자연스러운 한국어로만 답하십시오. "
            "모르는 내용은 추측하지 말고 '잘 모르겠습니다'라고 답하십시오."
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_question},
    ]

    res = requests.post(
        OLLAMA_CHAT_URL,
        json={
            "model": MODEL_NAME,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
            },
        },
        timeout=120,
    )

    if res.status_code != 200:
        raise RuntimeError(f"Ollama HTTP {res.status_code}: {res.text}")

    data = res.json()
    answer = (data.get("message", {}).get("content") or "").strip()
    if not answer:
        answer = "(모델이 비어 있는 응답을 보냈습니다.)"
    return answer

# -----------------------------
# 9. /ask 엔드포인트
# -----------------------------
@app.post("/ask")
def ask_ai(payload: Question):
    q = payload.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="question 필드가 비어 있습니다.")

    # 1단계: 교사/담임/부서 같은 '정확한 학교 정보'는 staff.json에서 먼저 찾기
    kb_answer = answer_from_staff_db(q)
    if kb_answer is not None:
        return {"answer": kb_answer}

    # 2단계: 학교 관련 질문인데, 아직 텍스트 기반 SCHOOL_KNOWLEDGE가 없으면 차단
    if is_school_question(q) and not SCHOOL_KNOWLEDGE:
        return {
            "answer": (
                "현재 학교 홈페이지 기반 정보가 아직 준비되지 않았습니다. "
                "학교 관련 질문은 나중에 다시 해 주십시오. "
                "그 외 일반 질문이나 잡담은 가능합니다."
            )
        }

    # 3단계: 나머지는 LLM(qwen 등)에게 넘기기
    try:
        answer = call_ollama_chat(q)
        return {"answer": answer}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {e}")

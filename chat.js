// chat.js

const API_URL = "http://127.0.0.1:8000/ask";

const chatWindow = document.getElementById("chatWindow");
const questionInput = document.getElementById("questionInput");
const sendBtn = document.getElementById("sendBtn");
const statusSpan = document.getElementById("status");

// 자동 스크롤 함수
function scrollToBottom() {
  // DOM에 말풍선이 추가된 뒤에 스크롤이 적용되도록 requestAnimationFrame 사용
  requestAnimationFrame(() => {
    if (!chatWindow) return;
    chatWindow.scrollTop = chatWindow.scrollHeight;
  });
}

// 말풍선 추가 함수
function appendMessage(role, text) {
  const div = document.createElement("div");
  div.classList.add("message", role); // .message.user / .message.bot 같은 식으로 스타일링
  div.textContent = text;
  chatWindow.appendChild(div);
  scrollToBottom();  // 말풍선 추가할 때마다 맨 아래로 이동
}

// 로딩 상태 표시
function setLoading(loading) {
  sendBtn.disabled = loading;
  statusSpan.textContent = loading ? "답변 생성 중입니다..." : "";
}

// 질문 전송 함수
async function sendQuestion() {
  const question = questionInput.value.trim();
  if (!question) return;

  // 사용자 메시지 먼저 출력
  appendMessage("user", question);
  questionInput.value = "";
  setLoading(true);

  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({ question }),
    });

    if (!res.ok) {
      let detail = `HTTP 오류: ${res.status}`;
      try {
        const err = await res.json();
        if (err.detail) detail = err.detail;
      } catch (_) {}
      appendMessage("bot", "서버 오류: " + detail);
      return;
    }

    const data = await res.json();
    const answer = data.answer ?? "(answer 필드가 없습니다.)";
    appendMessage("bot", answer);
  } catch (e) {
    appendMessage("bot", "요청 중 오류가 발생했습니다: " + e);
  } finally {
    setLoading(false);
  }
}

// 버튼 클릭 전송
sendBtn.addEventListener("click", sendQuestion);

// Enter 전송, Shift+Enter 줄바꿈
questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendQuestion();
  }
});

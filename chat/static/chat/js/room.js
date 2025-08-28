// /static/chat/js/room.js

document.addEventListener("DOMContentLoaded", function () {
  console.log("Chat room JavaScript loaded");

  // DOM 요소
  const chatLog = document.querySelector("#chat-log");
  const messageInput = document.querySelector("#chat-message-input");
  const messageForm = document.querySelector("#chat-message-form");
  const passwordForm = document.getElementById("passwordForm");

  // 현재 사용자 정보 (템플릿에서 가져오기)
  let currentUsername = "";
  let roomName = "";

  try {
    const userElement = document.getElementById("user-username");
    const roomElement = document.getElementById("room-name");

    if (userElement && roomElement) {
      currentUsername = JSON.parse(userElement.textContent);
      roomName = JSON.parse(roomElement.textContent);
      console.log("User:", currentUsername, "Room:", roomName);
    }
  } catch (e) {
    console.error("Error parsing user data:", e);
  }

  function scrollToBottom() {
    if (chatLog) {
      setTimeout(() => {
        chatLog.scrollTop = chatLog.scrollHeight;
      }, 100);
    }
  }

  function appendMessage(msgUsername, msgContent, msgTimestamp) {
    if (!chatLog) return;

    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message");

    const bubbleDiv = document.createElement("div");
    bubbleDiv.classList.add("message-bubble");

    const contentP = document.createElement("p");
    contentP.classList.add("message-content");
    contentP.innerHTML = msgContent.replace(/\n/g, "<br>");

    const timestampSpan = document.createElement("span");
    timestampSpan.classList.add("message-timestamp");
    timestampSpan.textContent = msgTimestamp;

    bubbleDiv.appendChild(contentP);
    bubbleDiv.appendChild(timestampSpan);

    if (msgUsername === currentUsername) {
      messageDiv.classList.add("message-own");
    } else {
      const authorSpan = document.createElement("span");
      authorSpan.classList.add("message-author");
      authorSpan.textContent = msgUsername;
      messageDiv.appendChild(authorSpan);
      messageDiv.classList.add("message-other");
    }

    messageDiv.appendChild(bubbleDiv);
    chatLog.appendChild(messageDiv);
    scrollToBottom();
  }

  function formatTimestamp() {
    const now = new Date();
    return now
      .toLocaleTimeString("ko-KR", {
        hour12: true,
        hour: "numeric",
        minute: "2-digit",
      })
      .replace("AM", "오전")
      .replace("PM", "오후");
  }

  // 비밀번호 폼 처리
  if (passwordForm) {
    passwordForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const password = document.getElementById("password").value;
      const errorDiv = document.getElementById("passwordError");
      const csrfToken = passwordForm.querySelector(
        'input[name="csrfmiddlewaretoken"]'
      ).value;

      try {
        const response = await fetch(`/chat/check_password/${roomName}/`, {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRFToken": csrfToken,
          },
          body: `password=${encodeURIComponent(password)}`,
        });

        if (response.ok) {
          const data = await response.json();
          if (data.success) {
            window.location.reload();
          } else {
            errorDiv.style.display = "block";
            errorDiv.textContent = "비밀번호가 올바르지 않습니다.";
          }
        } else {
          throw new Error("Network response was not ok");
        }
      } catch (error) {
        console.error("Password check error:", error);
        errorDiv.style.display = "block";
        errorDiv.textContent = "오류가 발생했습니다.";
      }
    });
  }

  // 채팅 메시지 전송 처리
  if (messageForm && messageInput && chatLog) {
    messageForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const message = messageInput.value.trim();

      if (!message) return;

      const csrfToken = messageForm.querySelector(
        'input[name="csrfmiddlewaretoken"]'
      ).value;

      // 낙관적 UI 업데이트: 내 메시지를 즉시 화면에 표시
      const tempTimestamp = formatTimestamp();
      appendMessage(currentUsername, message, tempTimestamp);

      // 입력창 비우기
      messageInput.value = "";

      try {
        // 서버로 메시지 전송
        const formData = new FormData();
        formData.append("message", message);

        const response = await fetch(`/chat/${roomName}/send/`, {
          method: "POST",
          headers: {
            "X-CSRFToken": csrfToken,
          },
          body: formData,
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        if (result.status !== "ok") {
          throw new Error("Message send failed");
        }
      } catch (error) {
        console.error("Error sending message:", error);
        alert("메시지 전송에 실패했습니다. 다시 시도해주세요.");
      }
    });

    // Enter 키로 전송
    messageInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        messageForm.dispatchEvent(new Event("submit"));
      }
    });

    // 페이지 로드 시 초기화
    scrollToBottom();
    messageInput.focus();
  }

  // 주기적으로 새 메시지 확인 (폴링)
  if (chatLog && roomName) {
    let lastMessageCount = chatLog.children.length;

    setInterval(async () => {
      try {
        const response = await fetch(`/chat/${roomName}/messages/`);
        if (response.ok) {
          const messages = await response.json();
          if (messages.length > lastMessageCount) {
            // 새 메시지가 있으면 페이지 새로고침 (간단한 방법)
            location.reload();
          }
        }
      } catch (error) {
        console.error("Error checking for new messages:", error);
      }
    }, 3000); // 3초마다 확인
  }
});

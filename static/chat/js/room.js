  document.addEventListener("DOMContentLoaded", function () {
    const messages = document.getElementById("messages");
    const messageForm = document.getElementById("messageForm");
    const passwordForm = document.getElementById('passwordForm'); // Password form

    function scrollToBottom() {
      messages.scrollTop = messages.scrollHeight;
    }
    
    if (messages) { // Only if messages element exists (not on password form)
        scrollToBottom(); 
    }


    if (messageForm) {
        messageForm.addEventListener("submit", function (event) {
        event.preventDefault();

        fetch(window.location.href, {
            method: "POST",
            headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]")
                .value,
            },
            body: new URLSearchParams(new FormData(messageForm)),
        })
            .then((response) => {
            if (!response.ok) {
                throw new Error("Network response was not ok");
            }
            return response.text();
            })
            .then(() => {
            messageForm.reset();
            fetchMessages();
            })
            .catch((error) => console.error("Error:", error));
        });

        function fetchMessages() {
        fetch("{% url 'get_messages' room_name=room.name %}")
            .then((response) => response.json())
            .then((messages) => {
            const messagesContainer = document.getElementById("messages");
            messagesContainer.innerHTML = messages
                .map(
                (message) => `
                            <div class="message ${
                                message.user__username === "{{ user.username }}"
                                ? "message-own"
                                : "message-other"
                            }">
                                ${
                                message.user__username !== "{{ user.username }}"
                                    ? `<span class="message-author">${message.user__username}</span>`
                                    : ""
                                }
                                <div class="message-bubble">${message.content}</div>
                            </div>
                        `
                )
                .join("");
            scrollToBottom();
            })
            .catch((error) => console.error("Error:", error));
        }

        setInterval(fetchMessages, 3000);
    }

    if (passwordForm) {
        const passwordError = document.getElementById('passwordError');

        passwordForm.addEventListener('submit', function(event) {
            event.preventDefault();
            passwordError.style.display = 'none';

            const formData = new FormData(passwordForm);
            const roomName = "{{ room.name }}";

            fetch(`/chat/check_password/${roomName}/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': formData.get('csrfmiddlewaretoken')
                },
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.location.href = `/chat/${roomName}/`;
                } else {
                    passwordError.style.display = 'block';
                }
            })
            .catch(error => {
                console.error('Error:', error);
                passwordError.textContent = 'An error occurred. Please try again.';
                passwordError.style.display = 'block';
            });
        });
    }
  });

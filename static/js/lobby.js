const proto = location.protocol === "https:" ? "wss://" : "ws://";
const playerName = sessionStorage.getItem("name");
const avatar = sessionStorage.getItem("avatar");

let ws = null;
let reconnectDelay = 1000;
let gameFinished = false;
let answered = false;
let myAnswer = null;
let currentQuestionId = null;
let questionTimer = null;
let revealTimer = null;
let timerExpiredSentFor = null;
let revealExpiredSentFor = null;

function wsSend(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
    }
}

function clearQuestionTimer() {
    if (questionTimer) {
        clearInterval(questionTimer);
        questionTimer = null;
    }
}

function clearRevealTimer() {
    if (revealTimer) {
        clearInterval(revealTimer);
        revealTimer = null;
    }
}

function setTimerLabel(text) {
    const timer = document.getElementById("timer");
    if (timer) timer.textContent = text;
}

function parseServerDate(value) {
    if (!value) return NaN;

    const timestamp = Date.parse(value);
    if (!Number.isNaN(timestamp)) return timestamp;

    const fallback = Date.parse(`${value}Z`);
    return Number.isNaN(fallback) ? NaN : fallback;
}

function startQuestionTimer(questionId, startedAt, durationSeconds) {
    clearQuestionTimer();
    timerExpiredSentFor = null;

    const startedTimestamp = parseServerDate(startedAt);
    const safeStart = Number.isNaN(startedTimestamp) ? Date.now() : startedTimestamp;
    const deadline = safeStart + durationSeconds * 1000;
    const tick = () => {
        const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        setTimerLabel(`Осталось: ${remaining}с`);

        if (remaining === 0) {
            clearQuestionTimer();
            setTimerLabel("Проверяем ответы...");
            if (timerExpiredSentFor !== questionId) {
                timerExpiredSentFor = questionId;
                wsSend({ type: "timer_expired", question_id: questionId });
            }
        }
    };

    tick();
    questionTimer = setInterval(tick, 250);
}

function startRevealTimer(questionId, revealedAt, revealSeconds) {
    clearRevealTimer();
    revealExpiredSentFor = null;

    const revealedTimestamp = parseServerDate(revealedAt);
    const safeReveal = Number.isNaN(revealedTimestamp) ? Date.now() : revealedTimestamp;
    const deadline = safeReveal + revealSeconds * 1000;
    const tick = () => {
        const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        setTimerLabel(`Следующий вопрос через: ${remaining}с`);

        if (remaining === 0) {
            clearRevealTimer();
            if (revealExpiredSentFor !== questionId) {
                revealExpiredSentFor = questionId;
                wsSend({ type: "reveal_expired", question_id: questionId });
            }
        }
    };

    tick();
    revealTimer = setInterval(tick, 250);
}

function connect() {
    ws = new WebSocket(`${proto}${location.host}/ws/lobby/${window.LOBBY_CODE}/`);

    ws.onopen = () => {
        reconnectDelay = 1000;
        const token = sessionStorage.getItem(`token_${window.LOBBY_CODE}`);
        wsSend({ type: "join_player", name: playerName, avatar, token });
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        if (msg.type === "lobby_update") renderPlayers(msg.players);
        if (msg.type === "question_show") {
            renderQuestion(msg.question, msg.index);
            currentQuestionId = msg.question_id;
            clearRevealTimer();

            if (!msg.revealed_at) {
                startQuestionTimer(msg.question_id, msg.started_at, msg.duration_seconds);
            } else {
                clearQuestionTimer();
                setTimerLabel("Ответ раскрыт");
            }
        }
        if (msg.type === "error") {
            alert(msg.message);
        }
        if (msg.type === "join_denied") {
            alert(msg.message);
            window.location.href = "/";
        }
        if (msg.type === "game_finished") {
            gameFinished = true;
            clearQuestionTimer();
            clearRevealTimer();
            renderLeaderboard(msg.leaderboard);
        }
        if (msg.type === "your_token") {
            sessionStorage.setItem(`token_${window.LOBBY_CODE}`, msg.token);
        }
        if (msg.type === "reveal_answer") {
            revealAnswer(msg.correct_index);
            if (currentQuestionId === msg.question_id) {
                clearQuestionTimer();
                startRevealTimer(msg.question_id, msg.revealed_at, msg.reveal_seconds);
            }
        }
        if (msg.type === "already_answered") {
            answered = true;
            document.querySelectorAll("#options button").forEach((button) => {
                button.disabled = true;
            });
        }
        if (msg.type === "chat_message") appendChatMessage(msg.player, msg.text);
    };

    ws.onclose = () => {
        if (gameFinished) return;
        setTimeout(connect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, 10000);
    };
}

connect();

function renderPlayers(players) {
    const box = document.getElementById("players");
    const filtered = players.filter((player) => !player.is_host);
    const countEl = document.getElementById("player-count");

    box.innerHTML = "";

    if (countEl) {
        countEl.textContent = filtered.length === 0
            ? "Ожидание игроков..."
            : `${filtered.length} ${playerWord(filtered.length)} в комнате`;
    }

    filtered.forEach((player) => {
        const item = document.createElement("div");
        item.className = "player-card";
        item.innerHTML = `
            <div class="player-card-avatar">${player.avatar}</div>
            <div class="player-card-name">${player.name}</div>
        `;
        box.appendChild(item);
    });
}

function playerWord(count) {
    if (count % 100 >= 11 && count % 100 <= 19) return "игроков";
    if (count % 10 === 1) return "игрок";
    if (count % 10 >= 2 && count % 10 <= 4) return "игрока";
    return "игроков";
}

function renderQuestion(question, index) {
    answered = false;
    myAnswer = null;

    document.getElementById("players").classList.add("hidden");
    document.getElementById("leaderboard").classList.add("hidden");

    const box = document.getElementById("question");
    box.classList.remove("hidden");
    box.innerHTML = `
        <div class="text-slate-400 mb-2">Вопрос ${index + 1}</div>
        <div class="text-xl font-bold mb-4">${question.text}</div>
        <div id="options" class="grid grid-cols-1 md:grid-cols-2 gap-3"></div>
        <div id="timer" class="text-right text-slate-400 mt-3"></div>
    `;

    question.options.forEach((option, optionIndex) => {
        const button = document.createElement("button");
        button.className = "answer-option";
        button.textContent = `${optionIndex + 1}. ${option}`;
        button.onclick = () => sendAnswer(optionIndex, button);
        document.getElementById("options").appendChild(button);
    });
}

function renderLeaderboard(list) {
    document.getElementById("question").classList.add("hidden");
    document.getElementById("players").classList.add("hidden");

    const box = document.getElementById("leaderboard");
    const sorted = [...list].sort((a, b) => b.exp - a.exp);

    box.classList.remove("hidden");
    box.innerHTML = `<h2 class="text-2xl font-bold mb-4">Итоги</h2>`;

    sorted.forEach((player, index) => {
        const medal = ["🥇", "🥈", "🥉"][index] || `${index + 1}.`;
        const row = document.createElement("div");
        row.className = "leaderboard-row";
        row.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="text-2xl">${medal}</span>
                <span class="text-2xl">${player.avatar}</span>
                <span class="font-bold">${player.name}</span>
            </div>
            <span class="text-xl font-bold score-text">${player.exp} exp</span>
        `;
        box.appendChild(row);
    });
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function appendChatMessage(player, text) {
    const box = document.getElementById("chat-messages");
    if (!box) return;

    const message = document.createElement("div");
    message.className = "chat-msg";
    message.innerHTML =
        `<span>${escapeHtml(player.avatar)}</span>` +
        `<span class="chat-msg-name">${escapeHtml(player.name)}:</span>` +
        `<span class="chat-msg-text">${escapeHtml(text)}</span>`;

    box.appendChild(message);
    box.scrollTop = box.scrollHeight;
}

function sendChat() {
    const input = document.getElementById("chat-input");
    const text = input.value.trim();

    if (!text) return;

    wsSend({ type: "send_message", text });
    input.value = "";
}

document.getElementById("chat-send").onclick = sendChat;
document.getElementById("chat-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendChat();
});

function revealAnswer(correctIndex) {
    const buttons = document.querySelectorAll("#options button");
    buttons.forEach((button, index) => {
        button.disabled = true;
        if (index === correctIndex) {
            button.classList.remove("selected");
            button.classList.add("correct");
        } else if (index === myAnswer) {
            button.classList.add("wrong");
        }
    });
}

function sendAnswer(index, button) {
    if (answered) return;

    answered = true;
    myAnswer = index;
    wsSend({ type: "answer", option_index: index });

    document.querySelectorAll("#options button").forEach((item) => {
        item.disabled = true;
    });
    button.classList.add("selected");
}

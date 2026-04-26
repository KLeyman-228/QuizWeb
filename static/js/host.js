const proto = location.protocol === "https:" ? "wss://" : "ws://";

let ws = null;
let reconnectDelay = 1000;
let gameFinished = false;
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
        setTimerLabel(`${remaining}с`);

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
        setTimerLabel(`Следующий через ${remaining}с`);

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
        ws.send(JSON.stringify({ type: "join_host" }));
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        if (msg.type === "lobby_update") renderPlayers(msg.players);
        if (msg.type === "error") {
            alert(msg.message);
            document.getElementById("next-btn").classList.add("hidden");
            document.getElementById("start-btn").classList.remove("hidden");
        }
        if (msg.type === "question_show") {
            renderHostQuestion(msg.question, msg.index);
            currentQuestionId = msg.question_id;
            clearRevealTimer();
            document.getElementById("start-btn").classList.add("hidden");
            document.getElementById("next-btn").classList.remove("hidden");

            if (!msg.revealed_at) {
                startQuestionTimer(msg.question_id, msg.started_at, msg.duration_seconds);
            } else {
                clearQuestionTimer();
                setTimerLabel("Ответ раскрыт");
            }
        }
        if (msg.type === "answer_stats") updateStats(msg.stats);
        if (msg.type === "game_finished") {
            gameFinished = true;
            clearQuestionTimer();
            clearRevealTimer();
            document.getElementById("next-btn").classList.add("hidden");
            document.getElementById("start-btn").classList.remove("hidden");
            renderLeaderboard(msg.leaderboard);
        }
        if (msg.type === "reveal_answer") {
            const row = document.getElementById(`opt-${msg.correct_index}`);
            if (row) row.classList.add("correct");

            if (currentQuestionId === msg.question_id) {
                clearQuestionTimer();
                startRevealTimer(msg.question_id, msg.revealed_at, msg.reveal_seconds);
            }
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

document.getElementById("start-btn").onclick = () => {
    wsSend({ type: "start_game" });
};

document.getElementById("next-btn").onclick = () => {
    wsSend({ type: "next_question" });
};

document.getElementById("finish-btn").onclick = () => {
    if (confirm("Завершить игру?")) {
        wsSend({ type: "finish_game" });
    }
};

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

function renderPlayers(players) {
    const box = document.getElementById("players");
    box.innerHTML = "";

    players
        .filter((player) => !player.is_host)
        .forEach((player) => {
            const item = document.createElement("div");
            item.className = "player-card-sm";
            item.innerHTML = `
                <div class="text-2xl">${player.avatar}</div>
                <div class="text-sm">${player.name}</div>
                <div class="text-xs text-muted">${player.exp} exp</div>
            `;
            box.appendChild(item);
        });
}

function renderHostQuestion(question, index) {
    document.getElementById("leaderboard").classList.add("hidden");

    const box = document.getElementById("question");
    box.classList.remove("hidden");
    box.innerHTML = `
        <div class="flex justify-between text-slate-400 mb-2 gap-3">
            <span>Вопрос ${index + 1}</span>
            <span id="timer"></span>
        </div>
        <div class="text-xl font-bold mb-4">${question.text}</div>
        <div id="options" class="space-y-2"></div>
    `;

    const options = document.getElementById("options");
    question.options.forEach((option, optionIndex) => {
        const row = document.createElement("div");
        row.className = "answer-option-host";
        row.id = `opt-${optionIndex}`;
        row.dataset.optionIndex = optionIndex;
        row.innerHTML = `
            <span class="font-bold">${optionIndex + 1}. ${option}</span>
            <span class="text-2xl font-bold score-text" data-count>0</span>
        `;
        options.appendChild(row);
    });
}

function updateStats(stats) {
    document.querySelectorAll("[data-option-index]").forEach((row) => {
        const index = row.dataset.optionIndex;
        const badge = row.querySelector("[data-count]");
        if (badge) badge.textContent = stats[index] || 0;
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

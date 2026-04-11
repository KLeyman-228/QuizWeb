const proto = location.protocol === "https:" ? "wss://" : "ws://";
const playerName = sessionStorage.getItem("name");
const avatar = sessionStorage.getItem("avatar");

let ws = null;
let reconnectDelay = 1000;
let gameFinished = false;

function wsSend(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
    }
}

function connect() {
    ws = new WebSocket(`${proto}${location.host}/ws/lobby/${window.LOBBY_CODE}/`);

    ws.onopen = () => {
        reconnectDelay = 1000;
        const token = sessionStorage.getItem(`token_${window.LOBBY_CODE}`);
        wsSend({type: "join_player", name: playerName, avatar, token});
    };

    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === "lobby_update") renderPlayers(msg.players);
        if (msg.type === "question_show") renderQuestion(msg.question, msg.index);
        if (msg.type === "timer_tick") {
            const t = document.getElementById("timer");
            if (t) t.textContent = `Осталось: ${msg.remaining}с`;
        }
        if (msg.type === "game_finished") {
            gameFinished = true;
            renderLeaderboard(msg.leaderboard);
        }
        if (msg.type === "your_token") {
            sessionStorage.setItem(`token_${window.LOBBY_CODE}`, msg.token);
        }
        if (msg.type === "reveal_answer") {
            revealAnswer(msg.correct_index);
        }
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
    box.innerHTML = "";
    players.filter(p => !p.is_host).forEach(p => {
        const d = document.createElement("div");
        d.className = "bg-slate-800 p-3 rounded text-center";
        d.innerHTML = `<div class="text-3xl">${p.avatar}</div>
                       <div class="font-bold">${p.name}</div>
                       <div class="text-xs text-slate-400">${p.exp} exp</div>`;
        box.appendChild(d);
    });
}

let answered = false;

function renderQuestion(q, idx) {
    answered = false;
    document.getElementById("players").classList.add("hidden");
    document.getElementById("leaderboard").classList.add("hidden");
    const box = document.getElementById("question");
    box.classList.remove("hidden");
    box.innerHTML = `
        <div class="text-slate-400 mb-2">Вопрос ${idx + 1}</div>
        <div class="text-xl font-bold mb-4">${q.text}</div>
        <div id="options" class="grid grid-cols-1 md:grid-cols-2 gap-3"></div>
        <div id="timer" class="text-right text-slate-400 mt-3"></div>
    `;
    q.options.forEach((opt, i) => {
        const b = document.createElement("button");
        b.className = "p-4 bg-slate-700 rounded hover:bg-slate-600 text-left";
        b.textContent = `${i + 1}. ${opt}`;
        b.onclick = () => sendAnswer(i, b);
        document.getElementById("options").appendChild(b);
    });
}

function renderLeaderboard(list) {
    document.getElementById("question").classList.add("hidden");
    document.getElementById("players").classList.add("hidden");
    const box = document.getElementById("leaderboard");
    box.classList.remove("hidden");
    const sorted = [...list].sort((a, b) => b.exp - a.exp);
    box.innerHTML = `<h2 class="text-2xl font-bold mb-4">🏆 Итоги</h2>`;
    sorted.forEach((p, i) => {
        const medal = ["🥇", "🥈", "🥉"][i] || `${i + 1}.`;
        const row = document.createElement("div");
        row.className = "flex items-center justify-between p-3 bg-slate-700 rounded mb-2";
        row.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="text-2xl">${medal}</span>
                <span class="text-2xl">${p.avatar}</span>
                <span class="font-bold">${p.name}</span>
            </div>
            <span class="text-xl font-bold text-blue-400">${p.exp} exp</span>`;
        box.appendChild(row);
    });
}

let myAnswer = null;

function revealAnswer(correctIndex) {
    const buttons = document.querySelectorAll("#options button");
    buttons.forEach((b, i) => {
        b.disabled = true;
        if (i === correctIndex) {
            b.classList.remove("bg-slate-700", "ring-blue-400");
            b.classList.add("bg-green-600");
        } else if (i === myAnswer) {
            b.classList.remove("bg-slate-700");
            b.classList.add("bg-red-600");
        }
    });
}

function sendAnswer(i, btn) {
    if (answered) return;
    answered = true;
    myAnswer = i;
    wsSend({type: "answer", option_index: i});
    document.querySelectorAll("#options button").forEach(x => x.disabled = true);
    btn.classList.add("ring-2", "ring-blue-400");
}

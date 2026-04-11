const proto = location.protocol === "https:" ? "wss://" : "ws://";
const ws = new WebSocket(`${proto}${location.host}/ws/lobby/${window.LOBBY_CODE}/`);

ws.onopen = () => ws.send(JSON.stringify({type: "join_host"}));
ws.onclose = (e) => console.error("WS closed:", e.code, e.reason);
ws.onerror = (e) => console.error("WS error:", e);

ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "error") { alert(msg.message); return; }
    if (msg.type === "lobby_update") renderPlayers(msg.players);
    if (msg.type === "question_show") renderHostQuestion(msg.question, msg.index);
    if (msg.type === "answer_stats") updateStats(msg.stats);
    if (msg.type === "timer_tick") {
        const t = document.getElementById("timer");
        if (t) t.textContent = `${msg.remaining}с`;
    }
    if (msg.type === "game_finished") renderLeaderboard(msg.leaderboard);

    if (msg.type === "reveal_answer") {
    const row = document.getElementById(`opt-${msg.correct_index}`);
    if (row) {
        row.classList.remove("bg-slate-700");
        row.classList.add("bg-green-600");
    }
}
};

function wsSend(data) {
    if (ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(data));
}

document.getElementById("start-btn").onclick = () => {
    wsSend({type: "start_game"});
    document.getElementById("start-btn").classList.add("hidden");
    document.getElementById("next-btn").classList.remove("hidden");
};
document.getElementById("next-btn").onclick = () => {
    wsSend({type: "next_question"});
};
document.getElementById("finish-btn").onclick = () => {
    if (confirm("Завершить игру?")) wsSend({type: "finish_game"});
};

function renderPlayers(players) {
    const box = document.getElementById("players");
    box.innerHTML = "";
    players.filter(p => !p.is_host).forEach(p => {
        const d = document.createElement("div");
        d.className = "bg-slate-800 p-2 rounded text-center";
        d.innerHTML = `<div class="text-2xl">${p.avatar}</div>
                       <div class="text-sm">${p.name}</div>
                       <div class="text-xs text-slate-400">${p.exp} exp</div>`;
        box.appendChild(d);
    });
}


function renderHostQuestion(q, idx) {
    document.getElementById("leaderboard").classList.add("hidden");
    const box = document.getElementById("question");
    box.classList.remove("hidden");
    box.innerHTML = `
        <div class="flex justify-between text-slate-400 mb-2">
            <span>Вопрос ${idx + 1}</span>
            <span id="timer"></span>
        </div>
        <div class="text-xl font-bold mb-4">${q.text}</div>
        <div id="options" class="space-y-2"></div>
    `;
    const opts = document.getElementById("options");
    q.options.forEach((opt, i) => {
        const row = document.createElement("div");
        row.className = "flex items-center justify-between p-4 bg-slate-700 rounded";
        row.id = `opt-${i}`;
        row.innerHTML = `
            <span class="font-bold">${i + 1}. ${opt}</span>
            <span class="text-2xl font-bold text-blue-400" data-count>0</span>
        `;
        opts.appendChild(row);
    });
}


function updateStats(stats) {
    for (let i = 0; i < 4; i++) {
        const row = document.getElementById(`opt-${i}`);
        if (!row) continue;
        const badge = row.querySelector("[data-count]");
        if (badge) badge.textContent = stats[i] || 0;
    }
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
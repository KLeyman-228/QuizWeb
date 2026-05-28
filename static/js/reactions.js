(function () {
    function setupReactionDock() {
        document.querySelectorAll("[data-reaction]").forEach((button) => {
            button.addEventListener("click", () => {
                const emoji = button.dataset.reaction;
                if (!emoji || typeof window.wsSend !== "function") return;

                window.wsSend({ type: "send_reaction", emoji });
                button.classList.add("is-pulsing");
                window.setTimeout(() => button.classList.remove("is-pulsing"), 180);
            });
        });
    }

    function spawnReaction(emoji, player) {
        const stream = document.getElementById("reaction-stream");
        if (!stream || !emoji) return;

        const item = document.createElement("div");
        item.className = "reaction-float";
        item.textContent = emoji;
        item.style.setProperty("--reaction-offset", `${Math.round(Math.random() * 52)}px`);
        item.style.setProperty("--reaction-drift", `${Math.round((Math.random() - 0.5) * 84)}px`);
        item.style.setProperty("--reaction-scale", `${0.92 + Math.random() * 0.24}`);
        if (player && player.name) item.title = player.name;

        stream.appendChild(item);
        item.addEventListener("animationend", () => item.remove(), { once: true });
        window.setTimeout(() => item.remove(), 2600);
    }

    window.spawnReaction = spawnReaction;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setupReactionDock, { once: true });
    } else {
        setupReactionDock();
    }
})();

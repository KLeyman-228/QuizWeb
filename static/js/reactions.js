(function () {
    function getPageRect() {
        const container = document.querySelector(".page-container");
        const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
        const viewportHeight = window.innerHeight || document.documentElement.clientHeight;

        if (!container) {
            return { left: 0, right: viewportWidth, width: viewportWidth, height: viewportHeight };
        }

        const rect = container.getBoundingClientRect();
        return {
            left: Math.max(0, rect.left),
            right: Math.min(viewportWidth, rect.right),
            width: Math.min(viewportWidth, rect.right) - Math.max(0, rect.left),
            height: viewportHeight,
        };
    }

    function positionReactionDock() {
        const dock = document.querySelector(".reaction-dock");
        if (!dock) return;

        const rect = getPageRect();
        const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
        const rightOffset = Math.max(8, viewportWidth - rect.right + 10);
        dock.style.setProperty("--reaction-dock-right", `${rightOffset}px`);
    }

    function setupReactionDock() {
        positionReactionDock();
        window.addEventListener("resize", positionReactionDock);

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

        const rect = getPageRect();
        const randomOffset = Math.round(Math.random() * 52);
        const x = Math.max(12, rect.right - 80 - randomOffset);
        const item = document.createElement("div");
        item.className = "reaction-float";
        item.textContent = emoji;
        item.style.setProperty("--reaction-x", `${x}px`);
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

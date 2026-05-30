(function () {
    const pendingLocalReactionIds = new Set();
    const ignoredEchoReactionIds = new Set();

    function createReactionId() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID();
        }
        return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function rememberIgnoredEcho(reactionId) {
        if (!reactionId) return;

        ignoredEchoReactionIds.add(reactionId);
        window.setTimeout(() => ignoredEchoReactionIds.delete(reactionId), 5000);
    }

    function moveReactionLayerToBody() {
        const stream = document.getElementById("reaction-stream");
        const dock = document.querySelector(".reaction-dock");

        if (stream && stream.parentElement !== document.body) {
            document.body.appendChild(stream);
        }
        if (dock && dock.parentElement !== document.body) {
            document.body.appendChild(dock);
        }
    }

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

        dock.style.setProperty("--reaction-dock-right", "0px");
    }

    function setupReactionDock() {
        moveReactionLayerToBody();
        positionReactionDock();
        window.addEventListener("resize", positionReactionDock);

        document.querySelectorAll("[data-reaction]").forEach((button) => {
            button.addEventListener("click", () => {
                const emoji = button.dataset.reaction;
                if (!emoji) return;

                const reactionId = createReactionId();
                const sent = typeof window.wsSend === "function"
                    ? window.wsSend({ type: "send_reaction", emoji, reaction_id: reactionId }) === true
                    : false;

                if (sent) {
                    pendingLocalReactionIds.add(reactionId);
                    window.setTimeout(() => {
                        if (!pendingLocalReactionIds.has(reactionId)) return;

                        pendingLocalReactionIds.delete(reactionId);
                        rememberIgnoredEcho(reactionId);
                        spawnReaction(emoji);
                    }, 450);
                } else {
                    spawnReaction(emoji);
                }

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

    function receiveReaction(emoji, player, reactionId) {
        if (reactionId && ignoredEchoReactionIds.has(reactionId)) return;

        if (reactionId) {
            pendingLocalReactionIds.delete(reactionId);
        }
        spawnReaction(emoji, player);
    }

    function flushPendingReactions() {
        const queue = window.pendingReactions || [];
        window.pendingReactions = [];

        queue.forEach((reaction) => {
            receiveReaction(reaction.emoji, reaction.player, reaction.reactionId);
        });
    }

    window.spawnReaction = spawnReaction;
    window.receiveReaction = receiveReaction;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            setupReactionDock();
            flushPendingReactions();
        }, { once: true });
    } else {
        setupReactionDock();
        flushPendingReactions();
    }
})();

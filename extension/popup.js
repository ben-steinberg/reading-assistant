// popup.js

let selectedLang = "es";
let readingModeOn = false;

document.addEventListener("DOMContentLoaded", async () => {
    checkIfAlreadyActive();
    checkServerStatus();
    setupButtons();
    loadSavedKey();
});

async function loadSavedKey() {
    const { apiKey } = await chrome.storage.local.get("apiKey");
    if (apiKey) {
        document.getElementById("api-key-input").value = apiKey;
        document.getElementById("key-status").textContent = "key saved ✓";
        document.getElementById("key-status").style.color = "#2ecc71";
    }
}

async function checkIfAlreadyActive() {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab) return;
        chrome.tabs.sendMessage(tab.id, { action: "is_active" }, (res) => {
            if (chrome.runtime.lastError) return;
            if (res && res.active) setButtonActive(true);
        });
    } catch(e) {}
}

async function checkServerStatus() {
    const statusEl = document.getElementById("server-status");
    if (!statusEl) return;
    try {
        await fetch("http://127.0.0.1:8000/dashboard");
        statusEl.textContent = "dashboard server: online ✓";
        statusEl.className = "online";
    } catch(e) {
        statusEl.textContent = "dashboard server: offline";
        statusEl.className = "offline";
    }
}

function setButtonActive(active) {
    readingModeOn = active;
    const btn = document.getElementById("btn-activate");
    if (active) {
        btn.textContent = "stop reading mode";
        btn.style.background = "#e74c3c";
    } else {
        btn.textContent = "start reading mode";
        btn.style.background = "";
    }
}

function setupButtons() {
    document.getElementById("btn-save-key").addEventListener("click", async () => {
        const key = document.getElementById("api-key-input").value.trim();
        const statusEl = document.getElementById("key-status");
        if (!key.startsWith("sk-ant-")) {
            statusEl.textContent = "invalid key format";
            statusEl.style.color = "#e74c3c";
            return;
        }
        await chrome.storage.local.set({ apiKey: key });
        statusEl.textContent = "saved ✓";
        statusEl.style.color = "#2ecc71";
    });

    document.querySelectorAll(".lang-btn:not(.disabled)").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".lang-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            selectedLang = btn.dataset.lang;
        });
    });

    document.getElementById("btn-activate").addEventListener("click", async () => {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab) return;

        if (readingModeOn) {
            chrome.tabs.sendMessage(tab.id, { action: "deactivate" });
            setButtonActive(false);
        } else {
            // fetch user's current level for cheat detection before activating
            chrome.runtime.sendMessage({ action: "get_user_level", language: selectedLang }, (res) => {
                const userLevel = res?.level || null;
                chrome.tabs.sendMessage(tab.id, { action: "activate", language: selectedLang, userLevel }, (res) => {
                    if (chrome.runtime.lastError) {
                        console.error("Error sending message:", chrome.runtime.lastError);
                        return;
                    }
                    if (res && res.success) setButtonActive(true);
                });
            });
        }
    });

    const dashBtn = document.getElementById("btn-dashboard");
    if (dashBtn) {
        dashBtn.addEventListener("click", () => {
            chrome.tabs.create({ url: "http://127.0.0.1:8000/dashboard" });
        });
    }
}
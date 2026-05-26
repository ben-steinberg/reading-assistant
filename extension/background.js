// background.js
// handles translation API calls and saving data to chrome storage
// using mymemory which is free and doesn't need an api key
// also posts click/session data to the local fastapi server for the dashboard

const SERVER = "http://127.0.0.1:8000";

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "translate") {
        translateWord(request.word, request.language)
            .then(result => sendResponse({ success: true, translation: result }))
            .catch(err => sendResponse({ success: false, error: err.message }));
        return true; // need this so the async response works
    }

    if (request.action === "log_click") {
        saveClick(request.word, request.language);
        sendResponse({ success: true });
    }

    if (request.action === "log_session") {
        saveSession(request.data);
        sendResponse({ success: true });
    }

    if (request.action === "get_stats") {
        getStats(request.language).then(stats => sendResponse(stats));
        return true;
    }

    if (request.action === "get_user_level") {
        getUserLevel(request.language).then(level => sendResponse({ level }));
        return true;
    }

    if (request.action === "open_dashboard") {
        chrome.tabs.create({ url: SERVER + "/dashboard" });
        sendResponse({ success: true });
    }

    if (request.action === "detected_language") {
        chrome.storage.local.set({ detectedLanguage: request.language || null });
        sendResponse({ success: true });
    }
});

async function translateWord(word, language) {
    const { apiKey } = await chrome.storage.local.get("apiKey");

    if (apiKey) {
        // use claude haiku for better translations
        const langName = language === "es" ? "Spanish" : language === "fr" ? "French" : "Japanese";
        const response = await fetch("https://api.anthropic.com/v1/messages", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "x-api-key": apiKey,
                "anthropic-version": "2023-06-01",
                "anthropic-dangerous-direct-browser-access": "true"
            },
            body: JSON.stringify({
                model: "claude-haiku-4-5-20251001",
                max_tokens: 60,
                messages: [{
                    role: "user",
                    content: `Translate this ${langName} word to English. Give only the most common meaning as 1-3 words, no explanation. Word: "${word}"`
                }]
            })
        });
        if (!response.ok) throw new Error("claude translation failed");
        const data = await response.json();
        return data.content[0].text.trim();
    }

    // fallback to mymemory if no api key
    const langPair = language === "es" ? "es|en"
                   : language === "fr" ? "fr|en"
                   : language === "ja" ? "ja|en"
                   : `${language}|en`;
    const url = `https://api.mymemory.translated.net/get?q=${encodeURIComponent(word)}&langpair=${langPair}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error("translation failed");
    const data = await response.json();
    if (data.responseStatus !== 200) throw new Error("translation failed");
    return data.responseData.translatedText.trim();
}

async function saveClick(word, language) {
    // save to chrome storage
    const key = "clicks_" + language;
    const stored = await chrome.storage.local.get(key);
    const counts = stored[key] || {};
    counts[word] = (counts[word] || 0) + 1;
    await chrome.storage.local.set({ [key]: counts });

    // also send to fastapi so the dashboard can use it
    try {
        await fetch(`${SERVER}/log_click/${encodeURIComponent(word)}?language=${language}`, { method: "POST" });
    } catch(e) {
        // server probably isn't running, that's fine
    }
}

async function saveSession(sessionData) {
    // save to chrome storage
    const key = "sessions_" + sessionData.language;
    const stored = await chrome.storage.local.get(key);
    const sessions = stored[key] || [];
    sessions.push({
        ...sessionData,
        timestamp: new Date().toISOString()
    });
    if (sessions.length > 200) sessions.splice(0, sessions.length - 200);
    await chrome.storage.local.set({ [key]: sessions });

    // also post to fastapi for the dashboard regression
    try {
        const params = new URLSearchParams({
            percentage: sessionData.missPct,
            difficulty: sessionData.difficulty || "50.0",
            language: sessionData.language,
            suspicious: sessionData.suspicious ? "1" : "0"
        });
        await fetch(`${SERVER}/log_reading_session/?${params}`, { method: "POST" });
    } catch(e) {
        // server probably isn't running, that's fine
    }
}

async function getStats(language) {
    const keys = ["clicks_" + language, "sessions_" + language];
    const result = await chrome.storage.local.get(keys);
    return {
        clicks: result["clicks_" + language] || {},
        sessions: result["sessions_" + language] || []
    };
}

async function getUserLevel(language) {
    // fetch the user's current proficiency level from the server
    // used for cheat detection in content.js
    try {
        const res = await fetch(`${SERVER}/user_level?lang=${language}`);
        if (!res.ok) return null;
        const data = await res.json();
        return data.level || null;
    } catch(e) {
        return null; // server not running, cheat detection will fall back to page difficulty
    }
}
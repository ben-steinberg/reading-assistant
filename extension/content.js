// content.js
// this runs on every page but only does stuff when the user clicks "start reading"

let isActive = false;
let language = "es";
let knownWords = {}; // word -> cefr/jlpt level, loaded from txt files
let clickedWords = new Set();
let totalWordCount = 0;
let pageDifficulty = 50;
let kuromoji_tokenizer = null; // cached tokenizer for japanese, takes a sec to load

// scroll tracking
let maxScrollY = 0;           // furthest point reached
let lastScrollY = 0;          // previous scroll position
let lastScrollTime = 0;       // timestamp of last scroll event
let scrollSuspicious = false; // flagged if scrolling too fast
let allWordSpans = [];        // reference to all word spans for counting up to scroll point
let sessionStartTime = 0;     // when reading mode was activated

// minimum scroll coverage before a session counts
// user needs to have scrolled through at least 50% of the page
const MIN_SCROLL_COVERAGE = 0.5;

// max reasonable scroll speed in px/ms - anything faster is suspicious
// average reader scrolls maybe 500px/sec = 0.5px/ms
const MAX_SCROLL_SPEED = 3.0; // px/ms, generous to avoid false positives

// track time spent at each quarter of the article
// if someone scrolls to 90% but spent <5s per quarter, probably just previewing
let timeAtDepth = { q1: 0, q2: 0, q3: 0, q4: 0 }; // ms spent in each quarter
let lastDepthCheck = 0;
let clickedWordLevels = []; // level scores of clicked words for cheat detection
let userLevel = null; // user's current proficiency score, fetched on activation

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "activate") {
        language = request.language || "es";
        userLevel = request.userLevel || null; // passed from popup via background
        loadWordLists().then(() => {
            if (language === "ja") {
                addStatusBar("Loading Japanese dictionary...");
                loadKuromoji().then(() => {
                    startReading();
                    sendResponse({ success: true });
                }).catch(() => {
                    document.getElementById("ra-statusbar")?.remove();
                    sendResponse({ success: false });
                });
            } else {
                startReading();
                sendResponse({ success: true });
            }
        });
        return true;
    }
    if (request.action === "deactivate") {
        stopReading();
        sendResponse({ success: true });
    }
    if (request.action === "is_active") {
        sendResponse({ active: isActive });
    }
});

// load the word lists - cefr for spanish/french, jlpt for japanese
async function loadWordLists() {
    knownWords = {};

    if (language === "ja") {
        // jlpt levels - N5 is easiest, N1 is hardest
        // map to 0-100 scale: N5=10, N4=25, N3=40, N2=60, N1=75
        const levels = ["N5", "N4", "N3", "N2", "N1"];
        const scores = { N5: 10, N4: 25, N3: 40, N2: 60, N1: 75 };

        for (const level of levels) {
            try {
                const url = chrome.runtime.getURL(`languages/ja/${level}.txt`);
                const res = await fetch(url);
                if (!res.ok) continue;
                const text = await res.text();
                text.split("\n").forEach(line => {
                    const w = line.trim();
                    if (w && !knownWords[w]) {
                        knownWords[w] = { level, score: scores[level] };
                    }
                });
            } catch(e) {}
        }
    } else {
        // cefr levels for spanish and french
        const levels = ["A1", "A2", "B1", "B2", "C1"];
        const scores = { A1: 10, A2: 25, B1: 40, B2: 60, C1: 75 };

        for (let i = 0; i < levels.length; i++) {
            try {
                const url = chrome.runtime.getURL(`languages/${language}/${levels[i]}.txt`);
                const res = await fetch(url);
                if (!res.ok) continue;
                const text = await res.text();
                const lines = text.split("\n");
                lines.forEach((line, index) => {
                    const w = line.trim().toLowerCase();
                    if (!w) return;
                    // first 200 words of A1 are stop words - tag them separately
                    // so function words like "el", "de", "que" don't skew difficulty
                    if (i === 0 && index < 200) {
                        knownWords[w] = { level: "stop", score: null };
                    } else if (!knownWords[w]) {
                        knownWords[w] = { level: levels[i], score: scores[levels[i]] };
                    }
                });
            } catch(e) {}
        }
    }
}

// load kuromoji tokenizer - kuromoji.js is bundled in the extension and
// loaded as a content script before content.js, so window.kuromoji is available
// dict files are also bundled locally so we don't depend on any external CDN
async function loadKuromoji() {
    if (kuromoji_tokenizer) return; // already loaded

    const dictUrl = chrome.runtime.getURL("languages/ja/dict/");

    return new Promise((resolve, reject) => {
        kuromoji.builder({ dicPath: dictUrl }).build((err, tokenizer) => {
            if (err) {
                console.error("kuromoji failed to load:", err);
                reject(err);
            } else {
                kuromoji_tokenizer = tokenizer;
                resolve();
            }
        });
    });
}

function isReadableWord(token) {
    return /[a-zA-ZáéíóúüñÁÉÍÓÚÜÑàâäéèêëîïôöùûüçœæÀÂÄÉÈÊËÎÏÔÖÙÛÜÇŒÆ]/.test(token);
}

function getBaseWord(token) {
    return token.replace(/[^a-zA-ZáéíóúüñÁÉÍÓÚÜÑàâäéèêëîïôöùûüçœæÀÂÄÉÈÊËÎÏÔÖÙÛÜÇŒÆ]/g, "").toLowerCase();
}

// rough difficulty estimate based on word level mix on the page, 0-100 scale
// stop words and unknown words are ignored so only content words count
function estimatePageDifficulty(levelCounts, total) {
    if (total === 0) return 50;

    let weightedSum = 0;
    let knownCount = 0;
    for (const [level, count] of Object.entries(levelCounts)) {
        if (level === "unknown" || level === "stop") continue;
        const scores = { A1: 10, A2: 25, B1: 40, B2: 60, C1: 75, N5: 10, N4: 25, N3: 40, N2: 60, N1: 75 };
        if (scores[level]) {
            weightedSum += scores[level] * count;
            knownCount += count;
        }
    }

    if (knownCount < 5) return 50;
    return weightedSum / knownCount;
}

// count words that are above the scroll cutoff point
// we only count words the user actually scrolled past
function countWordsRead() {
    let count = 0;
    for (const span of allWordSpans) {
        const rect = span.getBoundingClientRect();
        const absTop = rect.top + window.scrollY;
        if (absTop <= maxScrollY + window.innerHeight) {
            count++;
        }
    }
    return count;
}

// scroll handler - tracks max scroll and detects suspicious speed
function handleScroll() {
    const now = Date.now();
    const currentY = window.scrollY;
    const isGoingDown = currentY > lastScrollY;
    const isNewTerritory = currentY > maxScrollY;

    // only flag fast scrolling when going DOWN into unseen content
    // scrolling back up or re-reading already seen content is fine
    if (isGoingDown && isNewTerritory) {
        const delta = currentY - lastScrollY;
        const elapsed = now - lastScrollTime;
        if (elapsed > 0) {
            const speed = delta / elapsed;
            if (speed > MAX_SCROLL_SPEED && delta > 200) {
                scrollSuspicious = true;
                console.log(`Suspicious scroll: ${speed.toFixed(2)}px/ms into new territory`);
            }
        }
    }

    if (currentY > maxScrollY) {
        maxScrollY = currentY;
    }

    // track time spent at current scroll depth
    const now2 = Date.now();
    const elapsed2 = now2 - lastDepthCheck;
    lastDepthCheck = now2;
    const coverage = getScrollCoverage();
    if (coverage < 0.25) timeAtDepth.q1 += elapsed2;
    else if (coverage < 0.5) timeAtDepth.q2 += elapsed2;
    else if (coverage < 0.75) timeAtDepth.q3 += elapsed2;
    else timeAtDepth.q4 += elapsed2;

    // clear suspicion if the user has since shown real reading behavior
    // if they fast-scrolled to preview but then came back and spent real time, that's fine
    if (scrollSuspicious) {
        const quartersWithRealTime = [timeAtDepth.q1, timeAtDepth.q2, timeAtDepth.q3, timeAtDepth.q4]
            .filter(t => t > 10000).length; // 10s per quarter counts as real reading
        const totalTime = timeAtDepth.q1 + timeAtDepth.q2 + timeAtDepth.q3 + timeAtDepth.q4;
        if (quartersWithRealTime >= 2 || totalTime > 60000) {
            scrollSuspicious = false;
            console.log("Suspicion cleared - user demonstrated real reading behavior");
        }
    }

    lastScrollY = currentY;
    lastScrollTime = now;
    updateStatusBar();
}

// tokenize japanese text using kuromoji and wrap each token
function processJapaneseNodes(nodes, levelCounts) {
    nodes.forEach(node => {
        const text = node.textContent;
        if (!text.trim()) return;

        const tokens = kuromoji_tokenizer.tokenize(text);
        const frag = document.createDocumentFragment();

        tokens.forEach(token => {
            const surface = token.surface_form; // the actual text
            const reading = token.reading || ""; // katakana reading
            const baseForm = token.basic_form || surface; // dictionary form

            // only make kanji/kana clickable, skip punctuation and spaces
            const hasJapanese = /[\u3000-\u9fff\uff00-\uffef]/.test(surface);

            if (hasJapanese) {
                totalWordCount++;

                // check if word is in jlpt lists (try base form and surface form)
                const entry = knownWords[baseForm] || knownWords[surface] || null;
                const levelKey = entry ? entry.level : "unknown";
                levelCounts[levelKey] = (levelCounts[levelKey] || 0) + 1;

                const span = document.createElement("span");
                span.className = "ra-word";
                span.dataset.word = baseForm || surface;
                span.dataset.level = levelKey;
                span.dataset.reading = reading;

                // show furigana above kanji
                const hasKanji = /[\u4e00-\u9fff]/.test(surface);
                if (hasKanji && reading) {
                    const ruby = document.createElement("ruby");
                    ruby.textContent = surface;
                    const rt = document.createElement("rt");
                    rt.textContent = reading;
                    ruby.appendChild(rt);
                    span.appendChild(ruby);
                } else {
                    span.textContent = surface;
                }

                span.addEventListener("click", handleClick);
                allWordSpans.push(span);
                frag.appendChild(span);
            } else {
                frag.appendChild(document.createTextNode(surface));
            }
        });

        node.parentNode.replaceChild(frag, node);
    });
}

// tokenize latin-script text by splitting on whitespace
function processLatinNodes(nodes, levelCounts) {
    nodes.forEach(node => {
        const tokens = node.textContent.split(/(\s+)/);
        const frag = document.createDocumentFragment();

        tokens.forEach(token => {
            if (isReadableWord(token)) {
                totalWordCount++;
                const base = getBaseWord(token);
                const entry = knownWords[base] || null;
                const levelKey = entry ? entry.level : "unknown";
                levelCounts[levelKey] = (levelCounts[levelKey] || 0) + 1;

                const span = document.createElement("span");
                span.className = "ra-word";
                span.dataset.word = base;
                span.dataset.level = levelKey;
                span.textContent = token;
                span.addEventListener("click", handleClick);
                allWordSpans.push(span);
                frag.appendChild(span);
            } else {
                frag.appendChild(document.createTextNode(token));
            }
        });

        node.parentNode.replaceChild(frag, node);
    });
}

function startReading() {
    if (isActive) return;
    isActive = true;
    clickedWords = new Set();
    totalWordCount = 0;
    allWordSpans = [];
    clickedWordLevels = [];
    timeAtDepth = { q1: 0, q2: 0, q3: 0, q4: 0 };
    lastDepthCheck = Date.now();

    // reset scroll tracking
    maxScrollY = 0;
    lastScrollY = window.scrollY;
    lastScrollTime = Date.now();
    sessionStartTime = Date.now();
    scrollSuspicious = false;

    document.body.dataset.original = document.body.innerHTML;

    // walk through all text nodes
    const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
        {
            acceptNode(node) {
                const tag = node.parentElement?.tagName?.toLowerCase();
                if (["script", "style", "noscript"].includes(tag)) return NodeFilter.FILTER_REJECT;
                if (tag === "rt") return NodeFilter.FILTER_SKIP;
                if (tag === "ruby") return NodeFilter.FILTER_SKIP;
                if (node.textContent.trim().length < 2) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        }
    );

    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    const levelCounts = {};

    if (language === "ja") {
        processJapaneseNodes(nodes, levelCounts);
    } else {
        processLatinNodes(nodes, levelCounts);
    }

    pageDifficulty = estimatePageDifficulty(levelCounts, totalWordCount);

    // attach scroll listener
    window.addEventListener("scroll", handleScroll, { passive: true });

    // auto-save when user navigates away
    window.addEventListener("beforeunload", handleUnload);

    addStatusBar(); // replaces the loading bar if there was one
}

function handleUnload() {
    // save session automatically when user leaves the page
    saveSession();
}

function getScrollCoverage() {
    // what fraction of the page the user has scrolled through
    // use maxScrollY (furthest point) not current position
    const pageHeight = document.body.scrollHeight - window.innerHeight;
    if (pageHeight <= 0) return 1.0; // page fits in viewport, counts as fully read
    return Math.min(1.0, (maxScrollY + window.innerHeight) / document.body.scrollHeight);
}

function checkClickLevelSuspicion() {
    // compare clicked word levels to the user's proficiency score, not page difficulty
    // e.g. a level-75 reader clicking only A1 words (score 10) is suspicious
    // but a level-30 reader clicking A1 words is totally expected
    if (clickedWordLevels.length < 3) return false; // not enough clicks to judge

    const avgClickScore = clickedWordLevels.reduce((a, b) => a + b, 0) / clickedWordLevels.length;

    // use user's proficiency level as baseline if we have it, otherwise fall back to page difficulty
    const baseline = userLevel !== null ? userLevel : pageDifficulty;

    // only flag if the user is at a high level (>50) and consistently clicking easy words
    // the 30 point gap gives some tolerance - even advanced readers click some easy words
    if (baseline > 50 && avgClickScore < baseline - 30) {
        console.log(`Click level suspicion: avg click score ${avgClickScore.toFixed(0)} vs user level ${baseline.toFixed(0)}`);
        return true;
    }
    return false;
}

function saveSession() {
    const scrollCoverage = getScrollCoverage();

    // don't save if they didn't scroll through at least half the article
    // unless the article is short enough that they could see it all without scrolling
    const pageHeight = document.body.scrollHeight;
    const needsScroll = pageHeight > window.innerHeight * 1.5;
    if (needsScroll && scrollCoverage < MIN_SCROLL_COVERAGE) {
        console.log(`Not enough scroll coverage (${(scrollCoverage * 100).toFixed(0)}%), not saving.`);
        return;
    }

    // check if this looks like a preview scroll - high coverage but very little time spent
    // if they reached 75%+ but averaged less than 5s per quarter, probably just checking length
    if (scrollCoverage > 0.75) {
        const quartersReached = [timeAtDepth.q1, timeAtDepth.q2, timeAtDepth.q3].filter(t => t > 0);
        const avgTimePerQuarter = quartersReached.length > 0
            ? quartersReached.reduce((a, b) => a + b, 0) / quartersReached.length
            : 0;
        if (avgTimePerQuarter > 0 && avgTimePerQuarter < 5000) {
            console.log(`Preview scroll detected (avg ${(avgTimePerQuarter/1000).toFixed(1)}s per quarter), not saving.`);
            return;
        }
    }

    const wordsRead = countWordsRead();

    // don't save if 0% miss rate on a hard article - probably didn't actually read it
    // but allow 0% if the page is easy (difficulty < 40) or if they read very few words
    if (clickedWords.size === 0 && pageDifficulty > 50 && wordsRead > 50) {
        console.log(`Zero clicks on hard content (difficulty ${pageDifficulty.toFixed(0)}), not saving.`);
        return;
    }

    const pct = wordsRead > 0 ? ((clickedWords.size / wordsRead) * 100).toFixed(1) : 0;

    // check if clicks were suspiciously easy for the page level
    const clickSuspicious = checkClickLevelSuspicion();
    const isSuspicious = scrollSuspicious || clickSuspicious;

    chrome.runtime.sendMessage({
        action: "log_session",
        data: {
            language: language,
            url: location.href,
            title: document.title,
            missPct: parseFloat(pct),
            difficulty: pageDifficulty.toFixed(2),
            totalWords: wordsRead,
            clicks: clickedWords.size,
            suspicious: isSuspicious,
            scrollCoverage: parseFloat(scrollCoverage.toFixed(2)),
            durationMs: Date.now() - sessionStartTime
        }
    });
}

function stopReading() {
    if (!isActive) return;
    isActive = false;

    window.removeEventListener("scroll", handleScroll);
    window.removeEventListener("beforeunload", handleUnload);

    saveSession();

    if (document.body.dataset.original) {
        document.body.innerHTML = document.body.dataset.original;
    }
    totalWordCount = 0;
    allWordSpans = [];
}

async function handleClick(e) {
    e.stopPropagation();
    const span = e.currentTarget;
    const word = span.dataset.word; // base form stored in dataset
    // for japanese, get just the surface text not the furigana
    const ruby = span.querySelector("ruby");
    const orig = ruby ? ruby.childNodes[0].textContent.trim() : span.textContent.trim();

    document.querySelectorAll(".ra-tooltip").forEach(t => t.remove());
    document.querySelectorAll(".ra-word--active").forEach(w => w.classList.remove("ra-word--active"));

    span.classList.add("ra-word--active");
    clickedWords.add(word);

    // track the level score of this clicked word for cheat detection
    const levelScores = { A1: 10, A2: 25, B1: 40, B2: 60, C1: 75, N5: 10, N4: 25, N3: 40, N2: 60, N1: 75 };
    const wordLevel = span.dataset.level;
    if (levelScores[wordLevel]) {
        clickedWordLevels.push(levelScores[wordLevel]);
    }

    updateStatusBar();

    chrome.runtime.sendMessage({ action: "log_click", word: word, language: language });

    const tooltip = document.createElement("div");
    tooltip.className = "ra-tooltip";
    tooltip.textContent = "...";
    span.appendChild(tooltip);

    chrome.runtime.sendMessage({ action: "translate", word: orig, language: language }, (res) => {
        if (!document.contains(tooltip)) return;
        if (res && res.success) {
            tooltip.textContent = res.translation;
        } else {
            tooltip.textContent = "couldn't translate";
        }
    });

    setTimeout(() => {
        document.addEventListener("click", () => {
            tooltip.remove();
            span.classList.remove("ra-word--active");
        }, { once: true });
    }, 0);
}

function addStatusBar(loadingMsg = null) {
    document.getElementById("ra-statusbar")?.remove();

    const bar = document.createElement("div");
    bar.id = "ra-statusbar";
    const langName = language === "es" ? "Spanish" : language === "fr" ? "French" : "Japanese";

    if (loadingMsg) {
        bar.innerHTML = `<span>📖 Reading Assistant</span><span>${loadingMsg}</span>`;
    } else {
        bar.innerHTML = `
            <span>📖 Reading Assistant</span>
            <span>clicked: <b id="ra-count">0</b> words (<b id="ra-pct">0%</b>)</span>
            <span id="ra-timer" style="color:#aaa;font-size:11px;"></span>
            <span id="ra-scroll-warning" style="color:#e74c3c;display:none;">⚠ fast scroll</span>
            <span style="margin-left:auto">${langName}</span>
        `;
        // update the countdown every second
        const timerInterval = setInterval(() => {
            if (!isActive) { clearInterval(timerInterval); return; }
            updateStatusBar();
        }, 1000);
    }
    document.body.prepend(bar);
}

function updateStatusBar() {
    const countEl = document.getElementById("ra-count");
    const pctEl = document.getElementById("ra-pct");
    const warningEl = document.getElementById("ra-scroll-warning");
    const timerEl = document.getElementById("ra-timer");
    if (!countEl) return;

    const wordsRead = countWordsRead();
    countEl.textContent = clickedWords.size;
    if (wordsRead > 0) {
        pctEl.textContent = ((clickedWords.size / wordsRead) * 100).toFixed(1) + "%";
    }

    // show scroll coverage progress
    if (timerEl) {
        const coverage = getScrollCoverage();
        const pageHeight = document.body.scrollHeight;
        const needsScroll = pageHeight > window.innerHeight * 1.5;
        if (needsScroll && coverage < MIN_SCROLL_COVERAGE) {
            timerEl.textContent = `scroll: ${(coverage * 100).toFixed(0)}% (need 50%)`;
            timerEl.style.color = "#aaa";
        } else {
            timerEl.textContent = "✓ reading tracked";
            timerEl.style.color = "#2ecc71";
        }
    }

    if (warningEl && scrollSuspicious) {
        warningEl.style.display = "inline";
    }
}
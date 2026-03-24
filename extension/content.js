
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "start_reading") {
        console.log("Reading Mode activating...");
        activateReadingMode();
    }
});

async function activateReadingMode() {
    try {
        const rawText = document.body.innerText; 

        const response = await fetch(`http://127.0.0.1:8000/process_text?text=${encodeURIComponent(rawText)}`);
        const processedData = await response.json();

        document.body.innerHTML = '<div id="reading-container" style="padding:50px; max-width:800px; margin:0 auto; line-height:4;"></div>';
        const container = document.getElementById('reading-container');

        processedData.forEach(word => {
            const span = document.createElement('span');
            span.className = `word-block state-0`;
            span.dataset.isKanji = word.is_kanji;
            
            span.innerHTML = `
                <ruby>${word.orig}<rt>${word.hira}</rt></ruby>
                <span class="eng-hint">${word.english}</span>
            `;

            span.onclick = () => {
                let currentState = parseInt(span.getAttribute('data-state') || "0");
                let nextState = word.is_kanji ? (currentState + 1) % 3 : (currentState === 0 ? 2 : 0);
                
                span.setAttribute('data-state', nextState);
                span.className = `word-block state-${nextState}`;

                // Log click to Python
                fetch(`http://127.0.0.1:8000/log_click/${encodeURIComponent(word.orig)}`, { method: 'POST' });
            };

            container.appendChild(span);
            container.appendChild(document.createTextNode(' ')); // Space between words
        });
    } catch (error) {
        console.error("Error in Reading Mode:", error);
    }
}

// Keep your passive features
window.onload = highlightSuggestions;
// ... (Your existing mouseup listener and highlightSuggestions function below)

document.addEventListener('mouseup', () => {
    const selectedText = window.getSelection().toString().trim();
    
    if (selectedText.length > 0 && selectedText.length < 10) {
        console.log("Logging word:", selectedText);
        
        fetch('http://127.0.0.1:8000/log_click', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ word: selectedText })
        })
        .then(response => response.json())
        .catch(err => console.error("Could not log word. Is FastAPI running?"));
    }
});

async function highlightSuggestions() {
    try {
        const response = await fetch('http://127.0.0.1:8000/api/suggestions');
        const data = await response.json();
        const wordsToFind = data.suggestions; // suggested words

        const bodyText = document.body.innerHTML;
        let newHtml = bodyText;

        wordsToFind.forEach(word => {
            const regex = new RegExp(word, 'g');
            newHtml = newHtml.replace(regex, `<span style="background-color: #f1c40f; font-weight: bold; border-radius: 3px;">${word}</span>`);
        });

        document.body.innerHTML = newHtml;
    } catch (err) {
        console.log("Dashboard suggestions not available yet.");
    }
}


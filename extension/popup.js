document.addEventListener('DOMContentLoaded', function() {
    fetch('http://127.0.0.1:8000/dashboard')
        .then(() => {
            document.getElementById('status').innerText = "Server: Online";
        })
        .catch(() => {
            const statusDiv = document.getElementById('status');
            statusDiv.innerText = "Server: Offline";
            statusDiv.style.color = "red";
        });

    document.getElementById('open-dashboard').addEventListener('click', function() {
        chrome.tabs.create({ url: 'http://127.0.0.1:8000/dashboard' });
    });

    document.getElementById('start-reading').addEventListener('click', async () => {
        const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
        if (tab) {
            chrome.tabs.sendMessage(tab.id, { action: "start_reading" });
        }
    });
});
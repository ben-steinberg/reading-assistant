import numpy as np 
from jreadability import compute_readability
import pykakasi
import re
from deep_translator import GoogleTranslator
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
import os 
import json
from pathlib import Path
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from data_analysis import calculate_user_level, show_level, give_suggested_words, to_websites, get_timeline, get_click_counts, log_level_history

kks = pykakasi.kakasi()
app = FastAPI()
base_dir = os.path.dirname(os.path.abspath(__file__))
current_dir = Path(__file__).parent.absolute()
templates = Jinja2Templates(directory=str(current_dir))

# one-time migration: copy old click_counts.json into click_counts_ja.json
# so existing japanese data still shows up on the dashboard
old_clicks = os.path.join(base_dir, "click_counts.json")
new_clicks = os.path.join(base_dir, "click_counts_ja.json")
if os.path.exists(old_clicks) and not os.path.exists(new_clicks):
    import shutil
    shutil.copy(old_clicks, new_clicks)
    print("migrated click_counts.json -> click_counts_ja.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_processed_data_simple(text):
    result = kks.convert(text)
    processed = []
    for item in result:
        orig = item['orig']
        is_kanji = bool(re.search(r'[一-龯]', orig))
        processed.append({
            "orig": orig,
            "hira": item['hira'],
            "is_kanji": is_kanji,  
            "english": ""
        })
    return processed

@app.get("/")
def read_root(request: Request):
    path = os.path.join(base_dir, "little_prince.txt")
    if not os.path.exists(path):
        article_text = "水族館には、生き物の世話をする人、「飼育員」がいます。"
    else:
        with open(path, "r", encoding="utf-8") as f:
            article_text = f.read()

    data = get_processed_data_simple(article_text)
    total_words = len(data)
    score = compute_readability(article_text)
    difficulty = show_level(score)
    
    return templates.TemplateResponse(request, "index.html", {
        "words": data,
        "total_words": total_words,
        "difficulty": difficulty,
        "difficulty_score": score
    })

@app.get("/get_word_details/{word}")
async def get_word_details(word: str):
    english = ""
    if re.search(r'[一-龯]', word) or any(ord(c) > 127 for c in word):
        english = GoogleTranslator(source='ja', target='en').translate(word)
    
    log_file = os.path.join(base_dir, "click_counts.json")
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            counts = json.load(f)
    else:
        counts = {}
    counts[word] = counts.get(word, 0) + 1
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(counts, f, ensure_ascii=False, indent=4)
        
    return {"english": english}

@app.post("/log_click/{word}")
async def log_click(word: str, language: str = "ja"):
    # save to a language-specific file so the dashboard can separate them
    log_file = os.path.join(base_dir, f"click_counts_{language}.json")

    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            counts = json.load(f)
    else:
        counts = {}

    counts[word] = counts.get(word, 0) + 1

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(counts, f, ensure_ascii=False, indent=4)
        
    return {"status": "success", "word": word, "count": counts[word]}

@app.get("/api/suggestions")
async def get_suggestions_api(language: str = "ja"):
    user_level = calculate_user_level(language)
    suggested_words = give_suggested_words(user_level, language)
    return {"suggestions": suggested_words}

@app.post("/log_reading_session/")
async def log_session(percentage: float, difficulty: str, language: str = "ja", suspicious: str = "0"):
    log_file = os.path.join(base_dir, "reading_history.json")
    
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            history = json.load(f)
    else:
        history = []

    # convert japanese jreadability score (1-7, lower=harder) to 0-100
    # only apply if the score is actually on the old 1-7 scale
    # sessions from the extension already send 0-100 so don't convert those
    if language == "ja":
        try:
            d = float(difficulty)
            if 0 < d <= 7.0:
                difficulty = str(round((8.0 - d) / 7.0 * 90, 1))
            # if d is already on 0-100 scale (from extension), leave it alone
        except:
            pass

    session_data = {
        "difficulty": difficulty,
        "percentage": percentage,
        "language": language,
        "suspicious": suspicious == "1",
        "timestamp": str(datetime.now()) 
    }

    history.append(session_data)

    with open(log_file, "w") as f:
        json.dump(history, f, indent=4)

    # update level history now that we have new session data
    # do this in background so it doesn't slow down the response
    try:
        log_level_history(language)
    except Exception as e:
        print(f"Level history update skipped: {e}")

    return {"status": "success", "session": session_data}

@app.get("/user_level")
async def get_user_level(lang: str = "es"):
    try:
        level = calculate_user_level(lang)
        return {"level": round(float(level), 2)}
    except Exception as e:
        return {"level": None}

@app.get("/dashboard")
async def get_dashboard(request: Request, lang: str = "es"):
    # try to calculate level - need at least 5 sessions
    try:
        user_level = calculate_user_level(lang)
        suggested_words = give_suggested_words(user_level, lang)
        websites = to_websites(user_level, suggested_words, lang)
    except Exception as e:
        print("Not enough data yet:", e)
        user_level = 0
        suggested_words = []
        websites = []

    timeline_levels, timeline_times = get_timeline(lang)

    formatted_times = []
    for time_str in timeline_times:
        clean_time = time_str.split('.')[0][:-8]
        formatted_times.append(clean_time)
    
    click_counts = get_click_counts(lang)

    return templates.TemplateResponse(request, "dashboard.html", {
        "lang": lang,
        "level": round(user_level, 2) if user_level else 0,
        "level_name": show_level(user_level) if user_level else "Not enough data yet",
        "words": suggested_words,
        "articles": websites,
        "click_counts": click_counts,
        "timeline_levels": timeline_levels,
        "timeline_times": formatted_times
    })
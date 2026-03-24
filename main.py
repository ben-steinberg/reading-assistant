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
from data_analysis import calculate_user_level, show_level, give_suggested_words, to_websites, get_timeline

kks = pykakasi.kakasi()
app = FastAPI()
base_dir = os.path.dirname(os.path.abspath(__file__))
current_dir = Path(__file__).parent.absolute()
templates = Jinja2Templates(directory=str(current_dir))

from fastapi import FastAPI, Request
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_furigana(text):
    result = kks.convert(text)
    # This will return a list like: [{'orig': '漢字', 'hira': 'かんじ', ...}]
    return result

def get_kanji_groups(text):
    kanji_pattern = re.compile(r'[一-龯]+')
    
    groups = []
    for match in kanji_pattern.finditer(text):
        groups.append(match.group())

    return groups

def generate_ruby_html(text):
    kks = pykakasi.kakasi()
    result = kks.convert(text)
    
    html_output = ""
    
    for item in result:
        orig = item['orig']
        hira = item['hira']
        
        # Check if the original word contains any Kanji
        if re.search(r'[一-龯]', orig):
            # Wrap in ruby tags if it's Kanji
            html_output += f'<ruby class="kanji-block" onclick="this.classList.toggle(\'revealed\')">{orig}<rt>{hira}</rt></ruby>'
        else:
            # Just add regular kana/punctuation as normal text
            html_output += f'<span>{orig}</span>'
            
    return html_output

def show_eng_translation(word):
    translated = GoogleTranslator(source='en', target='ja').translate(word)
    return translated


app = FastAPI()
kks = pykakasi.kakasi()

@app.get("/process_text")
def process_text(text: str):
    tokens = kks.convert(text)
    processed_data = []
    
    for item in tokens:
        orig = item['orig']
        # Furigana
        hira = item['hira']
        
        # English 
        english = ""
        if re.search(r'[一-龯]', orig): 
            english = GoogleTranslator(source='ja', target='en').translate(orig)
        
        processed_data.append({
            "orig": orig,
            "hira": hira,
            "english": english,
            "is_kanji": bool(re.search(r'[一-龯]', orig))
        })
        
    return processed_data

def get_processed_data(text):
    result = kks.convert(text)
    processed = []
    for item in result:
        orig = item['orig']
        is_kanji = bool(re.search(r'[一-龯]', orig))
        
        english = GoogleTranslator(source='ja', target='en').translate(orig) if orig.strip() else ""
        
        processed.append({
            "orig": orig,
            "hira": item['hira'],
            "is_kanji": is_kanji,  
            "english": english
        })
    return processed

@app.get("/")
def read_root(request: Request):
    # initial text
    article_text = "水族館には、生き物の世話をする人、「飼育員」がいます。飼育員は一人ひとり、魚や動物など担当が決まっています。そして、どの飼育員にも3つの大きな仕事があります。1つ目は掃除をすることです。水槽の窓をきれいに拭いたり、水槽の中のゴミを片付けたりします。2つ目は餌の準備をすることです。これを「調餌」と言います。そして、3つ目はその餌をあげることです。餌をあげることを「給餌」と言います。この3つの掃除、調餌、給餌を「さんじ（3じ）」と言って、毎日繰り返します。それから、「さんじ」のほかの時間に会議などもしますから、飼育員はとても忙しいです。ですから、飼育員になるためには体力もとても大切だそうです。"
    
    data = get_processed_data(article_text)
    total_words = len(data)
    difficulty = show_level(compute_readability(article_text))
    score = compute_readability(article_text)
    
    # Send the data to index.html
    return templates.TemplateResponse("index.html", {"request": request, "words": data, "total_words": total_words, "difficulty" : difficulty, "difficulty_score": score})

@app.post("/log_click/{word}")
async def log_click(word: str):
    log_file = "click_counts.json"
    
    # 1. Load existing counts
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            counts = json.load(f)
    else:
        counts = {}

    # 2. Update the count for this specific word
    counts[word] = counts.get(word, 0) + 1

    # 3. Save it back to the file
    with open(log_file, "w") as f:
        json.dump(counts, f, ensure_ascii=False, indent=4)
        
    return {"status": "success", "word": word, "count": counts[word]}

@app.get("/api/suggestions")
async def get_suggestions_api():
    user_level = calculate_user_level()
    suggested_words = give_suggested_words(user_level)
    
    return {"suggestions": suggested_words}


@app.post("/log_reading_session/")
async def log_session(percentage: float, difficulty: str):
    log_file = "reading_history.json"
    
    # Load existing data
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            history = json.load(f)
    else:
        history = []

    session_data = {
        "difficulty": difficulty,
        "percentage": percentage,
        "timestamp": str(datetime.now()) 
    }

    history.append(session_data)

    with open(log_file, "w") as f:
        json.dump(history, f, indent=4)

    return {"status": "success", "session": session_data}

@app.get("/dashboard")
async def get_dashboard(request: Request):
    # 1. Run your existing logic
    user_level = calculate_user_level()
    suggested_words = give_suggested_words(user_level)
    websites = to_websites(user_level, suggested_words)
    timeline_levels, timeline_times = get_timeline()

    formatted_times = []
    for time in timeline_times:
        clean_time = time.split('.')[0][:-8]
        formatted_times.append(clean_time)
    
    # 2. Get click data for the Heatmap
    with open("click_counts.json", "r", encoding="utf-8") as f:
        click_counts = json.load(f)

    # 3. Render the page
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "level": round(user_level, 2),
        "level_name": show_level(user_level),
        "words": suggested_words,
        "articles": websites,
        "click_counts": click_counts,
        "timeline_levels": timeline_levels,
        "timeline_times": formatted_times
    })
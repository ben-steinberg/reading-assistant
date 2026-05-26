import pandas as pd
import matplotlib
matplotlib.use('Agg')  # prevents mac from opening a gui window every time we save a plot
import matplotlib.pyplot as plt
import json
import os
import numpy as np 
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
import requests
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def show_level(score):
    if score >= 75:
        return "Advanced"
    elif score >= 55:
        return "Upper Intermediate"
    elif score >= 40:
        return "Intermediate"
    elif score >= 25:
        return "Elementary"
    else:
        return "Beginner"

def calculate_user_level(language="ja"):
    history_path = os.path.join(BASE_DIR, "reading_history.json")
    with open(history_path, "r", encoding="utf-8") as f:
        all_history = json.load(f)

    # filter by language - old entries without a language field default to japanese
    # also filter out sessions flagged as suspicious (fast scrolling)
    history = [r for r in all_history if r.get("language", "ja") == language and not r.get("suspicious", False)]

    # old japanese sessions used jreadability's 1-7 scale (lower = harder)
    # convert them to 0-100 (higher = better) so everything is consistent
    def normalize_difficulty(entry):
        d = float(entry["difficulty"])
        if language == "ja" and 0 < d <= 7.0:
            # convert old jreadability 1-7 scale (lower=harder) to 0-100
            return round((8.0 - d) / 7.0 * 90, 1)
        return d  # already on 0-100 scale

    difficulty_array = []
    if len(history) >= 5: 
        for reading in history: 
            difficulty_array.append({normalize_difficulty(reading): reading["percentage"]})

    reading_to_df = []
    for entry in difficulty_array:
        for level, percent in entry.items():
            reading_to_df.append({"level_of_reading": level, "miss_percent": percent})

    reading_df = pd.DataFrame(reading_to_df)

    X = reading_df[['miss_percent']] 
    y = reading_df['level_of_reading']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, random_state=0)

    lin_reg = LinearRegression()
    lin_reg.fit(X_train, y_train)

    # 3% i looked it up seems to be like the percentage we want to be at
    # based on what ai thinks of my reading level, 1.75 is prob the best
    target_miss_rate = np.array([[1.75]]) 
    predicted_level = lin_reg.predict(target_miss_rate)

    # clamp to 0-100
    predicted_level[0] = max(0, min(100, predicted_level[0]))

    # might keep this and show like oh heres where we got that your reading level is ___ etc.
    min_percent = 0
    max_percent = 50
    plt.figure()
    plt.xlim(min_percent, max_percent)
    plt.ylim(0, 100)
    extended_percents = np.linspace(min_percent, max_percent, 20).reshape(-1, 1)
    percent_predictions = lin_reg.predict(extended_percents)
    percent_predictions = np.clip(percent_predictions, 0, 100)
    plt.plot(extended_percents.flatten(), percent_predictions, color='red', label='Best Fit Line')
    plt.plot(3.0, predicted_level[0], 'go', color='green', label='Your Level at 3% Miss Rate')
    plt.scatter(X, y, color='blue', label='Data Points')
    plt.xlabel('Miss Percentage')
    plt.ylabel('Proficiency Score (0-100)')
    plt.title(f'Reading Level vs Miss Percentage ({language.upper()})')
    plt.legend()
    plot_path = os.path.join(BASE_DIR, f'reading_level_fit_{language}.png')
    plt.savefig(plot_path)
    plt.close()

    # don't log level history here - only log when a real session is saved
    # otherwise every dashboard visit adds a new data point and skews the timeline

    return predicted_level[0]

def give_suggested_words(level, language="ja"):
    # get the most clicked words for this language
    clicks_file = os.path.join(BASE_DIR, f"click_counts_{language}.json")

    if not os.path.exists(clicks_file):
        return []

    with open(clicks_file, "r", encoding="utf-8") as f:
        clicked_words = json.load(f)

    sorted_clicked = dict(sorted(clicked_words.items(), key=lambda item: item[1], reverse=True))

    if language == "ja":
        path = os.path.join(BASE_DIR, "jlpt_levels")
        levels_list = []
        for i in range(5):
            level_words = []
            file_path = os.path.join(path, f"N{i+1}.txt")
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        level_words.append(line.strip())
            levels_list.append(level_words)

        suggested_words = []
        if level < 30:
            for word in sorted_clicked.keys(): 
                if word in levels_list[4] or word in levels_list[3]:
                    suggested_words.append(word)
        elif level < 55:
            for word in sorted_clicked.keys(): 
                if word in levels_list[2] or word in levels_list[1]:
                    suggested_words.append(word)
        else:
            for word in sorted_clicked.keys(): 
                if word in levels_list[1] or word in levels_list[0]:
                    suggested_words.append(word)

    else:
        # spanish/french - use cefr levels
        lang_folder = "es" if language == "es" else "fr"
        path = os.path.join(BASE_DIR, "extension", "languages", lang_folder)
        cefr_levels = {}
        for lvl in ["A1", "A2", "B1", "B2", "C1"]:
            file_path = os.path.join(path, f"{lvl}.txt")
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        w = line.strip().lower()
                        if w:
                            cefr_levels[w] = lvl

        # suggest words at the right level based on the user's score
        if level < 30:
            target_levels = ["A1", "A2"]
        elif level < 55:
            target_levels = ["A2", "B1"]
        else:
            target_levels = ["B1", "B2"]

        suggested_words = []
        for word in sorted_clicked.keys():
            if cefr_levels.get(word.lower()) in target_levels:
                suggested_words.append(word)

    final_suggestions = suggested_words[:5]
    print(f"Suggested words ({language}):", final_suggestions)
    return final_suggestions

# load cefr word lists once and cache them so we don't re-read files on every search
_cefr_cache = {}
_stop_words_cache = {}

def load_cefr_words(language):
    if language in _cefr_cache:
        return _cefr_cache[language]

    lang_folder = "es" if language == "es" else "fr" if language == "fr" else None
    if not lang_folder:
        return {}

    path = os.path.join(BASE_DIR, "extension", "languages", lang_folder)
    level_scores = {"A1": 10, "A2": 25, "B1": 40, "B2": 60, "C1": 75}
    word_map = {}

    for lvl in ["A1", "A2", "B1", "B2", "C1"]:
        file_path = os.path.join(path, f"{lvl}.txt")
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    w = line.strip().lower()
                    if w and w not in word_map:
                        word_map[w] = level_scores[lvl]

    _cefr_cache[language] = word_map
    return word_map

def load_stop_words(language):
    # top 100 words from A1 are function words that skew difficulty scores down
    # we ignore these when estimating difficulty so only content words count
    if language in _stop_words_cache:
        return _stop_words_cache[language]

    lang_folder = "es" if language == "es" else "fr" if language == "fr" else None
    if not lang_folder:
        return set()

    path = os.path.join(BASE_DIR, "extension", "languages", lang_folder, "A1.txt")
    stop_words = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 200:
                    break
                stop_words.add(line.strip().lower())

    _stop_words_cache[language] = stop_words
    return stop_words

def estimate_snippet_difficulty(snippet, language):
    # use the same cefr word-mix logic as the extension
    # so snippet difficulty and article difficulty are on the same scale
    word_map = load_cefr_words(language)
    stop_words = load_stop_words(language)

    if not word_map:
        # japanese fallback
        from jreadability import compute_readability
        return compute_readability(snippet)

    import re
    words = re.findall(r"[a-zA-ZáéíóúüñàâäèêëîïôùûüçœæÀÂÄÉÈÊËÎÏÔÙÛÜÇŒÆÁÉÍÓÚÜÑ]+", snippet.lower())

    total_score = 0
    known_count = 0
    for word in words:
        if word in stop_words:
            continue  # skip function words so they don't drag the average down
        if word in word_map:
            total_score += word_map[word]
            known_count += 1

    if known_count < 3:
        return 50  # not enough known words to estimate
    return total_score / known_count

def to_websites(level, final_suggestions, language="ja"):

    if final_suggestions:
        # search for articles containing these words across the whole web
        # inurl:article or just combining the words gets better results than restricting to one site
        words_query = " OR ".join([f'"{word}"' for word in final_suggestions])
        if language == "ja":
            query = f"{words_query} 記事"  # 記事 means "article" in japanese
        elif language == "fr":
            query = f"{words_query} article actualités"
        else:
            query = f"{words_query} artículo noticias"
    else:
        # fallback with no suggested words
        if language == "ja":
            query = "日本語 記事 ニュース"
        elif language == "fr":
            query = "article actualités français"
        else:
            query = "artículo noticias español"

    # lr restricts results to a specific language so we don't get english pages
    lang_code = "lang_ja" if language == "ja" else "lang_fr" if language == "fr" else "lang_es"

    params = {
        'key': 'AIzaSyAVYE88DHZLDVcETzlinIikadVR5Nc1PV8',
        'cx': 'a3f66c67c6d874d1b',
        'q': query,
        'lr': lang_code,
    }

    results = []
    response = requests.get('https://www.googleapis.com/customsearch/v1', params=params)
    if response.status_code == 200:
        data = response.json()
        for item in data.get("items", []):
            results.append({
                "title": item['title'], 
                "link": item['link'], 
                "snippet": item['snippet']
            })
    else:
        print("Search error:", response.status_code)

    result_dict = {}
    for result in results:
        # use the same cefr word mix logic as the extension for consistency
        # for japanese we use jreadability
        snippet_level = estimate_snippet_difficulty(result['snippet'], language)

        result_dict[result['link']] = {
            "title": result['title'],
            "score_diff": abs(snippet_level - level),
            "level": snippet_level
        }

    sorted_links = sorted(result_dict.keys(), key=lambda k: result_dict[k]['score_diff'])

    final_results = []
    for link in sorted_links[:5]:
        d = result_dict[link]
        final_results.append({
            "title": d['title'],
            "link": link,
            "level_difference": d['score_diff'],
            "snippet_level": d['level']
        })

    return final_results

def log_level_history(language="es"):
    # called after a real reading session is saved, not on dashboard visits
    try:
        level = calculate_user_level(language)
        log_file = os.path.join(BASE_DIR, f"level_history_{language}.json")
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                history = json.load(f)
        else:
            history = []
        history.append({
            "level": level,
            "timestamp": str(datetime.now())
        })
        with open(log_file, "w") as f:
            json.dump(history, f, indent=4)
        return level
    except Exception as e:
        print(f"Could not log level history: {e}")
        return None

def get_timeline(language="ja"):
    log_file = os.path.join(BASE_DIR, f"level_history_{language}.json")

    # fall back to the old file for japanese if the new one doesn't exist yet
    if not os.path.exists(log_file) and language == "ja":
        log_file = os.path.join(BASE_DIR, "level_history.json")

    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            history = json.load(f)
    else:
        history = []

    # keep only the most recent entry per day
    by_day = {}
    for entry in history:
        day = entry['timestamp'][:10]
        by_day[day] = entry

    deduped = sorted(by_day.values(), key=lambda e: e['timestamp'])

    level_array = [entry['level'] for entry in deduped]
    time_array = [entry['timestamp'] for entry in deduped]

    return level_array, time_array

def get_click_counts(language="ja"):
    clicks_file = os.path.join(BASE_DIR, f"click_counts_{language}.json")
    if not os.path.exists(clicks_file):
        return {}
    with open(clicks_file, "r", encoding="utf-8") as f:
        return json.load(f)
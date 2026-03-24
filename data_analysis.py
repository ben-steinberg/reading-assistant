import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import json
import os
import numpy as np 
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
import requests
from jreadability import compute_readability
from datetime import datetime


def show_level(score):
    if score < 1.5:
            return "Upper Advanced"
    elif score < 2.5:
        return "Lower Advanced"
    elif score < 3.5:
        return "Upper Intermediate"
    elif score < 4.5:
        return "Lower Intermediate"
    elif score < 5.5:
        return "Upper Elementary"
    else:
        return "Lower Elementary"


with open("click_counts.json", "r", encoding="utf-8") as f:
    click_counts = json.load(f)

# level calculation
    
def calculate_user_level():

    with open("reading_history.json", "r", encoding="utf-8") as f:
        history = json.load(f)

    difficulty_array = []

    if len(history) >= 5: 
        for reading in history: 
            difficulty_array.append({float(reading["difficulty"]) : reading["percentage"]})

    reading_to_df = []
    for entry in difficulty_array:
        for level, percent in entry.items():
            reading_to_df.append({"level_of_reading" : level, "miss_percent": percent})

    reading_df = pd.DataFrame(reading_to_df)

    X = reading_df[['miss_percent']] 
    y = reading_df['level_of_reading']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, random_state=0)

    lin_reg = LinearRegression()

    lin_reg = LinearRegression()
    lin_reg.fit(X_train, y_train)

    target_miss_rate = np.array([[3.0]]) 
    predicted_level = lin_reg.predict(target_miss_rate)

    min_percent = 0
    max_percent = 50

    plt.xlim(min_percent, max_percent)

    extended_percents = np.linspace(min_percent, max_percent, 20).reshape(-1, 1)

    percent_predictions = lin_reg.predict(extended_percents)

    plt.plot(extended_percents.flatten(), percent_predictions, color='red', label='Best Fit Line')
    plt.plot(3.0, predicted_level[0], 'go', color = 'green', label='Optimal Level at 3% Miss Rate')

    plt.scatter(X, y, color='blue', label='Data Points')

    plt.xlabel('Miss Percentage')
    plt.ylabel('Level of Reading')
    plt.title('Best Fit Line for Reading Level vs Miss Percentage')


    plt.legend()
    plt.savefig('reading_level_fit.png')
    # plt.show()

    # print(f"Optimal Reading Level for a 3% miss rate: {predicted_level[0]:.2f}")
    # print(f"Level: {show_level(predicted_level[0])}")

    log_file = "level_history.json"

    # Load existing data
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            history = json.load(f)
    else:
        history = []

    timeline = {
        "level": predicted_level[0],
        "timestamp": str(datetime.now()) 
    }

    history.append(timeline)

    with open(log_file, "w") as f:
        json.dump(history, f, indent=4)

    return predicted_level[0]

def give_suggested_words(level):
    # first we should look at words at the same level that are frequently missed

    with open("click_counts.json", "r", encoding="utf-8") as f:
        clicked_words = json.load(f)

    sorted_clicked = dict(sorted(clicked_words.items(), key=lambda item: item[1], reverse=True))

    path = os.path.join("jplt_levels")

    jplt_levels = []

    for i in range(5):
        level_words = []
        file_path = os.path.join(path, f"N{i+1}.txt")
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                word = line.strip()
                level_words.append(word)

        jplt_levels.append(level_words)

    suggested_words = []

    if level > 4.5:
        for word in sorted_clicked.keys(): 
            if word in jplt_levels[4] or word in jplt_levels[3]:
                suggested_words.append(word)
       
        
    elif level > 3.5:
        for word in sorted_clicked.keys(): 
            if word in jplt_levels[2] or word in jplt_levels[1]:
                suggested_words.append(word)
            
        
        
    else:
        for word in sorted_clicked.keys(): 
            if word in jplt_levels[1] or word in jplt_levels[0]:
                suggested_words.append(word)

    final_suggestions = suggested_words[:5]

    print("Final Suggested Words for Articles:", final_suggestions)

    return final_suggestions

def to_websites(level, final_suggestions):

    if level > 4.5:
        target_domain = "hirogaru-nihongo.jp"

    elif level > 3.5: 
        target_domain = "www.aozora-bunko-portal.com"

    else: 
        target_domain = "news.yahoo.co.jp"

    query = f"site:{target_domain} " + " OR ".join([f'"{word}"' for word in final_suggestions])

    # query = " ".join([f'"{word}"' for word in final_suggestions]) 
    # trying this for now, maybe we can just adjust what they send through to be on the same level 

    params = {
        'key': 'AIzaSyAVYE88DHZLDVcETzlinIikadVR5Nc1PV8',
        'cx': 'a3f66c67c6d874d1b',
        'q': query,
    }

    results = []

    response = requests.get('https://www.googleapis.com/customsearch/v1', params=params)
    if response.status_code == 200:

        data = response.json()
        print("DATA: ", data)
        for item in data.get("items", []):
            results.append({"title" : item['title'], 
                            "link": item['link'], 
                            "snippet": item['snippet']})


    else:
        print("Error:", response.status_code)
        print(response.text)

    result_dict = {}

    for result in results:
        print("\nTitle:", result['title'])
        print("Link:", result['link'])
        print("Snippet:", result['snippet'])
        snippet_level = compute_readability(result['snippet'])
        print("SNIPPET LEVEL: ", snippet_level, " OR: ", show_level(snippet_level))
        result_dict[result['link']] = abs(snippet_level - level)



    for result in results:
        snippet_level = compute_readability(result['snippet'])
        # Store a dictionary as the value instead of just the number
        result_dict[result['link']] = {
            "title": result['title'],
            "score_diff": abs(snippet_level - level),
            "level" : snippet_level
        }

    # Sort based on the score_diff inside the dictionary
    sorted_links = sorted(result_dict.keys(), key=lambda k: result_dict[k]['score_diff'])

    final_results = []
    for link in sorted_links[:5]: # Take top 5
        data = result_dict[link]
        final_results.append({
            "title": data['title'],
            "link": link,
            "level_difference": data['score_diff'],
            "snippet_level": data['level']
        })

    # print("Sorted based on how close to user level: ", final_results)

    return final_results
        
def get_timeline():
    log_file = "level_history.json"

    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            history = json.load(f)
    else:
        history = []

    level_array = []
    time_array = []

    for entry in history:
        level_array.append(entry['level'])
        time_array.append(entry['timestamp'])

    return level_array, time_array


if __name__ == "__main__":
    user_level = calculate_user_level()
    suggested_words = give_suggested_words(user_level)
    suggested_websites = to_websites(user_level, suggested_words)

    print("\n--------------------------------")
    print("User Level: ", user_level)
    print("Interpreted Level: ", show_level(user_level))
    print("Suggested Words: ", suggested_words)
    
    print("Suggested Websites: ") 
    for site in suggested_websites:
        print("\nTitle: ", site['title'], " Link: ", site['link'], " \nLevel Difference: ", 
              site['level_difference'], "\nLevel: ", site['snippet_level'], "Interpreted Level: ", 
              show_level(site['snippet_level']))
        
    print("Timeline: ", get_timeline())
    
    print("\n--------------------------------\n")





'''
To implement a "search and recommend" feature for your Chrome extension, you need to combine keyword targeting with difficulty filtering. Since you don't want the code itself, here is the architectural strategy for selecting websites and automating the search process.

1. Identifying "Safe-Zone" Domains
Instead of searching the entire internet (which includes slang, outdated forums, and technical jargon), you should tell your search engine to prioritize specific domains that are known for high-quality, modern Japanese.

For Lower Levels (N5–N4):



hirogaru-nihongo.jp (Culture-based short articles)

tadoku.org/japanese (Graded stories)

For Intermediate/Advanced (N3–N1):

www.aozora-bunko-portal.com (Classic literature categorized by vocabulary band)

news.yahoo.co.jp (Standard adult-level news)

ja.wikipedia.org (Deep-dives into specific topics)

2. Creating a "Programmable" Search Engine
To do this automatically, you use a tool like Google Programmable Search Engine (PSE). Here is how you set it up to act as your backend:

Restrict to Site Lists: In the PSE control panel, you can add the domains mentioned above. This ensures your search results never give you "junk" sites.

The Query Construction: Your extension will take your "Top 3 Missed Words" from your click_counts.json and build a search query like:

"政府" "経済" "影響" (Searches for articles containing all three target words).

The API Request: The extension sends this query to the Google PSE API. The API returns a list of URLs and "Snippets" (short text previews).

3. The "Difficulty Pre-Filter" Logic
Once you have 10 potential URLs from the search, your Python server (FastAPI) does a "Pre-check" before showing them to you:

Snippet Analysis: Your server reads the "Snippet" text returned by the search API and runs compute_readability on it immediately.

The Matchmaker: If you are at a "Lower Intermediate" level, and the snippet comes back as "Advanced," the extension silently discards that result.

The Recommendation: It only presents the sites that satisfy both conditions: Contains your missed words AND Matches your jReadability level.

4. Integration into the Extension
As a Chrome extension, this search can happen in the background. For example, every time you open a "New Tab," the extension could show a "Daily Recommendation" card: "Hey, you've missed '銃' (gun) twice this week. Here's a short NHK Easy article about a hunting festival that uses that word."

This creates a "Targeted Immersion" loop where the internet is filtered specifically for your personal weaknesses.

How to Setup Google Custom Search API

This video provides a step-by-step walkthrough on how to generate the API key and Search Engine ID you'll need to connect your Python backend to the search engine.


'''
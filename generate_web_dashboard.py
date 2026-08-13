#!/usr/bin/env python3
import os
import sys
import json
import time
import datetime
import urllib.parse
from dotenv import load_dotenv
from requests_oauthlib import OAuth1Session

load_dotenv(override=True)

def extract_publisher(url, title):
    """Detects clean publisher metadata and domain from URL and title."""
    url_lower = url.lower() if url else ""
    title_lower = title.lower() if title else ""
    
    if "lemonde.fr" in url_lower or "le monde" in title_lower:
        return {"name": "Le Monde", "tag": "lemonde", "color": "#0d3b66", "lang": "FR"}
    elif "ft.com" in url_lower or "financial times" in title_lower:
        return {"name": "Financial Times", "tag": "ft", "color": "#fd1266", "lang": "EN"}
    elif "economist.com" in url_lower or "the economist" in title_lower:
        return {"name": "The Economist", "tag": "economist", "color": "#e3120b", "lang": "EN"}
    elif "politico.eu" in url_lower or "politico" in title_lower:
        return {"name": "Politico Europe", "tag": "politico", "color": "#002b49", "lang": "EN"}
    elif "theverge.com" in url_lower or "the verge" in title_lower:
        return {"name": "The Verge", "tag": "tech", "color": "#e01a4f", "lang": "EN"}
    elif "arstechnica.com" in url_lower or "ars technica" in title_lower:
        return {"name": "Ars Technica", "tag": "tech", "color": "#ff6600", "lang": "EN"}
    elif "reuters.com" in url_lower:
        return {"name": "Reuters", "tag": "macro", "color": "#ff8000", "lang": "EN"}
    elif "bloomberg.com" in url_lower:
        return {"name": "Bloomberg", "tag": "macro", "color": "#000000", "lang": "EN"}
    elif "wsj.com" in url_lower:
        return {"name": "WSJ", "tag": "macro", "color": "#003865", "lang": "EN"}
    else:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "") if url else "web"
        return {"name": domain.capitalize() or "News", "tag": "other", "color": "#4a5568", "lang": "EN"}

def fetch_instapaper_articles():
    """Connects to Instapaper Full API and returns structured article list."""
    consumer_key = os.environ.get('INSTAPAPER_KEY')
    consumer_secret = os.environ.get('INSTAPAPER_SECRET')
    username = os.environ.get('INSTAPAPER_USERNAME')
    password = os.environ.get('INSTAPAPER_PASSWORD')

    if not all([consumer_key, consumer_secret, username, password]):
        print("Error: Missing Instapaper credentials in environment.", file=sys.stderr)
        return []

    print("Authenticating with Instapaper API...")
    oauth = OAuth1Session(consumer_key, client_secret=consumer_secret)
    auth_url = 'https://www.instapaper.com/api/1/oauth/access_token'
    try:
        response = oauth.post(
            auth_url, 
            data={
                'x_auth_username': username, 
                'x_auth_password': password, 
                'x_auth_mode': 'client_auth'
            },
            timeout=10
        )
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to authenticate with Instapaper API: {e}", file=sys.stderr)
        return []

    creds = dict(t.split('=') for t in response.text.split('&'))
    inst = OAuth1Session(
        consumer_key, 
        client_secret=consumer_secret, 
        resource_owner_key=creds.get('oauth_token'), 
        resource_owner_secret=creds.get('oauth_token_secret')
    )

    print("Fetching active bookmarks...")
    bookmarks_url = 'https://www.instapaper.com/api/1/bookmarks/list'
    try:
        resp = inst.post(bookmarks_url, data={'limit': 100}, timeout=15)
        resp.raise_for_status()
        items = resp.json()
    except Exception as e:
        print(f"Failed to fetch bookmarks: {e}", file=sys.stderr)
        return []

    articles = []
    for item in items:
        if isinstance(item, dict) and item.get('type') == 'bookmark':
            title = item.get('title', 'Untitled Article')
            url = item.get('url', '')
            desc = item.get('description', '')
            timestamp = item.get('time', int(time.time()))
            
            # Format datetime
            dt = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
            date_str = dt.strftime("%B %d, %Y - %H:%M UTC")
            
            pub_info = extract_publisher(url, title)
            
            articles.append({
                "id": item.get('bookmark_id'),
                "title": title,
                "url": url,
                "description": desc[:300] + ("..." if len(desc) > 300 else "") if desc else "",
                "time": timestamp,
                "formatted_date": date_str,
                "publisher": pub_info["name"],
                "tag": pub_info["tag"],
                "color": pub_info["color"],
                "lang": pub_info["lang"],
                "starred": bool(item.get('starred', 0))
            })

    # Sort descending by newest time
    articles.sort(key=lambda x: x['time'], reverse=True)
    return articles

def generate_dashboard_data():
    """Generates docs/data.json for GitHub Pages."""
    docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    articles = fetch_instapaper_articles()
    
    payload = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%B %d, %Y at %H:%M UTC"),
        "total_articles": len(articles),
        "articles": articles
    }
    
    output_path = os.path.join(docs_dir, "data.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        
    print(f"Successfully generated {output_path} with {len(articles)} articles.")

if __name__ == "__main__":
    generate_dashboard_data()

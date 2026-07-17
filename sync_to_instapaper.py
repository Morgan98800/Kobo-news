#!/usr/bin/env python3
import os
import sys
import json
import argparse
import ssl
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import warnings
from dotenv import load_dotenv

# Suppress all python warnings (e.g. LibreSSL deprecations, Google SDK deprecations)
warnings.filterwarnings("ignore")

# Load environment variables from .env file
load_dotenv(override=True)

# Instapaper API Endpoint
INSTAPAPER_ADD_URL = "https://www.instapaper.com/api/add"

def fetch_rss_items(url):
    """Fetch and parse RSS items from a feed URL."""
    context = ssl._create_unverified_context()
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    items = []
    try:
        with urllib.request.urlopen(req, context=context) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            for item in root.findall('.//item'):
                title = item.find('title')
                link = item.find('link')
                desc = item.find('description')
                pub_date = item.find('pubDate')
                
                title_text = title.text if title is not None else ""
                link_text = link.text if link is not None else ""
                desc_text = desc.text if desc is not None else ""
                pub_date_text = pub_date.text if pub_date is not None else ""
                
                # Simple cleanup of HTML in description if present
                if desc_text:
                    # Strip basic HTML tags
                    import re
                    desc_text = re.sub('<[^<]+?>', '', desc_text).strip()

                items.append({
                    'title': title_text,
                    'link': link_text,
                    'description': desc_text,
                    'pub_date': pub_date_text
                })
    except Exception as e:
        print(f"Error fetching feed {url}: {e}", file=sys.stderr)
    return items

def resolve_google_news_url(url):
    """Resolve Google News redirect/tracking URLs using googlenewsdecoder."""
    if "news.google.com" in url:
        try:
            from googlenewsdecoder import gnewsdecoder
            decoded = gnewsdecoder(url, interval=0.1)
            if decoded.get("status"):
                return decoded["decoded_url"]
        except Exception as e:
            print(f"Warning: Failed to decode Google News URL using library ({e}). Using raw URL.", file=sys.stderr)
    return url

def select_articles_with_gemini(articles, api_key):
    """Use Gemini API to select the best 5 articles."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        # Prepare list for prompt
        articles_list = []
        for i, art in enumerate(articles):
            articles_list.append(f"[{i}] Title: {art['title']}\nDescription: {art['description'][:200]}\n")
            
        articles_text = "\n".join(articles_list)
        
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"""You are a professional editor curating a daily briefing on European Union (EU) news and policy.
From the following list of news articles, select the top 5 most important, high-impact, or informative articles. Prioritize policy changes, regulatory updates, major political shifts, and EU-wide decisions.

Articles list:
{articles_text}

Return your selection in a JSON format containing a list of chosen indices, like this:
{{
  "selected_indices": [0, 3, 5, 8, 12]
}}
Return only the JSON object. Do not include markdown formatting or backticks around the JSON. Just raw JSON.
"""
        response = model.generate_content(prompt)
        # Clean response string in case it wrapped with markdown ```json ... ```
        response_text = response.text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        response_text = response_text.strip()

        data = json.loads(response_text)
        selected_indices = data.get("selected_indices", [])
        
        selected_articles = []
        for idx in selected_indices[:5]:
            if 0 <= idx < len(articles):
                selected_articles.append(articles[idx])
                
        return selected_articles
    except Exception as e:
        print(f"Error using Gemini API for selection: {e}. Falling back to top 5 chronological.", file=sys.stderr)
        return articles[:5]

def sync_to_instapaper(username, password, url, title=None):
    """Add a URL to Instapaper via Simple API."""
    data = {
        'username': username,
        'password': password,
        'url': url
    }
    if title:
        data['title'] = title
        
    encoded_data = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(
        INSTAPAPER_ADD_URL,
        data=encoded_data,
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    
    try:
        # Instapaper API uses basic SSL; bypass verification if system certs are old
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=context) as response:
            status = response.getcode()
            if status == 201:
                print(f"Successfully synced: {url}")
                return True
            else:
                print(f"Failed to sync {url}. Status code: {status}", file=sys.stderr)
                return False
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("Authentication failed: Check your Instapaper username and password.", file=sys.stderr)
        else:
            print(f"HTTP Error {e.code}: {e.read().decode('utf-8', errors='ignore')}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error syncing {url}: {e}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description="Fetch top EU/policy news and sync them to Instapaper.")
    parser.add_argument('--auto', action='store_true', help="Fetch feeds, auto-select articles using Gemini, and sync.")
    parser.add_argument('--list', action='store_true', help="Fetch feeds and print articles in JSON format.")
    parser.add_argument('--urls', nargs='+', help="Directly sync these URLs to Instapaper (Agent Mode).")
    
    args = parser.parse_args()
    
    username = os.environ.get("INSTAPAPER_USERNAME")
    password = os.environ.get("INSTAPAPER_PASSWORD")
    
    if not args.list and (not username or not password):
        print("Error: INSTAPAPER_USERNAME and INSTAPAPER_PASSWORD must be set in environment or .env file.", file=sys.stderr)
        sys.exit(1)
        
    if args.list:
        # Fetch RSS feeds and list them
        feeds = [
            "https://www.politico.eu/section/policy/feed/",
            "https://news.google.com/rss/search?q=EU+news+OR+EU+policy+OR+Europe+politics&hl=en-US&gl=US&ceid=US:en"
        ]
        
        all_articles = []
        for feed in feeds:
            all_articles.extend(fetch_rss_items(feed))
            
        # Deduplicate
        seen_titles = set()
        deduped = []
        for art in all_articles:
            title_norm = art['title'].lower().strip()
            if title_norm not in seen_titles:
                seen_titles.add(title_norm)
                deduped.append(art)
                
        print(json.dumps(deduped[:45], indent=2))
        sys.exit(0)
        
    elif args.urls:
        # Agent Mode: Syncing URLs provided by command line
        print(f"Agent Mode: Syncing {len(args.urls)} provided URLs to Instapaper...")
        success_count = 0
        for url in args.urls:
            resolved_url = resolve_google_news_url(url)
            if sync_to_instapaper(username, password, resolved_url):
                success_count += 1
        print(f"Synced {success_count}/{len(args.urls)} articles to Instapaper.")
        
    elif args.auto:
        # Standalone Mode: Fetch feeds, select top 5 (Gemini/Fallback), and sync
        print("Fetching RSS feeds...")
        feeds = [
            "https://www.politico.eu/section/policy/feed/",
            "https://news.google.com/rss/search?q=EU+news+OR+EU+policy+OR+Europe+politics&hl=en-US&gl=US&ceid=US:en"
        ]
        
        all_articles = []
        for feed in feeds:
            all_articles.extend(fetch_rss_items(feed))
            
        print(f"Fetched {len(all_articles)} total articles.")
        
        if not all_articles:
            print("No articles found to sync.", file=sys.stderr)
            sys.exit(1)
            
        # Deduplicate
        seen_titles = set()
        deduped = []
        for art in all_articles:
            title_norm = art['title'].lower().strip()
            if title_norm not in seen_titles:
                seen_titles.add(title_norm)
                deduped.append(art)
                
        print(f"Deduplicated to {len(deduped)} articles.")
        
        # Select best 5
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key and gemini_key.strip() != "" and "your_gemini_api_key" not in gemini_key:
            print("Selecting best 5 articles using Gemini API...")
            selected = select_articles_with_gemini(deduped, gemini_key)
        else:
            print("No valid GEMINI_API_KEY found. Falling back to first 5 chronological/relevance articles.")
            selected = deduped[:5]
            
        # Resolve Google News links for only the chosen 5 to save network calls
        print("Resolving and syncing selected articles...")
        success_count = 0
        for art in selected:
            title = art.get('title')
            url = art.get('link')
            resolved_url = resolve_google_news_url(url)
            print(f"- Adding: {title} ({resolved_url})")
            if sync_to_instapaper(username, password, resolved_url, title):
                success_count += 1
                
        print(f"Successfully curated and synced {success_count} articles to Instapaper.")
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

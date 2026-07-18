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
import datetime
import email.utils
from dotenv import load_dotenv

# Suppress all python warnings (e.g. LibreSSL deprecations, Google SDK deprecations)
warnings.filterwarnings("ignore")

# Load environment variables from .env file
load_dotenv(override=True)

# Instapaper API Endpoint
INSTAPAPER_ADD_URL = "https://www.instapaper.com/api/add"

def is_within_24_hours(pub_date_str):
    """Check if an RFC 822 pubDate string is within the last 24 hours."""
    if not pub_date_str:
        return True
    try:
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        now = datetime.datetime.now(datetime.timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return (now - dt).total_seconds() <= 24 * 3600
    except Exception:
        return True

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
                    import re
                    desc_text = re.sub('<[^<]+?>', '', desc_text).strip()

                if is_within_24_hours(pub_date_text):
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
        print(f"Error using Gemini API for selection: {e}. Falling back to keyword scoring algorithm.", file=sys.stderr)
        return select_articles_by_keyword_scoring(articles, top_n=5)

def select_articles_by_keyword_scoring(articles, top_n=5):
    """
    Scores and ranks articles based on keyword matching tailored to political risk,
    transatlantic relations, EU-China de-risking, and Francophone Africa.
    """
    import re
    
    # Weights reflecting priority order
    weights = {
        'eu_institutional': 10,
        'transatlantic': 9,
        'eu_china': 8,
        'geoeconomics': 7,
        'francophone_africa': 6,
        'negative': -20 # Heavily penalize sports/entertainment/domestic filler
    }
    
    keywords = {
        'eu_institutional': [
            r'\beu\b', r'\beuropean union\b', r'\bcommission\b', r'\bparliament\b', 
            r'\bcouncil\b', r'\bcourt of justice\b', r'\bcjeu\b', r'\blegislation\b', 
            r'\benlargement\b', r'\bbrussels\b', r'\bvon der leyen\b', r'\bmetsola\b'
        ],
        'transatlantic': [
            r'\bus\b', r'\bunited states\b', r'\btransatlantic\b', r'\bnato\b', 
            r'\bwashington\b', r'\bbiden\b', r'\btrump\b', r'\btrade dispute\b', 
            r'\bira\b', r'\binflation reduction act\b', r'\bdefense\b'
        ],
        'eu_china': [
            r'\bchina\b', r'\bbeijing\b', r'\bde-risking\b', r'\bfdi screening\b', 
            r'\bexport controls\b', r'\bsupply chains\b', r'\bcritical minerals\b', 
            r'\btariffs\b', r'\bevs\b', r'\belectric vehicles\b'
        ],
        'geoeconomics': [
            r'\bsanctions\b', r'\bsovereign risk\b', r'\bregulatory\b', r'\bgeoeconomic\b',
            r'\binvestment\b', r'\btrade war\b', r'\bgeopolitics\b', r'\bmercosur\b'
        ],
        'francophone_africa': [
            r'\bafrica\b', r'\bsahel\b', r'\bmali\b', r'\bniger\b', r'\bburkina faso\b',
            r'\bsenegal\b', r'\bcote d\'ivoire\b', r'\bivory coast\b', r'\bfrance\b',
            r'\bmacron\b', r'\bparis\b', r'\bfrancophone\b', r'\becowas\b'
        ],
        'negative': [
            r'\bsports\b', r'\bfootball\b', r'\bcelebrity\b', r'\bentertainment\b',
            r'\bmurder\b', r'\baccident\b', r'\bgossip\b', r'\breal madrid\b', r'\bfifa\b'
        ]
    }
    
    # Compile regexes for performance
    compiled_keywords = {
        category: [re.compile(kw, re.IGNORECASE) for kw in kws]
        for category, kws in keywords.items()
    }
    
    scored_articles = []
    
    for art in articles:
        title = art.get('title', '')
        desc = art.get('description', '')
        text_to_score = f"{title} {desc}"
        
        score = 0
        
        for category, regex_list in compiled_keywords.items():
            for regex in regex_list:
                # Count occurrences to reward articles covering topics in-depth
                matches = len(regex.findall(text_to_score))
                if matches > 0:
                    score += matches * weights[category]
                    # Bonus multiplier if the keyword is front-and-center in the title
                    if len(regex.findall(title)) > 0:
                        score += weights[category] 
                    
        art_with_score = art.copy()
        art_with_score['_score'] = score
        scored_articles.append(art_with_score)
        
    # Sort by score descending. 
    # Python's Timsort is stable, so articles with the same score maintain chronological order.
    scored_articles.sort(key=lambda x: x.get('_score', 0), reverse=True)
    
    # As requested, even if scores are low, we take the top N available.
    return scored_articles[:top_n]

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
            print("No valid GEMINI_API_KEY found. Falling back to keyword scoring algorithm...")
            selected = select_articles_by_keyword_scoring(deduped, top_n=5)
            
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

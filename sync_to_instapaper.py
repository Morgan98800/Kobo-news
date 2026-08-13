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

def get_unlocked_archive_url(url):
    """
    Checks if a URL is from a known paywalled publisher or if an archive snapshot exists.
    Returns the Wayback Machine / Archive URL if available, otherwise returns the original URL.
    """
    paywalled_domains = [
        "ft.com", "wsj.com", "bloomberg.com", "economist.com", 
        "foreignaffairs.com", "thetimes.co.uk", "nytimes.com", "telegraph.co.uk"
    ]
    
    domain = urllib.parse.urlparse(url).netloc.lower()
    is_paywalled = any(p in domain for p in paywalled_domains)
    
    if is_paywalled:
        try:
            api_url = f"https://archive.org/wayback/available?url={urllib.parse.quote(url)}"
            req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=context, timeout=4) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                snapshots = data.get('archived_snapshots', {})
                closest = snapshots.get('closest', {})
                if closest.get('available') and closest.get('url'):
                    archive_url = closest['url']
                    print(f"  [Archive Unlocked] Found Wayback mirror for {domain}: {archive_url}")
                    return archive_url
        except Exception as e:
            print(f"  [Archive Check] Could not fetch archive for {url}: {e}", file=sys.stderr)
            
    return url

def fetch_article_context(url, fallback_desc=""):
    """Fetch full text using trafilatura, return a 1500-char snippet."""
    try:
        import urllib.request
        import ssl
        import trafilatura
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=context, timeout=5) as response:
            html = response.read()
            
        text = trafilatura.extract(html)
        if text:
            return text[:1500]
    except Exception as e:
        print(f"Warning: Failed to extract full text for {url}: {e}", file=sys.stderr)
    return fallback_desc

def gemini_score_articles(articles, topic, api_key):
    """Use Gemini API to semantically deduplicate and score articles with deep context."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        articles_list = []
        for i, art in enumerate(articles):
            source = extract_source_domain(art)
            resolved_url = resolve_google_news_url(art['link'])
            context = fetch_article_context(resolved_url, fallback_desc=art.get('description', ''))
            articles_list.append(f"[{i}] Publisher: {source} | Title: {art['title']}\nSnippet: {context}\n")
            
        articles_text = "\n".join(articles_list)
        
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"""You are a strict, professional executive editor curating a daily briefing on {topic}.
Here is a list of candidate articles with text snippets. Your task is to score them for importance, quality, and depth, and completely eliminate duplicate stories.

Rules:
1. Semantic Deduplication: Identify articles covering the exact same underlying event or story. From each group of identical stories, select ONLY the single best, most in-depth article. Discard the rest.
2. Quality Scoring: For the unique articles you keep, assign a score from 1 to 100 based on how important and high-impact the article is.
   - FAVOR renowned, analytical sources (e.g. FT, Economist, major broadsheets).
   - PRIORITIZE deep-dive, long-form journalism and significant policy/regulatory changes.
   - HEAVILY PENALIZE short "live blog" updates, superficial listicles, wire snippets, or generic opinion columns.

Return your evaluation in a JSON format containing a list of dictionaries with 'index' and 'score'.
Example:
[
  {{"index": 0, "score": 95}},
  {{"index": 3, "score": 88}}
]
Return only the raw JSON array. Do not include markdown formatting or backticks around the JSON.
"""
        response = model.generate_content([prompt, articles_text])
        response_text = response.text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        response_text = response_text.strip()

        data = json.loads(response_text)
        
        scored = []
        for i, art in enumerate(articles):
            art_copy = art.copy()
            art_copy['_score'] = -1
            for item in data:
                if item.get("index") == i:
                    art_copy['_score'] = item.get("score", 0)
                    break
            scored.append(art_copy)
            
        scored.sort(key=lambda x: x.get('_score', 0), reverse=True)
        return scored
    except Exception as e:
        print(f"Error using Gemini API for selection on topic {topic}: {e}. Falling back to -1 scores.", file=sys.stderr)
        scored = [art.copy() for art in articles]
        for a in scored:
            a['_score'] = -1
        return scored

def extract_source_domain(article):
    """Extract clean source publisher name/domain from Google News title or direct link."""
    link = article.get('link', '')
    title = article.get('title', '')
    
    source = "unknown"
    # 1. Google News RSS titles format: "Headline text - Source Name"
    if ' - ' in title:
        source = title.rsplit(' - ', 1)[1].strip().lower()
        if source.startswith("www."):
            source = source[4:]
    # 2. Direct feed URL domain fallback
    elif link and "news.google.com" not in link:
        domain = urllib.parse.urlparse(link).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        source = domain

    # Normalize brand variants (e.g. politico.com / politico.eu / politico -> politico)
    if "politico" in source:
        return "politico"

    return source

def score_articles(articles, profile="political_risk"):
    """Scores articles based on topic-specific keyword matching."""
    import re
    
    if profile == "political_risk":
        weights = {
            'eu_institutional': 10, 'transatlantic': 9, 'eu_china': 8,
            'geoeconomics': 7, 'francophone_africa': 6, 'negative': -20
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
    elif profile == "ai_policy":
        weights = {'ai_policy': 10, 'chip_geo': 8, 'negative': -20}
        keywords = {
            'ai_policy': [
                r'\bai act\b', r'\bai regulation\b', r'\bai policy\b', r'\bexport controls\b', 
                r'\bgovernance\b', r'\bchips act\b', r'\bexecutive order\b', r'\bcompliance\b', 
                r'\bftc\b', r'\bdoj\b'
            ],
            'chip_geo': [
                r'\bnvidia\b', r'\btsmc\b', r'\basml\b', r'\bsemiconductor\b', 
                r'\badvanced chips\b', r'\bgpu\b', r'\bnational security\b'
            ],
            'negative': [
                r'\bsports\b', r'\bcelebrity\b', r'\bcrypto\b', r'\bnft\b', r'\bgossip\b'
            ]
        }
    elif profile == "ai_industry":
        weights = {'models_tech': 10, 'industry_compute': 7, 'negative': -20}
        keywords = {
            'models_tech': [
                r'\bopenai\b', r'\banthropic\b', r'\bgemini\b', r'\bchatgpt\b', 
                r'\bclaude\b', r'\bllm\b', r'\bdeepmind\b', r'\bmistral\b', 
                r'\bllama\b', r'\bmodel release\b', r'\breasoning model\b'
            ],
            'industry_compute': [
                r'\bstartup\b', r'\bfunding\b', r'\bdatacenter\b', r'\bcompute\b', 
                r'\bsupercomputer\b', r'\bapple intelligence\b'
            ],
            'negative': [
                r'\bsports\b', r'\bcrypto\b', r'\bnft\b', r'\bscam\b', r'\bgossip\b'
            ]
        }

    compiled = {cat: [re.compile(kw, re.IGNORECASE) for kw in kws] for cat, kws in keywords.items()}
    scored = []
    
    for art in articles:
        text = f"{art.get('title', '')} {art.get('description', '')}"
        score = 0
        for cat, regexes in compiled.items():
            for r in regexes:
                m = len(r.findall(text))
                if m > 0:
                    score += m * weights[cat]
                    if r.search(art.get('title', '')):
                        score += weights[cat]
        art_copy = art.copy()
        art_copy['_score'] = score
        scored.append(art_copy)
        
    scored.sort(key=lambda x: x.get('_score', 0), reverse=True)
    return scored

def select_with_diversity(scored_articles, count, max_per_source=2, pool_name="political_risk", global_sources=None):
    """
    Selects `count` articles from `scored_articles`, capping articles per source domain
    and favoring unrepresented publishers for similarly-scored articles.
    """
    if global_sources is None:
        global_sources = {}
        
    selected = []
    pool_sources = {}
    candidates = list(scored_articles)
    
    while len(selected) < count and candidates:
        # Find candidates whose source has not hit the per-pool cap
        valid_candidates = [
            art for art in candidates 
            if pool_sources.get(extract_source_domain(art), 0) < max_per_source
        ]
        
        if not valid_candidates:
            # Relax cap if strictly enforcing it would leave slots empty
            needed = count - len(selected)
            print(f"Notice: Relaxed source cap of {max_per_source} for '{pool_name}' pool. Adding {needed} remaining top article(s).")
            for art in candidates[:needed]:
                selected.append(art)
                domain = extract_source_domain(art)
                global_sources[domain] = global_sources.get(domain, 0) + 1
            break
            
        # Get highest score among valid candidates
        max_score = max(art.get('_score', 0) for art in valid_candidates)
        top_candidates = [art for art in valid_candidates if art.get('_score', 0) == max_score]
        
        # Favor a candidate from a source not yet represented in today's global picks
        chosen = None
        for art in top_candidates:
            domain = extract_source_domain(art)
            if global_sources.get(domain, 0) == 0:
                chosen = art
                break
                
        if not chosen:
            chosen = top_candidates[0]
            
        selected.append(chosen)
        candidates.remove(chosen)
        
        domain = extract_source_domain(chosen)
        pool_sources[domain] = pool_sources.get(domain, 0) + 1
        global_sources[domain] = global_sources.get(domain, 0) + 1
        
    return selected

def select_articles_by_keyword_scoring(articles, top_n=5):
    """Legacy compatibility function for political risk selection."""
    scored = score_articles(articles, profile="political_risk")
    return select_with_diversity(scored, count=top_n, max_per_source=2, pool_name="Political Risk")

def curate_all_articles(pol_articles, ai_policy_articles, ai_industry_articles, use_gemini=False, gemini_key=None):
    """
    Curates 8 total articles:
    - 5 Political Risk / EU / Transatlantic (max 2 per domain)
    - 2 AI Policy / Regulation (max 1 per domain)
    - 1 General AI Industry News
    """
    global_sources = {}
    
    # 1. Political Risk Pool (5 articles)
    if use_gemini and gemini_key:
        scored_pol = gemini_score_articles(pol_articles, "EU Politics & Policy", gemini_key)
    else:
        scored_pol = score_articles(pol_articles, profile="political_risk")
    selected_pol = select_with_diversity(scored_pol, count=5, max_per_source=2, pool_name="Political Risk", global_sources=global_sources)
    
    # 2. AI Policy Pool (2 articles)
    seen_urls = {a['link'] for a in selected_pol}
    filt_ai_pol = [a for a in ai_policy_articles if a['link'] not in seen_urls]
    if use_gemini and gemini_key:
        scored_ai_pol = gemini_score_articles(filt_ai_pol, "AI Regulation & Policy", gemini_key)
    else:
        scored_ai_pol = score_articles(filt_ai_pol, profile="ai_policy")
    selected_ai_pol = select_with_diversity(scored_ai_pol, count=2, max_per_source=1, pool_name="AI Policy", global_sources=global_sources)
    
    # 3. AI Industry Pool (1 article)
    seen_urls.update({a['link'] for a in selected_ai_pol})
    filt_ai_ind = [a for a in ai_industry_articles if a['link'] not in seen_urls]
    if use_gemini and gemini_key:
        scored_ai_ind = gemini_score_articles(filt_ai_ind, "AI Industry & Technology", gemini_key)
    else:
        scored_ai_ind = score_articles(filt_ai_ind, profile="ai_industry")
    selected_ai_ind = select_with_diversity(scored_ai_ind, count=1, max_per_source=1, pool_name="AI Industry", global_sources=global_sources)
    
    return selected_pol + selected_ai_pol + selected_ai_ind

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
        pol_feeds = [
            "https://www.politico.eu/section/policy/feed/",
            "https://news.google.com/rss/search?q=EU+news+OR+EU+policy+OR+Europe+politics&hl=en-US&gl=US&ceid=US:en"
        ]
        all_articles = []
        for feed in pol_feeds:
            all_articles.extend(fetch_rss_items(feed))
            
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
        print(f"Agent Mode: Syncing {len(args.urls)} provided URLs to Instapaper...")
        success_count = 0
        for url in args.urls:
            resolved_url = resolve_google_news_url(url)
            if sync_to_instapaper(username, password, resolved_url):
                success_count += 1
        print(f"Synced {success_count}/{len(args.urls)} articles to Instapaper.")
        
    elif args.auto:
        print("Fetching RSS feeds across categories...")
        pol_feeds = [
            "https://www.politico.eu/section/policy/feed/",
            "https://news.google.com/rss/search?q=EU+news+OR+EU+policy+OR+Europe+politics&hl=en-US&gl=US&ceid=US:en"
        ]
        ai_policy_feeds = [
            "https://news.google.com/rss/search?q=%22AI+regulation%22+OR+%22AI+Act%22+OR+%22AI+policy%22+OR+%22AI+export+controls%22+OR+%22AI+governance%22+OR+%22chips+act%22&hl=en-US&gl=US&ceid=US:en"
        ]
        ai_industry_feeds = [
            "https://news.google.com/rss/search?q=%22artificial+intelligence%22+OR+%22AI+model%22+OR+%22AI+industry%22+OR+OpenAI+OR+Anthropic&hl=en-US&gl=US&ceid=US:en"
        ]
        
        pol_raw, ai_pol_raw, ai_ind_raw = [], [], []
        for feed in pol_feeds:
            pol_raw.extend(fetch_rss_items(feed))
        for feed in ai_policy_feeds:
            ai_pol_raw.extend(fetch_rss_items(feed))
        for feed in ai_industry_feeds:
            ai_ind_raw.extend(fetch_rss_items(feed))
            
        print(f"Fetched {len(pol_raw)} Political, {len(ai_pol_raw)} AI Policy, and {len(ai_ind_raw)} AI Industry articles.")
        
        def dedup(articles):
            seen = set()
            out = []
            for art in articles:
                tn = art['title'].lower().strip()
                if tn not in seen:
                    seen.add(tn)
                    out.append(art)
            return out
            
        pol_deduped = dedup(pol_raw)
        ai_pol_deduped = dedup(ai_pol_raw)
        ai_ind_deduped = dedup(ai_ind_raw)
        
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key and gemini_key.strip() != "" and "your_gemini_api_key" not in gemini_key:
            print("Selecting articles using Gemini API with topic scoring & source diversity...")
            selected = curate_all_articles(pol_deduped, ai_pol_deduped, ai_ind_deduped, use_gemini=True, gemini_key=gemini_key)
        else:
            print("Selecting 8 articles with keyword scoring & source diversity...")
            selected = curate_all_articles(pol_deduped, ai_pol_deduped, ai_ind_deduped, use_gemini=False)
            
        print("Resolving and syncing selected 8 articles...")
        success_count = 0
        for art in selected:
            title = art.get('title')
            url = art.get('link')
            resolved_url = resolve_google_news_url(url)
            final_url = get_unlocked_archive_url(resolved_url)
            print(f"- Adding: {title} ({final_url})")
            if sync_to_instapaper(username, password, final_url, title):
                success_count += 1
                
        print(f"Successfully curated and synced {success_count} articles to Instapaper.")
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

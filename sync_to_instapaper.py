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
    """Fetch and parse RSS and Atom items from a feed URL."""
    context = ssl._create_unverified_context()
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    items = []
    try:
        with urllib.request.urlopen(req, context=context) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            
            # 1. Standard RSS items
            for item in root.findall('.//item'):
                title = item.find('title')
                link = item.find('link')
                desc = item.find('description')
                pub_date = item.find('pubDate')
                
                title_text = title.text if title is not None and title.text else ""
                link_text = link.text if link is not None and link.text else ""
                desc_text = desc.text if desc is not None and desc.text else ""
                pub_date_text = pub_date.text if pub_date is not None and pub_date.text else ""
                
                if desc_text:
                    import re
                    desc_text = re.sub('<[^<]+?>', '', desc_text).strip()

                if is_within_24_hours(pub_date_text):
                    items.append({
                        'title': title_text.strip(),
                        'link': link_text.strip(),
                        'description': desc_text,
                        'pub_date': pub_date_text
                    })
                    
            # 2. Atom entries (e.g. The Verge, Ars Technica)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            for entry in root.findall('.//atom:entry', ns) + root.findall('.//entry'):
                title = entry.find('atom:title', ns) if entry.find('atom:title', ns) is not None else entry.find('title')
                link = entry.find('atom:link', ns) if entry.find('atom:link', ns) is not None else entry.find('link')
                summary = entry.find('atom:summary', ns) or entry.find('atom:content', ns) or entry.find('summary') or entry.find('content')
                pub_date = entry.find('atom:published', ns) or entry.find('atom:updated', ns) or entry.find('published') or entry.find('updated')
                
                title_text = title.text if title is not None and title.text else ""
                link_text = ""
                if link is not None:
                    link_text = link.get('href') or link.text or ""
                desc_text = summary.text if summary is not None and summary.text else ""
                pub_date_text = pub_date.text if pub_date is not None and pub_date.text else ""
                
                if desc_text:
                    import re
                    desc_text = re.sub('<[^<]+?>', '', desc_text).strip()
                    
                if is_within_24_hours(pub_date_text):
                    items.append({
                        'title': title_text.strip(),
                        'link': link_text.strip(),
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
        "foreignaffairs.com", "thetimes.co.uk", "nytimes.com", "telegraph.co.uk", "lemonde.fr"
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

def fetch_lemonde_full_content(url):
    """
    Extracts the full subscriber HTML content from a Le Monde article URL
    using the mobile API endpoint with image template placeholders fixed.
    """
    import re
    match = re.search(r'_(\d+)_\d+\.html', url)
    if not match:
        match = re.search(r'_(\d+)(?:\.html)?$', url)
    if not match:
        return None
        
    article_id = match.group(1)
    api_url = f"https://apps.lemonde.fr/aec/v1/premium-android-phone/article/{article_id}"
    headers = {
        'User-Agent': 'LeMonde/9.20.1 (Android; 14)',
        'X-Lmd-Token': 'TWPLMOLMO',
        'Accept': 'application/json'
    }
    
    try:
        import requests
        resp = requests.get(api_url, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            content = data.get('template_vars', {}).get('content', '')
            title = data.get('template_vars', {}).get('seo_title') or data.get('template_vars', {}).get('title', '')
            if content:
                # Fix image template placeholders
                content = content.replace('%7B%7Bwidth%7D%7D', '1000').replace('{{width}}', '1000')
                content = content.replace('%7B%7Bheight%7D%7D', '600').replace('{{height}}', '600')
                
                full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
</head>
<body>
{content}
</body>
</html>"""
                return {
                    'title': title,
                    'html': full_html
                }
    except Exception as e:
        print(f"  [Le Monde Extractor] Error extracting article {article_id}: {e}", file=sys.stderr)
        
    return None

def fetch_ft_full_content(url):
    """
    Extracts the full subscriber HTML content from a Financial Times article URL
    using the FT_COOKIE / FTSession_s if available.
    """
    cookie = os.environ.get("FT_COOKIE")
    if not cookie:
        return None
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cookie': cookie if 'FTSession' in cookie else f"FTSession_s={cookie}; FTSession={cookie}"
    }
    
    try:
        import requests
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            body = soup.find('div', {'id': 'article-body'}) or soup.find('article')
            title_tag = soup.find('h1') or soup.find('meta', property='og:title')
            title = title_tag.get_text(strip=True) if title_tag else "Financial Times"
            if body and len(body.get_text(strip=True)) > 400:
                full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
</head>
<body>
<h1>{title}</h1>
{str(body)}
</body>
</html>"""
                return {
                    'title': title,
                    'html': full_html
                }
    except Exception as e:
        print(f"  [FT Extractor] Error extracting article: {e}", file=sys.stderr)
        
    return None

def fetch_economist_full_content(url):
    """
    Extracts the full subscriber HTML content from an Economist article URL
    using ECONOMIST_COOKIE and curl_cffi with Chrome impersonation.
    """
    cookie = os.environ.get("ECONOMIST_COOKIE")
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    if cookie:
        headers['Cookie'] = cookie
        
    try:
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(url, headers=headers, impersonate="chrome124", timeout=15)
        except Exception:
            import requests
            headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            resp = requests.get(url, headers=headers, timeout=12)
            
        if resp.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # 1. Try __NEXT_DATA__ JSON payload
            next_data = soup.find('script', {'id': '__NEXT_DATA__'})
            if next_data:
                try:
                    import json
                    data = json.loads(next_data.string)
                    content = data.get('props', {}).get('pageProps', {}).get('content', {})
                    headline = content.get('headline') or data.get('props', {}).get('pageProps', {}).get('headline', '')
                    body_parts = content.get('body', [])
                    if body_parts and len(body_parts) > 2:
                        html_pieces = []
                        for part in body_parts:
                            if isinstance(part, dict) and part.get('textHtml'):
                                html_pieces.append(f"<p>{part.get('textHtml')}</p>")
                            elif isinstance(part, dict) and part.get('text'):
                                html_pieces.append(f"<p>{part.get('text')}</p>")
                        if html_pieces:
                            full_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{headline}</title></head><body><h1>{headline}</h1>{''.join(html_pieces)}</body></html>"""
                            return {'title': headline or "The Economist", 'html': full_html}
                except Exception:
                    pass

            # 2. Try HTML article body
            body = soup.find('article') or soup.find('div', {'class': lambda c: c and 'article__body' in c})
            title_tag = soup.find('h1')
            title = title_tag.get_text(strip=True) if title_tag else "The Economist"
            if body and len(body.get_text(strip=True)) > 500:
                full_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title></head><body><h1>{title}</h1>{str(body)}</body></html>"""
                return {'title': title, 'html': full_html}
    except Exception as e:
        print(f"  [Economist Extractor] Error extracting article: {e}", file=sys.stderr)
        
    return None

def fetch_article_context(url, fallback_desc=""):
    """Fetch full text using trafilatura or direct extractors, return a 1500-char snippet."""
    if "lemonde.fr" in url:
        lm_data = fetch_lemonde_full_content(url)
        if lm_data and lm_data.get('html'):
            try:
                import trafilatura
                extracted = trafilatura.extract(lm_data['html'])
                if extracted:
                    return extracted[:1500]
            except Exception:
                pass
    elif "economist.com" in url:
        ec_data = fetch_economist_full_content(url)
        if ec_data and ec_data.get('html'):
            try:
                import trafilatura
                extracted = trafilatura.extract(ec_data['html'])
                if extracted:
                    return extracted[:1500]
            except Exception:
                pass
            except Exception:
                pass

    if "ft.com" in url:
        ft_data = fetch_ft_full_content(url)
        if ft_data and ft_data.get('html'):
            try:
                import trafilatura
                extracted = trafilatura.extract(ft_data['html'])
                if extracted:
                    return extracted[:1500]
            except Exception:
                pass

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

PREMIER_PUBLISHERS = {
    "ft", "lemonde", "politico", "economist", "reuters", "bloomberg", 
    "wsj", "theverge", "arstechnica", "technologyreview", "euractiv", 
    "foreignaffairs", "foreignpolicy", "lesechos", "lefigaro", "wired"
}

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

    # Normalize brand variants
    if "politico" in source:
        return "politico"
    if "lemonde" in source or "le monde" in source:
        return "lemonde"
    if "ft.com" in source or "financial times" in source:
        return "ft"
    if "economist" in source:
        return "economist"
    if "theverge" in source or "the verge" in source:
        return "theverge"
    if "arstechnica" in source or "ars technica" in source:
        return "arstechnica"
    if "reuters" in source:
        return "reuters"
    if "bloomberg" in source:
        return "bloomberg"
    if "wsj" in source or "wall street journal" in source:
        return "wsj"
    if "euractiv" in source:
        return "euractiv"
    if "technologyreview" in source or "technology review" in source or "mit tech" in source:
        return "technologyreview"

    return source

def score_articles(articles, profile="political_risk"):
    """Scores articles based on topic-specific keyword matching and publisher prestige."""
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
                        
        domain = extract_source_domain(art)
        # Heavy quality boost for premier publications
        if domain in PREMIER_PUBLISHERS:
            score += 35
        else:
            # Deprioritize unknown regional micro-blogs
            score -= 20
            
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

_oauth_session_cache = None

def get_instapaper_oauth_session(consumer_key, consumer_secret, username, password):
    """Obtains and caches an OAuth 1.0 session for the Instapaper Full API."""
    global _oauth_session_cache
    if _oauth_session_cache is not None:
        return _oauth_session_cache
        
    try:
        import requests
        from requests_oauthlib import OAuth1
        auth = OAuth1(consumer_key, consumer_secret)
        token_url = "https://www.instapaper.com/api/1.1/oauth/access_token"
        data = {
            'x_auth_username': username,
            'x_auth_password': password,
            'x_auth_mode': 'client_auth'
        }
        resp = requests.post(token_url, auth=auth, data=data, timeout=10)
        if resp.status_code == 200:
            params = dict(urllib.parse.parse_qsl(resp.text))
            oauth_token = params.get('oauth_token')
            oauth_token_secret = params.get('oauth_token_secret')
            if oauth_token and oauth_token_secret:
                _oauth_session_cache = OAuth1(consumer_key, consumer_secret, oauth_token, oauth_token_secret)
                return _oauth_session_cache
        else:
            print(f"Warning: Instapaper OAuth authentication failed: {resp.status_code} {resp.text}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Instapaper OAuth initialization failed: {e}", file=sys.stderr)
    return None

def sync_to_instapaper(username, password, url, title=None, raw_content=None):
    """
    Add a URL or raw article content to Instapaper.
    Uses Instapaper Full OAuth API if raw_content or OAuth credentials are present,
    otherwise falls back to the Simple API.
    """
    consumer_key = os.environ.get("INSTAPAPER_KEY")
    consumer_secret = os.environ.get("INSTAPAPER_SECRET")
    
    # 1. Try Full API with raw HTML content (Bypasses server paywall fetching)
    if consumer_key and consumer_secret and raw_content:
        oauth_auth = get_instapaper_oauth_session(consumer_key, consumer_secret, username, password)
        if oauth_auth:
            try:
                import requests
                add_url = "https://www.instapaper.com/api/1.1/bookmarks/add"
                payload = {
                    'url': url,
                    'content': raw_content
                }
                if title:
                    payload['title'] = title
                res = requests.post(add_url, auth=oauth_auth, data=payload, timeout=15)
                if res.status_code == 200:
                    print(f"Successfully synced [Full-Text OAuth]: {title or url}")
                    return True
                else:
                    print(f"OAuth bookmark add failed ({res.status_code}): {res.text}. Falling back to Simple API...", file=sys.stderr)
            except Exception as e:
                print(f"OAuth bookmark add error ({e}). Falling back to Simple API...", file=sys.stderr)

    # 2. Simple API fallback
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
            "https://www.economist.com/the-world-this-week/rss.xml",
            "https://www.economist.com/europe/rss.xml",
            "https://www.economist.com/finance-and-economics/rss.xml",
            "https://news.google.com/rss/search?q=site:lemonde.fr+international+OR+politique+OR+Europe&hl=fr&gl=FR&ceid=FR:fr",
            "https://news.google.com/rss/search?q=site:euractiv.com+AND+(EU+OR+policy+OR+commission+OR+parliament)&hl=en-US&gl=US&ceid=US:en"
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
            raw_content = None
            title = None
            if "lemonde.fr" in resolved_url:
                lm_data = fetch_lemonde_full_content(resolved_url)
                if lm_data:
                    raw_content = lm_data['html']
                    title = lm_data['title']
                    print(f"  [Le Monde Extracted] Full article retrieved ({len(raw_content)} bytes)")
            elif "economist.com" in resolved_url:
                ec_data = fetch_economist_full_content(resolved_url)
                if ec_data:
                    raw_content = ec_data['html']
                    title = ec_data['title']
                    print(f"  [Economist Extracted] Full article retrieved ({len(raw_content)} bytes)")
            elif "ft.com" in resolved_url:
                ft_data = fetch_ft_full_content(resolved_url)
                if ft_data:
                    raw_content = ft_data['html']
                    title = ft_data['title']
                    print(f"  [FT Extracted] Full article retrieved ({len(raw_content)} bytes)")
            
            final_url = get_unlocked_archive_url(resolved_url) if not raw_content else resolved_url
            if sync_to_instapaper(username, password, final_url, title=title, raw_content=raw_content):
                success_count += 1
        print(f"Synced {success_count}/{len(args.urls)} articles to Instapaper.")
        
    elif args.auto:
        print("Fetching RSS feeds across categories...")
        pol_feeds = [
            "https://www.politico.eu/section/policy/feed/",
            "https://www.economist.com/the-world-this-week/rss.xml",
            "https://www.economist.com/europe/rss.xml",
            "https://www.economist.com/finance-and-economics/rss.xml",
            "https://news.google.com/rss/search?q=site:lemonde.fr+international+OR+politique+OR+Europe&hl=fr&gl=FR&ceid=FR:fr",
            "https://news.google.com/rss/search?q=site:euractiv.com+AND+(EU+OR+policy+OR+commission+OR+parliament)&hl=en-US&gl=US&ceid=US:en"
        ]
        ai_policy_feeds = [
            "https://news.google.com/rss/search?q=site:politico.eu+%22AI+Act%22+OR+%22AI+regulation%22+OR+%22chips%22&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=site:lemonde.fr+%22intelligence+artificielle%22+OR+IA&hl=fr&gl=FR&ceid=FR:fr",
            "https://news.google.com/rss/search?q=site:euractiv.com+%22artificial+intelligence%22+OR+%22AI+Act%22&hl=en-US&gl=US&ceid=US:en"
        ]
        ai_industry_feeds = [
            "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
            "https://arstechnica.com/tag/ai/feed/",
            "https://www.economist.com/science-and-technology/rss.xml",
            "https://news.google.com/rss/search?q=site:arstechnica.com+OR+site:theverge.com+AND+(OpenAI+OR+Anthropic+OR+Mistral)&hl=en-US&gl=US&ceid=US:en"
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
            
        print("Resolving and syncing selected articles with full-text verification...")
        success_count = 0
        for art in selected:
            title = art.get('title')
            url = art.get('link')
            resolved_url = resolve_google_news_url(url)
            
            raw_content = None
            if "lemonde.fr" in resolved_url:
                lm_data = fetch_lemonde_full_content(resolved_url)
                if lm_data:
                    raw_content = lm_data['html']
                    if not title:
                        title = lm_data['title']
                    print(f"  [Le Monde Extracted] Full subscriber article retrieved ({len(raw_content)} bytes)")
            elif "economist.com" in resolved_url:
                ec_data = fetch_economist_full_content(resolved_url)
                if ec_data:
                    raw_content = ec_data['html']
                    if not title:
                        title = ec_data['title']
                    print(f"  [Economist Extracted] Full article retrieved ({len(raw_content)} bytes)")
                else:
                    arch_url = get_unlocked_archive_url(resolved_url)
                    if arch_url != resolved_url:
                        resolved_url = arch_url
                        print(f"  [Economist Archive Mirror] {resolved_url}")
            elif "ft.com" in resolved_url:
                ft_data = fetch_ft_full_content(resolved_url)
                if ft_data:
                    raw_content = ft_data['html']
                    if not title:
                        title = ft_data['title']
                    print(f"  [FT Extracted] Full article retrieved ({len(raw_content)} bytes)")
                else:
                    # Check archive snapshot
                    arch_url = get_unlocked_archive_url(resolved_url)
                    if arch_url != resolved_url:
                        resolved_url = arch_url
                        print(f"  [FT Archive Mirror] {resolved_url}")
                    else:
                        print(f"  [FT Skipped] No subscriber session or archive mirror for {title}. Skipping paywall stub.", file=sys.stderr)
                        continue
            
            final_url = get_unlocked_archive_url(resolved_url) if not raw_content else resolved_url
            print(f"- Adding: {title or resolved_url} ({final_url})")
            if sync_to_instapaper(username, password, final_url, title=title, raw_content=raw_content):
                success_count += 1
                
        print(f"Successfully curated and synced {success_count} articles to Instapaper.")
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

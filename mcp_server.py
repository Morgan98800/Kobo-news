#!/usr/bin/env python3
import sys
import json
import urllib.request
import urllib.parse
import ssl
import os
from dotenv import load_dotenv

# Ensure all output goes to stderr unless it's MCP protocol JSON
def log(msg):
    print(msg, file=sys.stderr, flush=True)

load_dotenv(override=True)

INSTAPAPER_ADD_URL = "https://www.instapaper.com/api/add"

def host_text_on_rentry(title, text):
    """Hosts text on rentry.co (markdown pastebin) and returns the public URL."""
    html_content = f"<h1>{title}</h1>\n\n{text}"
    url = "https://rentry.co/api/new"
    data = urllib.parse.urlencode({'text': html_content}).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    req.add_header('Referer', 'https://rentry.co')
    
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=context) as response:
        resp_data = json.loads(response.read().decode('utf-8'))
        if resp_data.get('url'):
            return resp_data['url']
        raise Exception(f"Failed to host text: {resp_data}")

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
                log(f"Successfully synced: {url}")
                return True
            else:
                log(f"Failed to sync {url}. Status code: {status}")
                return False
    except urllib.error.HTTPError as e:
        if e.code == 403:
            log("Authentication failed: Check your Instapaper username and password.")
        else:
            log(f"HTTP Error {e.code}: {e.read().decode('utf-8', errors='ignore')}")
        return False
    except Exception as e:
        log(f"Error syncing {url}: {e}")
        return False

def handle_request(req):
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params", {})
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "kobo-news", "version": "1.0.0"},
                "capabilities": {"tools": {}}
            }
        }
    
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "send_to_instapaper",
                        "description": "Send a text article to Instapaper. This wraps the text in HTML and pushes it to Instapaper.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "The title of the article."},
                                "text": {"type": "string", "description": "The full text content of the article."}
                            },
                            "required": ["title", "text"]
                        }
                    }
                ]
            }
        }
        
    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})
        
        if tool_name == "send_to_instapaper":
            title = args.get("title")
            text = args.get("text")
            
            if not title or not text:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Missing title or text arguments"}
                }
            
            username = os.environ.get("INSTAPAPER_USERNAME")
            password = os.environ.get("INSTAPAPER_PASSWORD")
            
            if not username or not password:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": "Error: INSTAPAPER_USERNAME and INSTAPAPER_PASSWORD must be set in .env"}],
                        "isError": True
                    }
                }
            
            try:
                log(f"Hosting text for '{title}' on rentry.co...")
                public_url = host_text_on_rentry(title, text)
                log(f"Hosted URL: {public_url}")
                
                log("Syncing to Instapaper...")
                success = sync_to_instapaper(username, password, public_url, title)
                
                if success:
                    result_msg = f"Successfully pushed '{title}' to Instapaper."
                    is_error = False
                else:
                    result_msg = "Failed to push to Instapaper. Check server logs."
                    is_error = True
                    
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result_msg}],
                        "isError": is_error
                    }
                }
                
            except Exception as e:
                log(f"Tool execution failed: {e}")
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                        "isError": True
                    }
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Method not found"}
            }
            
    # Ignored notifications (like initialized)
    return None

def main():
    log("Starting Kobo-news MCP server...")
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            log("Invalid JSON received.")
            continue
            
        if req.get("jsonrpc") == "2.0":
            response = handle_request(req)
            if response:
                print(json.dumps(response), flush=True)

if __name__ == "__main__":
    main()

import os
import sys
import time
from dotenv import load_dotenv
from requests_oauthlib import OAuth1Session

def cleanup_old_articles(days=2):
    """
    Connects to the Instapaper Full API using OAuth 1.0a xAuth.
    Fetches the unread bookmarks and deletes those older than the specified number of days.
    """
    load_dotenv(override=True)
    CONSUMER_KEY = os.environ.get('INSTAPAPER_KEY')
    CONSUMER_SECRET = os.environ.get('INSTAPAPER_SECRET')
    USERNAME = os.environ.get('INSTAPAPER_USERNAME')
    PASSWORD = os.environ.get('INSTAPAPER_PASSWORD')

    if not all([CONSUMER_KEY, CONSUMER_SECRET, USERNAME, PASSWORD]):
        print("Missing OAuth credentials in .env. Skipping cleanup.", file=sys.stderr)
        return

    print("Authenticating with Instapaper Full API for cleanup...")
    # Authenticate via xAuth
    oauth = OAuth1Session(CONSUMER_KEY, client_secret=CONSUMER_SECRET)
    auth_url = 'https://www.instapaper.com/api/1/oauth/access_token'
    try:
        response = oauth.post(
            auth_url, 
            data={
                'x_auth_username': USERNAME, 
                'x_auth_password': PASSWORD, 
                'x_auth_mode': 'client_auth'
            }
        )
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to authenticate with Full API: {e}", file=sys.stderr)
        return

    creds = dict(t.split('=') for t in response.text.split('&'))
    inst = OAuth1Session(
        CONSUMER_KEY, 
        client_secret=CONSUMER_SECRET, 
        resource_owner_key=creds.get('oauth_token'), 
        resource_owner_secret=creds.get('oauth_token_secret')
    )

    print("Fetching unread bookmarks...")
    # Fetch bookmarks (limit 500 is max allowed per page)
    bookmarks_url = 'https://www.instapaper.com/api/1/bookmarks/list'
    try:
        resp = inst.post(bookmarks_url, data={'limit': 500})
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to fetch bookmarks: {e}", file=sys.stderr)
        return
        
    items = resp.json()
    
    # Calculate cutoff time (Unix timestamp)
    cutoff_time = time.time() - (days * 24 * 3600)
    
    deleted_count = 0
    for item in items:
        # The JSON returned is a mixed list of meta, user, and bookmark objects
        if isinstance(item, dict) and item.get('type') == 'bookmark':
            bookmark_time = item.get('time', 0)
            if bookmark_time < cutoff_time:
                b_id = item.get('bookmark_id')
                title = item.get('title', 'Unknown Title')
                print(f"- Deleting article older than {days} days: {title}")
                
                # Delete endpoint removes it entirely (better for Kobo space limits)
                del_url = 'https://www.instapaper.com/api/1/bookmarks/delete'
                del_resp = inst.post(del_url, data={'bookmark_id': b_id})
                
                if del_resp.status_code == 200:
                    deleted_count += 1
                else:
                    print(f"  Failed to delete {b_id}. Status: {del_resp.status_code}", file=sys.stderr)
                    
    print(f"Cleanup complete. Deleted {deleted_count} old articles.")

if __name__ == "__main__":
    # You can change the days parameter if you ever want a longer/shorter retention
    cleanup_old_articles(days=2)

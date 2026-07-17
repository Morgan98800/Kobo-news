# Kobo News

An automated system to fetch, select, and sync the best 5 European Union (EU) and policy news articles to your Instapaper account every morning. This is designed to sync seamlessly to your Kobo Clara Colour reader so you can start reading right after waking up.

## Features

- **Multi-source fetching**: Aggregates news from Politico Europe, Euractiv, and Google News RSS (searching for `"EU news OR EU policy OR Europe politics"`).
- **URL Resolving**: Automatically decodes Google News tracking/redirect links into their direct publisher URLs using `googlenewsdecoder`.
- **AI-curated selection**:
  - **Agent-driven**: The Antigravity agent fetches and selects the best articles using its own Gemini model, invoking the script with targeted URLs. No Gemini API key required!
  - **Standalone**: Run the script using your own `GEMINI_API_KEY` to let the script automatically query Gemini and sync.
- **Fail-safe fallback**: Falls back to the top chronological/relevance articles if no AI model or API key is available.

---

## Setup

### 1. Installation
The setup script creates a virtual environment and installs dependencies:

```bash
# Done automatically by the agent, or run manually:
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 2. Configuration
Create a `.env` file in the root of this directory by copying `.env.example`:

```bash
cp .env.example .env
```

Edit the `.env` file and fill in your Instapaper credentials:

```ini
# Instapaper Credentials
INSTAPAPER_USERNAME=your_email@example.com
INSTAPAPER_PASSWORD=your_instapaper_password

# Optional: Gemini API Key (Required ONLY for Standalone Mode)
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## Usage

### Standalone Mode (Auto-curation via Gemini API)
To fetch RSS feeds, automatically select the top 5 articles using Gemini, resolve their links, and sync them to Instapaper:

```bash
./venv/bin/python3 sync_to_instapaper.py --auto
```

### Agent Mode (Sync specified URLs)
To sync a list of specific URLs (used by the Antigravity agent or external selectors):

```bash
./venv/bin/python3 sync_to_instapaper.py --urls "https://example.com/article1" "https://example.com/article2"
```

---

## Scheduling

### Option A: GitHub Actions (Cloud Sync - Recommended if your computer sleeps)
This is 100% free and runs completely in the cloud. You do not need to keep your computer awake.

1. **Create a private repository** on GitHub.
2. **Push this folder** to your new repository:
   ```bash
   git init
   git add .
   git commit -m "Initialize news curator"
   git branch -M main
   git remote add origin <your-github-repo-url>
   git push -u origin main
   ```
3. **Configure GitHub Secrets**:
   Go to your GitHub repository -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret** and add:
   - `INSTAPAPER_USERNAME`: Your Instapaper email.
   - `INSTAPAPER_PASSWORD`: Your Instapaper password.
   - `GEMINI_API_KEY`: Your Gemini API key (optional, falls back to top stories if not provided).
4. The workflow is located at `.github/workflows/daily_sync.yml`. It will run automatically every morning at **6:30 AM EDT** (10:30 UTC). You can adjust the `cron` line in that file if you are in a different timezone.

---

### Option B: Antigravity Agent Scheduler
Uses the built-in agent scheduling engine to run on your local machine.

To schedule, we set up a recurring task that triggers every morning at 6:30 AM.

---

### Option C: Local macOS Crontab
If you prefer a standard local cron job on your machine (requires `GEMINI_API_KEY` in `.env`):

1. Open your crontab:
   ```bash
   crontab -e
   ```
2. Add the following entry to run the script every morning at 6:30 AM:
   ```text
   30 6 * * * cd /Users/morgancanteri/Documents/antigravity/amazing-galileo && ./venv/bin/python3 sync_to_instapaper.py --auto >> daily_sync.log 2>&1
   ```

---

### Option D: macOS launchd Agent
For a macOS background agent that will run even if the computer was asleep (and runs immediately upon wake-up if the time was missed):
Create a plist file at `~/Library/LaunchAgents/com.user.instapaper.sync.plist`.

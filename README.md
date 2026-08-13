# Kobo News

**🇬🇧 English**: This is a personal script that automatically curates the top EU policy news and syncs them to Instapaper for offline reading on a Kobo e-reader. It also deletes old articles after 2 days to save space.

**🇫🇷 Français**: Il s'agit d'un script personnel qui sélectionne automatiquement les meilleures actualités politiques de l'UE et les synchronise avec Instapaper pour une lecture hors ligne sur une liseuse Kobo. Il supprime également les anciens articles après 2 jours pour gagner de la place.

**🇪🇸 Español**: Este es un script personal que selecciona automáticamente las mejores noticias políticas de la UE y las sincroniza con Instapaper para leerlas sin conexión en un lector electrónico Kobo. También elimina los artículos antiguos después de 2 días para ahorrar espacio.

**🇮🇹 Italiano**: Questo è uno script personale che seleziona automaticamente le migliori notizie politiche dell'UE e le sincronizza con Instapaper per la lettura offline su un e-reader Kobo. Inoltre, elimina i vecchi articoli dopo 2 giorni per risparmiare spazio.

**🇩🇪 Deutsch**: Dies ist ein persönliches Skript, das automatisch die besten EU-Politiknachrichten kuratiert und sie mit Instapaper synchronisiert, um sie offline auf einem Kobo-E-Reader zu lesen. Es löscht auch alte Artikel nach 2 Tagen, um Platz zu sparen.

**🇵🇹 Português**: Este é um script pessoal que seleciona automaticamente as melhores notícias políticas da UE e as sincroniza com o Instapaper para leitura offline num e-reader Kobo. Ele também exclui artigos antigos após 2 dias para economizar espaço.
## Features

- **Multi-source fetching**: Aggregates news from **Politico Europe**, **Le Monde**, **Financial Times**, **The Economist & Espresso**, and targeted Google News RSS feeds.
- **Full-Text Subscriber Extraction**: Automatically fetches full subscriber HTML from *Le Monde* and *Financial Times*, uploading directly via Instapaper OAuth to prevent paywall truncation on Kobo.
- **URL Resolving & Archive Bypasses**: Automatically decodes Google News tracking/redirect links into their direct publisher URLs using `googlenewsdecoder` and routes paywalled articles through archive mirrors.
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

Edit the `.env` file and fill in your credentials:

```ini
# Instapaper Credentials
INSTAPAPER_USERNAME=your_email@example.com
INSTAPAPER_PASSWORD=your_instapaper_password

# Instapaper Full API (OAuth 1.0)
INSTAPAPER_KEY=your_key
INSTAPAPER_SECRET=your_secret

# Le Monde Credentials
LEMONDE_USERNAME=your_lemonde_email@example.com
LEMONDE_PASSWORD=your_lemonde_password

# Financial Times Credentials
FT_USERNAME=your_ft_email@example.com
FT_PASSWORD=your_ft_password

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

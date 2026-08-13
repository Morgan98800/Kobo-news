# Kobo News MCP Server

This is a local Model Context Protocol (MCP) server that exposes a single tool: `send_to_instapaper`.

It allows AI agents to directly push raw text articles to your Instapaper account. Instapaper does not natively support text uploads via its API, so this server transparently wraps the text in HTML, hosts it temporarily on `rentry.co`, and tells Instapaper to fetch it. This ensures perfect formatting on your Kobo e-reader.

## Features

- **MCP Integration**: Fully compliant stdio-based MCP server.
- **Auto-Hosting**: Automatically converts text payloads into readable HTML and hosts them via the free `rentry.co` API.
- **Instapaper Sync**: Pushes the generated URL directly to your Instapaper account.

## Setup

### 1. Configuration
Create a `.env` file in the root of this directory:

```bash
cp .env.example .env
```

Edit the `.env` file and fill in your Instapaper credentials:

```ini
INSTAPAPER_USERNAME=your_email@example.com
INSTAPAPER_PASSWORD=your_instapaper_password
```

### 2. Add to your MCP Client

Add the following configuration to your MCP client (e.g. Claude Desktop or Antigravity) to run this server. Replace the path with the absolute path to this directory on your machine.

**For Antigravity (`~/.gemini/antigravity/mcp_servers.json`) or Claude Desktop (`claude_desktop_config.json`):**

```json
{
  "mcpServers": {
    "kobo-news": {
      "command": "/Users/morgancanteri/Documents/antigravity/amazing-galileo/venv/bin/python3",
      "args": [
        "/Users/morgancanteri/Documents/antigravity/amazing-galileo/mcp_server.py"
      ],
      "env": {}
    }
  }
}
```

## Available Tools

- `send_to_instapaper(title: str, text: str)`: Generates a temporary webpage with the provided `text` and pushes it to your Instapaper account under the specified `title`.

# Etsy MCP — Setup Walkthrough

## 1. Create an Etsy developer account

1. Go to https://www.etsy.com/developers/register and sign in with your Etsy account.
2. Accept the API terms.

## 2. Create an app

1. Go to https://www.etsy.com/developers/your-apps and click **Create a New App**.
2. Fill in:
   - **Name:** Etsy MCP (or anything)
   - **Description:** Personal MCP server
   - **Website:** any URL you control (or `http://localhost`)
   - **What kind of app:** "I'm building an app for myself"
3. After creation, you'll see your **Keystring** (API key) and **Shared Secret**. Copy both.
4. Click **Edit** on your app and add this OAuth redirect URI:
   ```
   http://localhost:3003/callback
   ```
   Save.

## 3. Configure local environment

```bash
cd "/Users/sumit/Desktop/Etsy MCP"
cp .env.example .env
# Open .env and paste your Keystring + Shared Secret
```

## 4. Run the OAuth bootstrap

```bash
source .venv/bin/activate
python scripts/bootstrap_oauth.py
```

What happens:
1. Script opens your default browser to Etsy's authorization page.
2. Click **Allow Access**.
3. Browser redirects to `localhost:3003/callback`. The script captures the auth code.
4. Script exchanges the code for access + refresh tokens and writes them to `.tokens.json`.
5. Script prints your `shop_id`. Paste it into `.env` as `ETSY_SHOP_ID`.

If anything fails, the script prints a clear error. Re-run after fixing.

## 5. Wire MCP into Claude Code

Edit `~/.claude/claude_desktop_config.json` (or your project-scoped config) and add:

```json
{
  "mcpServers": {
    "etsy": {
      "command": "/Users/sumit/Desktop/Etsy MCP/.venv/bin/python",
      "args": ["/Users/sumit/Desktop/Etsy MCP/server.py"]
    }
  }
}
```

Restart Claude Code. From a chat, call `etsy_whoami` — you should see your shop info.

## 6. When refresh tokens expire (every 90 days)

You'll see this error from any tool:
```
{"error": "Refresh token expired. Re-run scripts/bootstrap_oauth.py", "code": "auth_expired"}
```

Just re-run `python scripts/bootstrap_oauth.py`. Takes 30 seconds.

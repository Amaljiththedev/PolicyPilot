# Integrations setup: Google sign-in, Google Drive, Slack, MCP

Everything below runs locally with Docker. None of it needs a public URL.

## 1. Google Cloud project (sign-in and Drive share it)

1. Go to https://console.cloud.google.com/ and create a project, e.g. `PolicyPilot`.
2. **APIs & Services → Library →** enable **Google Drive API**.
3. **APIs & Services → OAuth consent screen:** choose *External*, fill in the app name and your email. Under *Test users*, add your Google account and your friends' accounts (while the app is in testing, only test users can sign in).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID:**
   - Application type: **Web application**
   - Authorised redirect URI: `http://localhost:8000/api/v1/auth/google/callback`
5. Copy the client ID and secret into `.env`:

```
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=....
ADMIN_EMAILS=you@gmail.com
GOOGLE_ALLOWED_DOMAINS=          # optional, e.g. liverpool.ac.uk
```

6. Create an encryption key for Drive tokens and add it to `.env`:

```
docker compose exec api python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEY=<paste>
```

7. `docker compose up -d --build`

### Sign in
Open http://localhost:8000/api/v1/auth/google/login in a browser, choose your account, and you get JSON with an `access_token`. Paste it into Swagger's **Authorize** box.

Password sign-in is now off. For scripts and local testing:
`docker compose exec api python scripts/dev_token.py --email you@example.com --admin`

## 2. Google Drive sync

1. Signed in (token in Swagger), call `GET /api/v1/drive/connect` and open the returned `auth_url` in a browser. Approve read-only Drive access. The callback returns a `connection_id`.
2. Make a Drive folder for policies and put some documents in it (Google Docs, PDF, DOCX, TXT). The folder ID is the last part of its URL: `drive.google.com/drive/folders/<FOLDER_ID>`.
3. `POST /api/v1/drive/connections/{id}/folder` with `{"folder_id": "<FOLDER_ID>", "organisation": "Your Org"}`
4. `POST /api/v1/drive/connections/{id}/sync`, then `GET /api/v1/drive/connections` to see the report.
5. Edit a Google Doc in that folder and sync again: it becomes version 2 and the old text leaves search.

Automatic sync every 15 minutes: `docker compose --profile drive up -d`

## 3. Slack bot

1. https://api.slack.com/apps → **Create New App → From scratch**, pick your workspace.
2. **Socket Mode:** enable it, create an app-level token with `connections:write`, copy it (`xapp-...`).
3. **OAuth & Permissions → Bot Token Scopes:** `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `reactions:read`.
4. **Event Subscriptions:** enable, subscribe to bot events `app_mention`, `message.im`, `reaction_added`.
5. **App Home:** turn on the *Messages* tab so people can DM the bot.
6. **Install to Workspace**, copy the Bot User OAuth Token (`xoxb-...`).
7. `.env`:

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_ESCALATION_USER_ID=U0123456   # Slack member ID of the person who handles refusals (profile → ⋮ → Copy member ID)
SLACK_DEFAULT_ORGANISATION=         # optional: only answer from this organisation's policies
```

8. `docker compose --profile slack up -d --build`, invite the bot to a channel (`/invite @PolicyPilot`) and mention it, or DM it. React 👍/👎 on its answers to leave feedback.

## 4. MCP server (Claude Desktop, Cursor, ...)

Claude Desktop → Settings → Developer → Edit Config, add:

```json
{
  "mcpServers": {
    "policypilot": {
      "command": "docker",
      "args": ["compose", "-f", "C:\\Users\\amalj\\OneDrive\\Desktop\\WINTER ARC\\PolicyPilot\\docker-compose.yml",
               "exec", "-T", "api", "python", "-m", "app.mcp_server"]
    }
  }
}
```

Restart Claude Desktop. Tools: `ask_policy`, `search_policies`, `list_policies`, `policy_changes`. Answers go through the same citation checks as `/ask` and are logged with `source = mcp`.

# Email → Vikunja Task Pipeline

Turn emails into Vikunja tasks: IMAP ingest (allowlist-gated) → Redis → OpenAI extract → Vikunja create → SMTP ack reply.

**Run this on your home server with Docker Compose.** Do not start Compose on a laptop used only for editing.

## Architecture

| Service | Role |
|---------|------|
| `email-ingest` | IMAP poll/IDLE → **allowlist gate first** → parse → Redis enqueue → move to Processed / Quarantine |
| `redis` | Job queue + processed Message-ID set |
| `task-worker` | Consume jobs (trusted) → OpenAI JSON extract → Vikunja task + `needs-grooming` → SMTP ack |

Allowlist checks happen **only in ingest**. Non-allowlisted mail is moved to Quarantine and never enqueued. The worker does not re-check senders.

## Recommended mailbox

Use a **dedicated IMAP+SMTP mailbox with an app password** (provider-agnostic via `IMAP_*` / `SMTP_*`).

1. **Fastmail** (best fit) — create `todo@yourdomain.com` (or an alias). App password for IMAP + SMTP.
2. **Self-hosted mail** (Mailcow / docker-mailserver) — dedicated address + mailbox password.
3. **Gmail** — only if you already use it; App Password with 2FA. Prefer Fastmail when possible.

Create these IMAP folders (or let ingest create them on first connect):

- `Processed` — allowlisted mail after enqueue
- `Quarantine` — non-allowlisted mail

## One-time Vikunja setup

1. Create project **Email Inbox** (fallback for low confidence / unknown routing).
2. Create label **needs-grooming**.
3. Create any other projects/labels you want the model to choose from (e.g. Home, Work, urgent).
4. Create an API token with task create + label attach + project read (“Task management” preset is fine).
5. Note each project/label **ID** from the Vikunja UI or API.
6. Edit `config/projects.yaml` with those names and IDs.

## Home-server run steps

```bash
# on the home server
cd /path/to/agentic-email-todo
cp .env.example .env
# edit .env: IMAP, SMTP, ALLOWLIST_EMAILS, OPENAI_*, VIKUNJA_*
# edit config/projects.yaml with real Vikunja IDs

docker compose up -d --build
docker compose logs -f email-ingest task-worker
```

Send a test email **from an allowlisted address** to the mailbox. You should get:

1. Mail moved to `Processed`
2. A Vikunja task (always labeled `needs-grooming`)
3. An SMTP reply with the task link and a grooming summary

Non-allowlisted senders → `Quarantine`, no task.

## Environment variables

See `.env.example`. Important ones:

| Variable | Used by | Notes |
|----------|---------|--------|
| `ALLOWLIST_EMAILS` | ingest only | Comma-separated, case-insensitive |
| `IMAP_*` | ingest | Host, port, user, pass, folders |
| `SMTP_*` | worker | Ack replies |
| `REDIS_URL` | both | Compose sets `redis://redis:6379/0` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | worker | |
| `LLM_PROVIDER` | worker | `openai` or `openai_compatible` (+ `OPENAI_BASE_URL`) |
| `VIKUNJA_BASE_URL` | worker | e.g. `https://vikunja.example.com/api/v1` |
| `VIKUNJA_TOKEN` | worker | API token |
| `VIKUNJA_UI_BASE_URL` | worker | Deep links in ack emails |
| `VIKUNJA_FALLBACK_PROJECT` | worker | Default `Email Inbox` |
| `VIKUNJA_NEEDS_GROOMING_LABEL` | worker | Default `needs-grooming` |

## Redis job payload

Ingest pushes JSON to the Redis list `email_todo:jobs` (`LPUSH` / worker `BRPOP`):

```json
{
  "schema_version": 1,
  "message_id": "<...>",
  "from": "you@example.com",
  "from_header": "You <you@example.com>",
  "to": ["todo@yourdomain.com"],
  "cc": [],
  "subject": "...",
  "date": "2026-01-15T12:00:00+00:00",
  "text_body": "...",
  "html_body": "...",
  "attachments": [
    {
      "filename": "notes.txt",
      "content_type": "text/plain",
      "size_bytes": 123,
      "text_extract": "..."
    }
  ],
  "imap_uid": "42",
  "enqueued_at": "2026-01-15T12:00:05+00:00"
}
```

Attachments are summarized (filename + cheap text/PDF extract) only — **never uploaded** to Vikunja.

## Local LLM later

Set `LLM_PROVIDER=openai_compatible` and `OPENAI_BASE_URL` to an OpenAI-compatible endpoint. Same JSON schema; no code change required beyond env.

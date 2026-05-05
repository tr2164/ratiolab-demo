# FinSight — NYU Stern ACCT-GB.2350

A small full-stack web application that pulls real financial data from **SEC EDGAR**, lets you build financial ratios, and uses a **Large Language Model** to interpret them.

This is the codebase from the bonus session of **ACCT-GB.2350: Financial Data Management and Analysis** (NYU Stern, Spring 2026). It is the student copy: it ships **without** any working API keys. You will need to get your own free API key and wire it up before the app will run.

If you can read this file, follow it step by step, and end up with a running app, you have done what every junior engineer does on day one of a new job. That is the entire point.

---

## What this app does

1. You enter a public US company ticker (try `CAT` for Caterpillar).
2. The backend calls SEC EDGAR's `companyfacts` API and pulls the company's XBRL line items (balance sheet, income statement, cash flow).
3. You pick line items and build financial ratios out of them.
4. The app charts the ratios over time.
5. You click **"Run AI Analysis"**. The backend sends the ratios to an LLM with a structured prompt, parses the JSON response, and renders the analysis next to the numbers.

The **AI Analysis** is the part to pay attention to. It is just an HTTP request to a language model with a carefully written prompt. That is what every "AI-powered" product is, under the hood.

---

## What you need before you start

- A computer (Mac, Windows, or Linux) with at least 5 GB of free disk space.
- **Docker Desktop** installed and running.
  Download: <https://www.docker.com/products/docker-desktop/>
  (Free for personal/academic use. Alternatives that work the same way: [OrbStack](https://orbstack.dev/) on Mac, [Rancher Desktop](https://rancherdesktop.io/), [Podman Desktop](https://podman-desktop.io/).)
- **Git** installed. <https://git-scm.com/downloads>
- A web browser.
- A free **Groq API key** (we will get this in Step 2 below).
- About 15 minutes the first time.

You do **not** need to install Python or Node.js — Docker handles that for you.

---

## Step 1 — Clone this repo

Open a terminal (on Mac: Spotlight → "Terminal"; on Windows: Start → "Git Bash" or "PowerShell") and run:

```bash
git clone https://github.com/<YOUR_INSTRUCTORS_GITHUB_USERNAME>/<REPO_NAME>.git
cd <REPO_NAME>
```

Replace the placeholders with the actual repo URL your instructor shared on Brightspace. After this command you should see a directory containing this `README.md` file, plus `backend/`, `frontend/`, and `docker-compose.yml`.

---

## Step 2 — Get a free Groq API key

The app uses Groq (a fast, free LLM provider) for the AI analysis call. Getting a key takes about 2 minutes.

1. Go to <https://console.groq.com>.
2. Click **"Sign up"**. You can use your school email or sign in with Google.
3. No credit card is required. The free tier allows 30 requests per minute, which is plenty.
4. Once you're in, click **"API Keys"** in the left sidebar.
5. Click **"Create API Key"**. Give it a name like `nyu-class-demo`.
6. **Copy the key immediately and paste it somewhere safe.** It starts with `gsk_`. Groq will only show it to you once. If you lose it, you can always create another one.

> **Why we are not using ChatGPT / Gemini directly:**
> OpenAI requires a phone number and gives only a small free trial. Google AI Studio (Gemini) is blocked for many academic Google Workspace accounts. Groq is the path of least friction for this class. The code is provider-agnostic — see the bottom of `.env.example` for how to use OpenAI, OpenRouter, or Gemini instead.

---

## Step 3 — Create your `.env.local` file

This is the step the app deliberately makes you do yourself. Without it, the app will not start.

In the project root (the same directory as `docker-compose.yml`), run:

```bash
cp .env.example .env.local
```

This makes a copy of the template at `.env.local`. Then open `.env.local` in any text editor (VS Code, Sublime, Notepad, `nano`, whatever you have) and find this line:

```
OPENAI_API_KEY=                                   # <-- paste your gsk_... key here
```

Paste your Groq API key right after the `=` sign, no spaces, no quotes:

```
OPENAI_API_KEY=gsk_abcdef0123456789...
```

Save and close the file.

> **Why is this file gitignored?**
> Because anyone who gets their hands on your API key can run up usage charges on your account. The `.gitignore` file at the project root tells git to never commit `.env.local`, even if you `git add .` everything. Verify with `git status` — you should NOT see `.env.local` in the list of files to be committed.

---

## Step 4 — Start the app

From the project root, run:

```bash
docker compose up --build
```

The first time you run this it will take 5–10 minutes because Docker has to download images and install all dependencies. Subsequent starts take about 15 seconds.

You will know it is ready when you see lines that look like:

```
backend-1   | INFO:     Uvicorn running on http://0.0.0.0:8001
frontend-1  |  ✓ Ready in 15s
```

Leave this terminal open while you use the app. Closing it shuts everything down.

> **If you get an error like `required file .env.local is missing`:**
> You skipped Step 3. Go back and create `.env.local` from `.env.example`.

---

## Step 5 — Open the app in your browser

In a new browser tab go to:

<http://localhost:3003/modules/ratiolab>

You should see the FinSight Ratio Lab. Try this flow:

1. Search for ticker `CAT` (Caterpillar Inc.).
2. **Layer 1**: select 4–6 line items (e.g., Total Current Assets, Total Current Liabilities, Long-Term Debt, Total Stockholders Equity, Revenues, Net Income).
3. Click **Next** to move through the layers, or jump straight to **Layer 3 — Build Ratios**.
4. Click a ratio template (Current Ratio, Debt to Equity), then **Compute**.
5. **Layer 4 — Dashboard**: click **Run AI Analysis**. After ~2 seconds, the LLM's analysis appears in the side panel.

Other useful URLs:

| What | URL |
|------|-----|
| The frontend | <http://localhost:3003> |
| Backend's auto-generated API docs | <http://localhost:8005/docs> |
| Direct example API call | <http://localhost:8005/api/statements/CAT/line-items> |

---

## How to stop everything

In the terminal where Docker is running, press `Ctrl-C`. Or in a different terminal:

```bash
docker compose down            # stop containers, keep your database
docker compose down -v         # stop containers AND wipe the database/cache
```

---

## Common problems and how to fix them

### "port is already allocated" / "address already in use"

Something else on your computer is using one of the ports the app needs. The app uses three:

| Port | Service |
|------|---------|
| `3003` | Frontend |
| `8005` | Backend |
| `5435` | Postgres database |

Stop whatever else is using them, **or** edit `docker-compose.yml` and change the host-side port number. Look for lines like:

```yaml
ports:
  - "127.0.0.1:3003:3001"
```

The first number (`3003`) is the port you'll open in your browser. Change it to anything free, like `3010`. The second number (`3001`) is internal to Docker — leave it alone.

### "CERTIFICATE_VERIFY_FAILED" or other SSL errors

This usually only happens on a **corporate-issued laptop** that performs SSL inspection on outgoing HTTPS traffic (common at PwC, Deloitte, EY, KPMG, banks, etc.). Three options, in order of preference:

1. Try a different network — home Wi-Fi, your phone's hotspot, or NYU campus Wi-Fi without VPN.
2. If you must stay on the corporate network, open `.env.local` and add this line:
   ```
   INSECURE_SSL_VERIFY=true
   ```
   This disables TLS certificate verification. The code prints a loud warning when it's enabled. **Do not commit this setting.** It is for local development only.
3. Ask your IT department for the corporate root CA certificate so you can wire it up properly. (Out of scope for this class.)

### "Docker Desktop is not running"

Open Docker Desktop from your Applications / Start Menu first. Wait until the whale icon in the menu bar / system tray is steady (not animated). Then try `docker compose up --build` again.

### The AI analysis returns a generic, unhelpful answer

That is the lesson. Open `backend/app/routers/statements.py` and look for `RATIO_ANALYSIS_PROMPT`. The prompt is the product. Edit it, save the file (uvicorn auto-reloads), and click "Run AI Analysis" again. You will see the output change.

### Anything else

When you ran `docker compose up`, the terminal showed log output. The error messages tell you what failed. Read them. If you can't figure it out, paste the last 30 lines of output into the LLM you have open (literally any LLM — that's the whole point of the course) and ask "what does this mean and how do I fix it?"

---

## What you're looking at (architecture)

```
finsight/
├── frontend/                   Next.js 14 app — what you see in the browser
│   └── src/app/modules/ratiolab/   The Ratio Lab UI
│
├── backend/                    Python FastAPI server
│   └── app/
│       ├── routers/statements.py   The /api/statements/* HTTP endpoints
│       │                           (this is where RATIO_ANALYSIS_PROMPT lives)
│       └── services/
│           ├── llm_service.py      The HTTP call to the LLM provider
│           └── sec_data.py         Pulls XBRL data from SEC EDGAR
│
├── docker-compose.yml          Tells Docker how to wire it all together
├── .env.example                Template for environment variables (this is in git)
├── .env.local                  YOUR config with YOUR key (NOT in git)
└── README.md                   This file
```

The frontend talks to the browser. The backend talks to SEC EDGAR (for data) and to Groq (for analysis). Postgres stores small bits of state. Everything is wired together by Docker so you don't have to install Python or Node yourself.

---

## What we covered in class

- **Block 1 — "What's behind ChatGPT"**: a `curl` to Groq's API. The whole AI industry is wrappers around requests like that one.
- **Block 2 — "Tour of an app"**: this is that app. Frontend, backend, environment variables, external API keys.
- **Block 3 — "Build a feature live"**: the Run AI Analysis button. We added the prompt, the API call, and the rendering.
- **Block 4 — "GitHub basics"**: cloning this repo, making changes, pushing them somewhere a teammate can see.

If you want to go further:
- Modify `RATIO_ANALYSIS_PROMPT` in `backend/app/routers/statements.py`.
- Try a different ticker, like `DE` (John Deere) or `AGCO`.
- Try a different model — change `DEFAULT_LLM_MODEL` in `.env.local` to `llama-3.1-8b-instant` (faster) or `gemma2-9b-it` (smaller).
- Try a different provider — see the bottom of `.env.example` for OpenAI, OpenRouter, or Gemini config.
- Fork the repo on GitHub, make a change, open a pull request to your instructor's repo. That is how every modern software team works.

---

## Course / contact

ACCT-GB.2350 — Financial Data Management and Analysis  
Spring 2026 — NYU Stern  
Travis Ringger

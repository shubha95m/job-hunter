# 🚀 Job Hunter & Recruiter Intelligence Agent

An autonomous, multi-platform job application engine, personal CRM, and Model Context Protocol (MCP) server. Built for **LinkedIn**, **Naukri**, and **Company ATS Portals** (Workday, Greenhouse, Lever, etc.), designed to run seamlessly with AI IDEs like **Antigravity IDE**, **Cursor**, **Windsurf**, and **Claude Code**.

---

## 🌟 Key Highlights & Why It's Built Differently

- 🤖 **Native AI IDE Intelligence (Zero External LLM Cost):** You don't need expensive third-party LLM API keys. When running inside an AI IDE, the IDE itself provides the reasoning, while the local deterministic engine drives Playwright headlessly in the background.
- 🗄️ **Unified Local CRM & Real-Time Sync:** Fully local SQLite database (`applications.db` with WAL mode) with real-time atomic JSON mirroring (`applications_tracker.json`). Zero data loss, zero remote tracking.
- ⭐ **Opportunity Wishlist & Package Tracking:** Search high-paying roles (e.g., > ₹1 Crore / $120k+ USD), bookmark them in a Wishlist with salary notes, and apply when ready.
- 🔄 **Auto-Purge on Apply:** When you apply to a wishlisted job, it is automatically removed from the Wishlist, moved to active Applications, and inherits its package/notes.
- 🤝 **Recruiter Touchpoint Cadence Engine:** Day 0 (Applied) ➔ Day 2 (Warm Recruiter Connection) ➔ Day 7 (Follow-up DM) with a 24-hour company deduplication guard.
- 🎯 **Keyword Gap Audit & Compatibility Scorer:** Tool `audit_job_compatibility` contrasts your profile against any job description, scores compatibility, reveals missing keyword gaps, and crafts interview talking points.
- 📝 **Strict Single-Page Targeted Cover Letter:** Tool `generate_targeted_cover_letter` drafts tailored 3-paragraph executive pitches (Crossplane, Playwright MCP, Kubernetes test runners) and renders crisp, strictly 1-page A4 PDFs with zero truncation.
- 🏢 **Automated Interview Prep & Company Dossier:** Tool `generate_interview_dossier` compiles Product vs Service intel, funding/valuation, leadership, recent/upcoming events, and 6 high-probability Staff SDET technical questions with winning answers and strategic reverse-interview questions.
- 🔒 **100% Private & Git-Safe:** All sessions (`.auth/`), databases (`applications.db`), trackers, and personal resumes/cover letters (`*.pdf`) are strictly excluded in `.gitignore`.

---

## ⚡ Core Architecture

```text
               AI Agent / MCP Client (Antigravity IDE, Cursor, Claude, Windsurf)
                                       │
                                       ▼
                              mcp_engine/server.py
                            (Universal MCP Protocol)
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
  platforms/linkedin/           platforms/naukri/                 portals/
   ├── api.py (Voyager REST)     ├── api.py (Naukri Gateway)     ├── agent.py (Phase 2 ATS)
   ├── dom.py (Playwright UI)    └── quick_apply.py              ├── workday.py
   └── easy_apply.py (Phase 1)                                   └── base.py
         │                             │                             │
         └─────────────────────────────┼─────────────────────────────┘
                                       ▼
                               runtime/crm.py
                        (SQLite WAL + applications_tracker.json)
```

---

## 📦 Step-by-Step Installation & Setup

### Step 1: Clone the Repository & Set Up Virtual Environment

```bash
# 1. Clone the repository
git clone https://github.com/shubha95m/job-hunter.git
cd job-hunter

# 2. Create and activate a Python 3.10+ virtual environment
python3 -m venv venv
source venv/bin/activate       # On macOS / Linux
# .\venv\Scripts\activate      # On Windows (PowerShell)

# 3. Upgrade pip and install all dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Install Playwright browser binaries
playwright install chromium
```

---

### Step 2: One-Time Authentication (Saved Locally)

Run the login script once to capture your authenticated browser cookies:

```bash
# Authenticate LinkedIn
python auth.py --linkedin

# Authenticate Naukri
python auth.py --naukri
```

A browser window will open. Log into your account as usual. Once logged in, close the browser window.
- Cookies are saved locally in `.auth/state.json` (LinkedIn) and `.auth/naukri_state.json` (Naukri).
- **Security:** `.auth/` is strictly in `.gitignore` and never leaves your computer.

---

### Step 3: Configure Your Candidate Profile

Copy the template to create your personal profile:

```bash
cp profile_template.yaml profiles/my_profile.yaml
```

Edit `profiles/my_profile.yaml` with your information:
- **Contact Details:** Name, email, mobile phone, location.
- **Job Preferences:** Target roles (`Staff SDET`, `Lead QA`), locations, min package.
- **Standard Screening Answers:** Notice period (e.g. `30`), years of experience (e.g. `10`), legal authorization, visa sponsorship.
- **Resume File / Web CV (Saved in local root folder):**
  ```yaml
  resume_path: "my_resume.pdf"
  resume_under1mb_path: "my_resume.pdf"
  ```
  *(Store all CV PDFs directly in the local repository root directory — they are strictly git-ignored).*

Set your active profile in `.env`:
```env
PROFILE=my_profile
```

---

### Step 4: Environment Configuration & Automated Email Setup (`.env`)

Job Hunter features an autonomous interview intelligence engine that analyzes company profiles and delivers comprehensive briefing dossiers and PDF prep packs directly to your inbox. All communication settings are strictly environment-driven with **zero hardcoding**.

Copy the environment template to create your local `.env`:
```bash
cp .env.template .env
```

#### 1. Mapping Required Variables in `.env`
Open `.env` in your editor and configure your variables:

| Environment Variable | Description | Example / Default |
| :--- | :--- | :--- |
| `PROFILE` | The YAML profile name in `profiles/` (without `.yaml`) | `my_profile` |
| `RECIPIENT_EMAIL` | Dedicated destination inbox where your dossiers and alerts arrive | `your_inbox@gmail.com` |
| `SENDER_EMAIL` | Gmail / Google Workspace address used to dispatch the emails | `your_inbox@gmail.com` |
| `EMAIL_APP_PASSWORD` | 16-character Google App Password (spaces optional) | `abcd efgh ijkl mnop` |
| `SMTP_HOST` | *(Optional)* SMTP server host | `smtp.gmail.com` |
| `SMTP_PORT` | *(Optional)* SMTP port (SSL) | `465` |
| `RESUME_PATH` | *(Optional)* Default single-page CV filename in root folder | `my_resume.pdf` |

---

#### 2. How to Generate a Google App Password (Step-by-Step)
For security, Gmail does not allow direct SMTP login with your standard Google password. You must generate a dedicated **16-character App Password**:

1. **Open Google Account Settings:**  
   Navigate to [https://myaccount.google.com/](https://myaccount.google.com/).
2. **Ensure 2-Step Verification is Active:**  
   - In the left sidebar, click **Security**.
   - Under *"How you sign in to Google"*, verify that **2-Step Verification** is turned **ON**. *(Google mandates 2FA to create app-specific passwords)*.
3. **Navigate to App Passwords:**  
   - In the top search bar inside Google Account, search for **"App passwords"** and select it.  
   - Alternatively, visit the direct URL: [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
4. **Create a Dedicated App Password:**  
   - In the **App name** field, type a label such as `Job Hunter Engine` or `Interview Assistant`.
   - Click **Create**.
5. **Copy the 16-Character Password:**  
   - Google will display a 16-character code (e.g., `abcd efgh ijkl mnop`).
   - Copy this code immediately (it is only shown once).
6. **Paste into `.env`:**  
   ```env
   RECIPIENT_EMAIL="your_destination@gmail.com"
   SENDER_EMAIL="your_sender@gmail.com"
   EMAIL_APP_PASSWORD="abcd efgh ijkl mnop"
   ```

---

> [!CAUTION]
> ### 🔒 Critical Security & Confidentiality Notice
> - **NEVER share your Gmail App Password with ANYONE**: An App Password grants direct SMTP access to send emails from your Google account. Treat it with the same sensitivity as a root private key.
> - **NEVER commit `.env` to Git**: Your `.env` contains personal credentials and must NEVER be pushed to GitHub or any public remote. The file is strictly enforced in [.gitignore](.gitignore).
> - **Zero Hardcoding Guarantee**: The Job Hunter codebase contains **zero hardcoded email addresses or credentials**—all communication routing reads strictly from your local `.env`.
> - **Never paste `.env` into public issues, screenshots, chat groups, or pull requests**.

---

### Step 5: Configure Visual SQLite Viewer in Your IDE

The CRM uses `applications.db` to guarantee zero data loss. To view and filter your jobs visually inside your editor:

1. Press `Cmd + Shift + X` (or `Ctrl + Shift + X`) to open the **Extensions** panel.
2. Search for: **`SQLite Viewer`** (by Florian Klampfer / `qwtel.sqlite-viewer`).
3. Click **Install**.
4. Open the file tree and click on **`applications.db`**.
   - It will open as an interactive, sortable, filterable spreadsheet directly in your editor tab!
   - You can toggle between `wishlist`, `applications`, and `touchpoint_logs` with a single click.

> **Zero Sync Worries:** `applications.db` and [applications_tracker.json](applications_tracker.json) are automatically mirrored in real-time on every single write. If you prefer JSON, just open `applications_tracker.json`!

---

## 🔌 Connecting MCP in AI IDEs (Antigravity, Cursor, Windsurf, Claude)

The universal MCP server exposes 30+ tools for recruiter searches, messaging, application logging, and Wishlist management.

Get your absolute repository path by running:
```bash
pwd
# Example: /Users/username/job-hunter
```

### 1. Google Antigravity IDE
Add the MCP configuration to `.agents/mcp_config.json` (workspace) or `~/.gemini/config/mcp_config.json` (global):

```json
{
  "mcpServers": {
    "job-hunter": {
      "command": "/Users/username/job-hunter/venv/bin/python3",
      "args": ["/Users/username/job-hunter/mcp_engine/server.py"],
      "env": {
        "PYTHONPATH": "/Users/username/job-hunter"
      }
    }
  }
}
```

### 2. Cursor
Go to **Cursor Settings** ➔ **Features** ➔ **MCP Servers** ➔ click **Add New MCP Server**, or edit `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "job-hunter": {
      "command": "/Users/username/job-hunter/venv/bin/python3",
      "args": ["/Users/username/job-hunter/mcp_engine/server.py"],
      "env": {
        "PYTHONPATH": "/Users/username/job-hunter"
      }
    }
  }
}
```

### 3. Claude Desktop
Add under `"mcpServers"` in:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "job-hunter": {
      "command": "/Users/username/job-hunter/venv/bin/python3",
      "args": ["/Users/username/job-hunter/mcp_engine/server.py"]
    }
  }
}
```

### 4. Windsurf / VS Code (Roo Code / Cline)
Add under your MCP settings:

```json
{
  "mcpServers": {
    "job-hunter": {
      "command": "/Users/username/job-hunter/venv/bin/python3",
      "args": ["/Users/username/job-hunter/mcp_engine/server.py"]
    }
  }
}
```

---

## 💬 How to Use in Your AI IDE: Ready-to-Use Prompts

Once open in your AI IDE, you don't need to write manual scripts — just prompt your AI assistant naturally:

### 1. Job Discovery & Wishlist (High Package Filter)
> *"Search for Staff SDET or Quality Architect jobs in Pune and Remote paying over ₹1 Crore (or $120k+ USD). Save the best matching opportunities into my Wishlist with package notes."*

### 2. Single-Page Web CV Setup
> *"Download my single-page web resume from my portfolio URL, compile it to an A4 PDF under 200 KB in the local root folder, and set it as my active CV in my profile."*

### 3. Applying to Wishlist Jobs
> *"Look at my Wishlist. For all jobs where Easy Apply is True, apply to them headlessly in Playwright using my single-page CV, then verify they are moved to the Applied pipeline."*

### 4. Recruiter Discovery & Cadence Follow-Ups
> *"Check my application tracker. Are there any recruiter follow-ups due today? If so, find the hiring recruiter for that company on LinkedIn and draft a warm 300-character connection note."*

### 5. Keyword Gap Audit & Match Score
> *"Run an audit on the job description for Kaseya (or any job URL). Contrast my profile against the requirements, give me my compatibility score, highlight missing keyword gaps, and generate interview talking points."*

### 6. Single-Page Targeted Cover Letter Generation
> *"Generate a tailored 3-paragraph executive cover letter for the Kaseya Staff SDET role emphasizing my Crossplane, Playwright MCP, and Kubernetes projects. Output it as a strict single-page PDF with zero overflow."*

### 7. Automated Interview Prep & Company Dossier
> *"Generate a complete interview prep dossier for Kaseya for the Staff SDET position. Fetch their engineering leadership, analyze their tech stack, provide 6 high-probability technical questions with winning answers tailored to my 10-year Staff SDET profile, and draft strategic reverse-interview questions to ask their VP/Director."*

### 8. End-to-End Interview Intel & Email Dispatch (Native AI IDE Tool)
> *"Run `send_interview_prep_email(company_name='TalAstra HR Consultants (AI Pod)')`. Analyze the exact job description and company profile as an interviewer for my experience level, generate comprehensive deep-dive questions with winning answers, format IDE code demonstrations, render a multi-page PDF, and deliver everything to my email."*

### 9. Check Pipeline & Sync Health
> *"Show me a summary of my active pipeline, breakdown by platform, and confirm that `applications.db` and `applications_tracker.json` are in sync."*



---

## 🆘 "What If Something Fails?" (How to Ask Your AI)

If you hit a roadblock (e.g. cookie expired, modal stuck, or custom portal), simply ask your AI IDE with these exact prompt patterns:

| Problem | Prompt to Give Your AI IDE |
|---|---|
| **LinkedIn or Naukri logged out** | *"My session expired. Can you launch `python auth.py --linkedin` so I can log in and save fresh cookies?"* |
| **New questionnaire question** | *"The application modal is asking a custom question about salary expectation. Can you update `profiles/my_profile.yaml` with my answer and retry?"* |
| **Want to sync manual edits** | *"I edited `applications_tracker.json` manually to add notes. Run `./venv/bin/python3 runtime/crm.py --sync-from-json` to sync them into `applications.db`."* |
| **Need to inspect database** | *"Run `sqlite3 -header -table applications.db 'SELECT id, company, role_title, package FROM wishlist;'` and show me what's stored."* |

---

## ✅ Verification & Success Checklist

Run this command anytime to verify your CRM health:

```bash
./venv/bin/python3 runtime/crm.py
```

Expected output:
```json
CRM Status (SQLite & JSON in Sync):
{
  "total_applications_tracked": 1,
  "active_pipeline": 1,
  "total_wishlist_saved": 2,
  "pending_followups_due": 0,
  "breakdown_by_status": {
    "APPLIED": 1
  },
  "breakdown_by_platform": {
    "LinkedIn": 1
  },
  "database_path": ".../job-hunter/applications.db",
  "json_tracker_path": ".../job-hunter/applications_tracker.json"
}
```

🎉 **Great! You have completed the setup and are ready to hunt jobs autonomously!** 🚀
# Job Hunter & LinkedIn MCP Agent

An intelligent, autonomous job application agent and enterprise LinkedIn MCP (Model Context Protocol) server powered by Playwright, Python, and LLM integrations.

---

## ⚡ Core Architecture: Hybrid, Multi-Platform Engine

Job Hunter uses a modular, multi-platform architecture designed for high-speed execution, self-recycling browser sessions, and cross-platform recruiter intelligence:

```text
               AI Agent / MCP Client (Antigravity, Cursor, Claude, Codex)
                                      │
                                      ▼
                           mcp_engine/server.py
                       (linkedin_mcp.py facade)
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
  platforms/linkedin/           platforms/naukri/               portals/
   ├── api.py (Voyager REST)     ├── api.py (Naukri Gateway)    ├── agent.py (Phase 2 ATS)
   ├── dom.py (Playwright UI)    └── dom.py (1-Click Apply)     ├── workday.py
   └── easy_apply.py (Phase 1)                                  └── base.py
         │                            │                            │
         └────────────────────────────┼────────────────────────────┘
                                      ▼
                                   runtime/
         ├── browser_pool.py (Self-recycling Playwright context pool)
         ├── session_store.py (Isolated multi-account cookie manager)
         ├── rate_limiter.py (Token-bucket rate limiter with jitter)
         └── dom_utils.py (Resilient clicking & loader synchronization)
```

### 1. Direct Platform REST APIs (`platforms/<platform>/api.py`)
- Reads authenticated session cookies (`JSESSIONID`, `li_at`, etc.) from `.auth/`.
- Makes direct HTTP requests via `httpx.Client` to platform backend endpoints.
- **Speed:** Responses return in **100–300ms** without launching a browser.
- **Used for:** Profile inspection, work experience, skill extraction, unread message checks, job details, and CV-to-job matching.

### 2. High-Performance Browser Context Pool (`runtime/browser_pool.py`)
- Maintains a lazy-initialized Chromium process and leases isolated browser contexts.
- Auto-recycles contexts every 20 operations to eliminate memory leaks.
- Avoids cold-start browser boot latency across sequential MCP calls.
- **Used for:** Recruiter discovery, public people searches, connection requests, and message dispatch.

---

## 🚀 Autonomous Job Application Pipeline

The automation workflow is cleanly separated into specialized modules:

### Phase 1: In-Platform Quick Apply (`platforms/linkedin/easy_apply.py`, `platforms/naukri/quick_apply.py`, `agent.py`)
- **LinkedIn Easy Apply:** Autonomously detects Easy Apply modals, fills multi-step forms (experience years, radio buttons, dropdowns, resume attachment, disclosures), and uses token-tracked LLM assistance for custom screening questions.
- **Naukri Quick Apply:** Seamlessly identifies modern Naukri `Quick apply` cards, matches role criteria, executes 1-click in-platform submission, handles screening questionnaires, and logs applied jobs.


### Phase 2: External Enterprise ATS Portals (`portals/agent.py`, `external_portal_agent.py`)
- Platform-agnostic engine that takes over when a job redirects to external company career portals (e.g., **Workday**, **Greenhouse**, **Lever**, **Taleo**, **iCIMS**, **Ashby**).
- **Automated Portal Features:**
  - **Account Creation / Login:** Detects authentication requirements and creates candidate portal accounts using configured credentials.
  - **Resume Upload & Constraints:** Handles file upload triggers and automatically switches to optimized files if size limits (e.g., Workday 1MB) are detected.
  - **Enterprise Field Pre-population:** Populates multi-section forms (Contact Details, Address, Work Authorization, EEO Demographics, Education & Employment History).
  - **Multi-Step Progression:** Navigates multi-page Workday/ATS wizards with spinner synchronization and step-by-step progress tracking.

---


## 🛠️ LinkedIn MCP Server Tools Overview

The included universal Model Context Protocol server (`mcp.py`) exposes 30+ tools and operating guideline resources to AI coding environments (e.g., Antigravity, Cursor, Claude Code):

### MCP Operating Guidelines Resources
AI agents connected to this MCP server can read standard resources for cross-platform workflows:
- `guidelines://cross-platform-workflow` — Complete guide on combining Naukri job discovery with LinkedIn recruiter mapping and DMs.
- `guidelines://outbound-dm-templates` — Proven cold outreach templates referencing job URLs from Naukri or LinkedIn.
- `guidelines://platform-capabilities` — Capabilities matrix comparing Naukri Quick Apply vs LinkedIn member graph.

### Tools Overview

| Tool Name | Engine | Description |
|---|---|---|
| `search_cross_platform_jobs` | Naukri + LinkedIn | Aggregates jobs from both platforms, tags origin (`[Platform: Naukri]` / `[Platform: LinkedIn]`), maps LinkedIn recruiters for each company, and provides pre-drafted DMs. |
| `draft_recruiter_pitch` | Local Engine | Generates tailored outreach pitches for recruiters citing specific job URLs and platform origins. |
| `get_intro` | Voyager API | Returns full name, headline, vanity URL, and occupation. |
| `get_about` | Voyager API | Fetches profile about/summary section. |
| `get_experience` | Voyager API | Lists all work experiences, company names, titles, and dates. |
| `get_skills` | Voyager API | Retrieves all endorsed skills and proficiencies. |
| `get_education` | Voyager API | Lists universities, degrees, and dates. |
| `get_certifications` | Voyager API | Lists professional licenses and certifications. |
| `get_unread_messages` | Voyager API | Retrieves unread direct message threads. |
| `get_job_details` | Voyager API | Extracts structured title, company, description, and criteria for a job. |
| `get_company_info` | Voyager API | Fetches employee count, headquarters, and industry for a company. |
| `match_jobs_to_cv` | Voyager API | Compares current job listings against your CV text. |
| `review_linkedin_against_cv`| Voyager API | Audits profile headline/summary/skills against a local CV. |
| `search_recruiters` | Playwright | Finds active talent acquisition partners and recruiters for a company. |
| `search_people_at_company` | Playwright | Finds employees matching a target role at a specific company. |
| `find_person` | Playwright | Searches for individuals across 1st and public networks. |
| `get_person_profile` | Voyager API | Inspects full public profile details for a person. |
| `send_dm` | Playwright | Sends direct messages *(requires user confirmation)*. |
| `connect_with_person` | Playwright | Dispatches connection requests with custom notes *(requires confirmation)*. |
| `create_post` | Playwright | Publishes a LinkedIn feed post *(requires confirmation)*. |
| `naukri_get_profile` | Playwright | Diagnostic check of Naukri session state and live candidate profile details. |
| `naukri_search_jobs` | Playwright | Searches jobs on Naukri and returns structured cards with Quick Apply status. |
| `naukri_search_recruiters` | Playwright | Discovers recruiters hiring on Naukri for target companies. |
| `naukri_update_headline` | Playwright | Updates candidate resume headline on Naukri *(requires confirmation)*. |
| `naukri_quick_apply` | Playwright | Submits Phase 1 Quick Apply applications on Naukri *(requires confirmation)*. |

> **Safety Guard:** Any mutating or communication action (`send_dm`, `connect_with_person`, `create_post`, `update_*`, `naukri_update_headline`, `naukri_quick_apply`) strictly requires `confirmed=True` to prevent accidental actions.



---

## 📦 Installation & Setup

### 1. Prerequisites
- Python 3.10+
- Google Chrome or Chromium

### 2. Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 3. One-Time Authentication
Run the interactive login script for your platform of choice:

```bash
# Authenticate with LinkedIn (default)
python auth.py --linkedin

# Authenticate with Naukri
python auth.py --naukri
```
A visual browser window will open. Log into your account. Once logged in, close the browser window. Your authenticated session cookies will be stored locally in `.auth/` (`.auth/state.json` for LinkedIn, `.auth/naukri_state.json` for Naukri).

> **Security Note:** `.auth/` and `.env` are strictly excluded in `.gitignore`. Never commit or publish session storage files.

### 4. Configure Your Profile
Create your personal profile by copying the template:
```bash
cp profile_template.yaml profiles/my_profile.yaml
```
Configure your personal information, skills, job preferences, and Phase 2 external portal credentials in `profiles/my_profile.yaml`.

Set your active profile in `.env`:
```env
PROFILE=my_profile
GEMINI_API_KEY=your_gemini_api_key
JOB_TIMEOUT_SECONDS=240
```

---

## 🖥️ Usage

### Running the Multi-Platform Job Application Agent
Run the main runner to automatically search and apply for jobs on your desired platform:

```bash
# Run on LinkedIn (Phase 1 Easy Apply & Phase 2 ATS Portals)
python main.py --linkedin

# Run on Naukri
python main.py --naukri

# Additional options
python main.py --linkedin --profile my_profile --max-apps 20 --headless
```

### Connecting the Universal Recruiter MCP Server to Your AI IDE

Once you have completed the one-time authentication (`python auth.py`), you can connect `mcp.py` to any AI coding assistant or IDE supporting the Model Context Protocol (**Cursor**, **Claude Desktop**, **Antigravity**, **Codex**, or **Windsurf**). The single `mcp.py` server manages recruiter discovery, candidate messaging, and job intelligence across all supported platforms (LinkedIn, Naukri, and external portals).

#### Step 1: Note your repository path
In your terminal, navigate to the cloned `job-hunter` directory and run:
```bash
pwd
# Example output: /Users/<your-username>/projects/job-hunter
```
Note the path to your repository and virtual environment Python interpreter:
- **macOS / Linux:** `<path-to-job-hunter>/venv/bin/python`
- **Windows:** `<path-to-job-hunter>\venv\Scripts\python.exe`

---

#### Step 2: Add Configuration to Your IDE

##### 🔹 Cursor
1. Go to **Cursor Settings** > **Features** > **MCP Servers** > click **Add New MCP Server**.
2. Or directly edit/create `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "recruiter-hunter": {
      "command": "<path-to-job-hunter>/venv/bin/python",
      "args": [
        "<path-to-job-hunter>/mcp.py"
      ],
      "env": {
        "PYTHONPATH": "<path-to-job-hunter>"
      }
    }
  }
}
```

##### 🔹 Google Antigravity
Add the server configuration to your global config (`~/.gemini/config/mcp_config.json`) or workspace root (`.agents/mcp_config.json`):
```json
{
  "mcpServers": {
    "recruiter-hunter": {
      "command": "<path-to-job-hunter>/venv/bin/python",
      "args": [
        "<path-to-job-hunter>/mcp.py"
      ],
      "env": {
        "PYTHONPATH": "<path-to-job-hunter>"
      }
    }
  }
}
```

##### 🔹 Claude Desktop
Open your Claude Desktop configuration file:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add the server under `mcpServers`:
```json
{
  "mcpServers": {
    "recruiter-hunter": {
      "command": "<path-to-job-hunter>/venv/bin/python",
      "args": [
        "<path-to-job-hunter>/mcp.py"
      ],
      "env": {
        "PYTHONPATH": "<path-to-job-hunter>"
      }
    }
  }
}
```

##### 🔹 Codex / Windsurf / VS Code (Roo Code / Cline)
In your MCP settings or plugin JSON configuration:
```json
{
  "mcpServers": {
    "recruiter-hunter": {
      "command": "<path-to-job-hunter>/venv/bin/python",
      "args": [
        "<path-to-job-hunter>/mcp.py"
      ],
      "env": {
        "PYTHONPATH": "<path-to-job-hunter>"
      }
    }
  }
}
```

*(Note: `linkedin_mcp.py` is also retained as a direct backward-compatible runner for existing setups).*

```

> **Tip:** Replace `<path-to-job-hunter>` with the absolute path returned by `pwd` on your machine.


---

## 🔒 100% Local & Secure (No Database, No Remote Backend)

- **100% Local Execution:** Everything runs entirely on your local machine.
- **No Remote Servers or Databases:** There is zero external telemetry, no remote backend, and no third-party database tracking or collecting your information.
- **Session Stored Exclusively on Your Machine:** Your LinkedIn authentication cookies are stored locally in `.auth/state.json`. They never leave your system and are strictly ignored by `.gitignore`.
- **Private & Safe by Design:** Feel completely free to leverage full agentic capabilities to search recruiters, tailor profiles, and apply for jobs knowing that your credentials, resumes, and personal data stay strictly under your control.

### Best Practices & Guardrails:
- **Resumes & PII:** Resume PDFs (`*.pdf`), custom profile YAMLs (`profiles/*.yaml`), and session states (`.auth/`) are ignored by Git.
- **Reference Profile:** Always use `profiles/dummy_profile.yaml` for testing and public templates.
- **Safety Approvals:** High-impact operations in the MCP server (`send_dm`, `connect_with_person`, `create_post`) strictly require user confirmation (`confirmed=True`).
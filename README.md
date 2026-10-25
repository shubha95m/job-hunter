# Job Hunter & LinkedIn MCP Agent

An intelligent, autonomous job application agent and enterprise LinkedIn MCP (Model Context Protocol) server powered by Playwright, Python, and LLM integrations.

---

## ⚡ Core Architecture: Hybrid Execution Engine

Job Hunter uses a **hybrid automation architecture** designed for both ultra-fast read operations and robust browser-level interactions:

```text
               AI Agent / MCP Client (Antigravity, Cursor, Claude)
                                      │
                                      ▼
                               linkedin_mcp.py
                                      │
         ┌────────────────────────────┴────────────────────────────┐
         ▼                                                         ▼
 [Fast Backend API Engine]                              [Headless Browser Engine]
  - Python httpx + Cookies                               - Playwright (Headless Chromium)
  - Targets LinkedIn Voyager REST API                    - Uses saved session storage state
  - No browser overhead (<300ms)                         - Handles complex DOM & UI events
  - Read queries: Profile, Experience, Skills,           - Interactive actions: Recruiter Search,
    Job Specs, Messages, CV Matching                       DMs, Connect Requests, Post Creation
```

### 1. Direct Voyager REST API (Backend Python + Session Cookies)
- Reads authenticated session cookies (`JSESSIONID` and `li_at`) from `.auth/state.json`.
- Makes direct HTTP requests via `httpx.Client` to LinkedIn's internal backend endpoints (`/voyager/api/...`).
- **Speed:** Responses return in **100–300ms** without launching a browser or consuming GPU/CPU rendering resources.
- **Used for:** Profile inspection, work experience, skill extraction, unread message checks, job details, and CV-to-job matching.

### 2. Headless Browser Automation (Playwright Chromium)
- Reuses the saved browser storage state (`.auth/state.json`) with pre-authenticated session state.
- Bypasses login prompts and CAPTCHAs silently in the background.
- **Used for:** Recruiter discovery, public people searches, connection requests, and message dispatch.

---

## 🚀 Job Application Pipeline

The automation workflow is split into two specialized phases:

### Phase 1: LinkedIn Easy Apply Agent (`agent.py`)
- Navigates through LinkedIn search results and identifies jobs matching profile keywords.
- Detects the **Easy Apply** modal.
- Autonomously fills standard multi-step forms (experience years, radio buttons, dropdowns, resume attachment, disclosures).
- Uses token-tracked LLM assistance for custom/unfamiliar screening questions.

### Phase 2: External Company Portal Agent (`external_portal_agent.py`)
- Detects jobs requiring direct application on external company ATS portals (e.g., **Workday**, **Greenhouse**, **Lever**, **Taleo**, **iCIMS**, **Ashby**).
- Captures new browser tabs when clicking external apply links.
- **Automated Portal Features:**
  - **Account Creation / Login:** Detects authentication requirements and creates candidate portal accounts using configured credentials.
  - **Resume Upload & Constraints:** Handles file upload triggers and automatically switches to optimized files if size limits (e.g., Workday 1MB) are detected.
  - **Enterprise Field Pre-population:** Populates multi-section forms (Contact Details, Address, Work Authorization, EEO Demographics, Education & Employment History).
  - **Multi-Step Progression:** Navigates multi-page Workday/ATS wizards with spinner synchronization and step-by-step progress tracking.

---

## 🛠️ LinkedIn MCP Server Tools Overview

The included Model Context Protocol server (`linkedin_mcp.py`) exposes 25+ tools to AI coding environments (e.g., Antigravity, Cursor, Claude Code):

| Tool Name | Engine | Description |
|---|---|---|
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

> **Safety Guard:** Any mutating or communication action (`send_dm`, `connect_with_person`, `create_post`, `update_*`) strictly requires `confirmed=True` to prevent accidental actions.

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
Run the interactive login script:
```bash
python auth.py
```
A visual browser window will open. Log into your LinkedIn account. Once logged in, close the browser window. Your authenticated session state and cookies will be stored locally in `.auth/state.json`.

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

### Running the Job Application Agent
Run the main runner to automatically search and apply for jobs:
```bash
python main.py
```

### Connecting the LinkedIn MCP Server to Your AI IDE

Once you have completed the one-time authentication (`python auth.py`), you can connect `linkedin_mcp.py` to any AI coding assistant or IDE supporting the Model Context Protocol (**Cursor**, **Claude Desktop**, **Antigravity**, **Codex**, or **Windsurf**).

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
    "linkedin": {
      "command": "<path-to-job-hunter>/venv/bin/python",
      "args": [
        "<path-to-job-hunter>/linkedin_mcp.py"
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
    "linkedin": {
      "command": "<path-to-job-hunter>/venv/bin/python",
      "args": [
        "<path-to-job-hunter>/linkedin_mcp.py"
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

Add the `linkedin` server under `mcpServers`:
```json
{
  "mcpServers": {
    "linkedin": {
      "command": "<path-to-job-hunter>/venv/bin/python",
      "args": [
        "<path-to-job-hunter>/linkedin_mcp.py"
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
    "linkedin": {
      "command": "<path-to-job-hunter>/venv/bin/python",
      "args": [
        "<path-to-job-hunter>/linkedin_mcp.py"
      ],
      "env": {
        "PYTHONPATH": "<path-to-job-hunter>"
      }
    }
  }
}
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
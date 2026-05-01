# Job Hunter Agent

An automated job application agent that uses Playwright and Python to apply for jobs on LinkedIn.

## Prerequisites
- Python 3.9+
- Chrome/Chromium browser

## Setup

1. **Install dependencies**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Configure your profile**:
   Copy the template and fill in your details:
   ```bash
   cp profile_template.yaml profile.yaml
   ```
   Open `profile.yaml` and add your real information, skills, and preferences.

3. **Authenticate with LinkedIn**:
   Run the authentication script to perform a one-time manual login. This saves your session securely so the bot can run headlessly later.
   ```bash
   python auth.py
   ```
   *A browser window will open. Log into your LinkedIn account. Once logged in, simply close the browser window.*

## Usage

Run the main agent script to start searching and applying for Easy Apply jobs based on your profile:
```bash
python main.py
```
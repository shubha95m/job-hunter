import os
import json
from dotenv import load_dotenv

load_dotenv()

async def generate_action(prompt: str) -> dict:
    """
    Wrapper to call the appropriate LLM based on the AI environment variable.
    Returns the parsed JSON dictionary.
    """
    ai_provider = os.getenv("AI", "gemini").lower()
    
    if ai_provider == "claude":
        return await _call_claude(prompt)
    else:
        return await _call_gemini(prompt)

async def _call_claude(prompt: str) -> dict:
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY not found in .env")
        return None
        
    client = anthropic.AsyncAnthropic(api_key=api_key)
    model_name = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
    
    try:
        response = await client.messages.create(
            model=model_name,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        return _parse_json_response(response.content[0].text.strip())
    except Exception as e:
        print(f"Claude Error: {e}")
        return None

async def _call_gemini(prompt: str) -> dict:
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("WARNING: GEMINI_API_KEY not found in .env")
        return None
        
    client = genai.Client(api_key=api_key)
    # Defaulting to 2.5-flash as 3.0 caused a 404 earlier
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    try:
        # Use aio for async generation so we don't block the Playwright event loop
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        return _parse_json_response(response.text.strip())
    except Exception as e:
        print(f"Gemini Error: {e}")
        return None

def _parse_json_response(text: str) -> dict:
    # Clean up markdown if the model included it
    if text.startswith("```json"):
        text = text.split("```json")[1].split("```")[0].strip()
    elif text.startswith("```"):
        text = text.split("```")[1].split("```")[0].strip()
        
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"JSON Parsing Error: {e}\\nRaw Text: {text}")
        return None

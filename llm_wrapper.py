import asyncio
import json
import os
import re
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()


# ==============================================================================
# Model Pricing (USD per 1,000,000 tokens: input, output)
# ==============================================================================
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic / Cursor Claude
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-7-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-opus": (15.00, 75.00),
    # Google Gemini
    "gemini-3.8-flash": (0.075, 0.30),
    "gemini-3.5-flash": (0.075, 0.30),
    "gemini-flash": (0.075, 0.30),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-2.5-pro": (1.25, 5.00),
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o1": (15.00, 60.00),
    "o3-mini": (1.10, 4.40),
}


class TokenCostTracker:
    def __init__(self):
        self.call_count = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0

    def calculate_cost(self, model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        model_lower = model_name.lower()
        rates = (3.00, 15.00)  # default to Sonnet pricing
        for key, r in MODEL_PRICING.items():
            if key in model_lower:
                rates = r
                break
        in_cost = (prompt_tokens / 1_000_000.0) * rates[0]
        out_cost = (completion_tokens / 1_000_000.0) * rates[1]
        return in_cost + out_cost

    def record_call(
        self, provider: str, model_name: str, prompt_tokens: int, completion_tokens: int
    ) -> dict[str, Any]:
        self.call_count += 1
        total_tokens = prompt_tokens + completion_tokens
        call_cost = self.calculate_cost(model_name, prompt_tokens, completion_tokens)

        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        self.total_cost_usd += call_cost

        print(
            f"\n  [AI Cost & Tokens] Action Call #{self.call_count} | {provider.upper()} ({model_name})\n"
            f"    Prompt Tokens: {prompt_tokens:,} | Completion: {completion_tokens:,} | Total: {total_tokens:,}\n"
            f"    Cost this action: ${call_cost:.5f} | Cumulative Session Cost: ${self.total_cost_usd:.5f}"
        )
        return {
            "call_number": self.call_count,
            "provider": provider,
            "model": model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost": call_cost,
            "cumulative_cost": self.total_cost_usd,
        }

    def print_summary(self) -> None:
        print("\n=======================================================")
        print("             AI SESSION TOKEN & COST SUMMARY")
        print("=======================================================")
        print(f"  Total AI Calls:             {self.call_count}")
        print(f"  Prompt (Input) Tokens:      {self.total_prompt_tokens:,}")
        print(f"  Completion (Output) Tokens: {self.total_completion_tokens:,}")
        print(f"  Total Tokens Used:          {self.total_tokens:,}")
        print(f"  Total Estimated Cost:       ${self.total_cost_usd:.5f} USD")
        print("=======================================================\n")


token_tracker = TokenCostTracker()


async def generate_action(prompt: str) -> Optional[list[dict[str, Any]]]:
    """
    Calls the configured LLM and returns parsed JSON actions.
    The form agent is DOM-first, so this wrapper is text-only by design.
    """
    raw_provider = os.getenv("AI", "gemini").lower()
    ai_provider = re.sub(r'[^a-z]', '', raw_provider)

    if ai_provider in ("cursor", "openai", "openrouter"):
        result = await _call_cursor(prompt)
        if result is None:
            print("  Falling back to Gemini...")
            result = await _call_gemini(prompt)
            if result is None:
                claude_key = os.getenv("ANTHROPIC_API_KEY", "")
                if claude_key and not claude_key.startswith("your_"):
                    print("  Falling back to Claude...")
                    result = await _call_claude(prompt)
    elif ai_provider == "claude":
        result = await _call_claude(prompt)
        if result is None:
            print("  Falling back to Gemini...")
            result = await _call_gemini(prompt)
    else:
        result = await _call_gemini(prompt)
        if result is None:
            cursor_key = os.getenv("CURSOR_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
            if cursor_key and not cursor_key.startswith("your_"):
                print("  Falling back to Cursor/OpenAI...")
                result = await _call_cursor(prompt)
            if result is None:
                claude_key = os.getenv("ANTHROPIC_API_KEY", "")
                if claude_key and not claude_key.startswith("your_"):
                    print("  Falling back to Claude...")
                    result = await _call_claude(prompt)

    return result


async def _call_cursor(prompt: str) -> Optional[list[dict[str, Any]]]:
    import httpx

    api_key = os.getenv("CURSOR_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key or api_key.startswith("your_"):
        print("WARNING: CURSOR_API_KEY not found in .env")
        return None

    base_url = os.getenv("CURSOR_BASE_URL", "https://api.cursor.com").rstrip("/")
    model_name = os.getenv("CURSOR_MODEL", "claude-sonnet-4-6")

    # If it's a native Cursor API key (starts with crsr_) or target is api.cursor.com,
    # use the official Cursor Cloud Agent API
    if api_key.startswith("crsr_") or "api.cursor.com" in base_url:
        return await _call_cursor_cloud_agent(prompt, api_key, model_name, "https://api.cursor.com")

    # Otherwise standard OpenAI-compatible / OpenRouter endpoint
    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(3):
            try:
                resp = await client.post(endpoint, json=payload, headers=headers)
                if resp.status_code == 401:
                    print("Cursor/OpenAI Error: Authentication failed (invalid CURSOR_API_KEY)")
                    return None
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]

                usage = data.get("usage", {})
                p_tokens = usage.get("prompt_tokens") or max(1, len(prompt) // 4)
                c_tokens = usage.get("completion_tokens") or max(1, len(content) // 4)
                token_tracker.record_call(provider="Cursor / OpenAI", model_name=model_name, prompt_tokens=p_tokens, completion_tokens=c_tokens)

                return _parse_json_response(content.strip())
            except Exception as exc:
                err_str = str(exc)
                if "authentication_error" in err_str.lower() or "401" in err_str:
                    print("Cursor/OpenAI Error: Authentication failed (invalid CURSOR_API_KEY)")
                    return None
                if _is_transient_error(exc) and attempt < 2:
                    wait_secs = _retry_delay_seconds(exc, default=3 * (attempt + 1))
                    print(f"  Cursor/OpenAI rate limited/busy. Waiting {wait_secs}s...")
                    await asyncio.sleep(wait_secs)
                    continue
                print(f"Cursor/OpenAI Error: {exc}")
                return None

    return None


async def _call_cursor_cloud_agent(
    prompt: str, api_key: str, model_name: str, base_url: str = "https://api.cursor.com"
) -> Optional[list[dict[str, Any]]]:
    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": {"id": model_name},
        "prompt": {"text": prompt},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{base_url}/v1/agents", json=payload, headers=headers)
            if resp.status_code == 401:
                print("Cursor Cloud Agent Error: Authentication failed (invalid CURSOR_API_KEY)")
                return None
            if resp.status_code != 201:
                print(f"Cursor Cloud Agent Error: {resp.status_code} - {resp.text}")
                return None

            data = resp.json()
            agent_id = data.get("agent", {}).get("id")
            run_id = data.get("run", {}).get("id")
            if not agent_id or not run_id:
                print("Cursor Cloud Agent Error: Missing agent or run ID in response")
                return None

            result_text = None
            for _ in range(25):  # poll up to ~37s
                await asyncio.sleep(1.5)
                r_run = await client.get(f"{base_url}/v1/agents/{agent_id}/runs/{run_id}", headers=headers)
                if r_run.status_code == 200:
                    run_data = r_run.json()
                    status = run_data.get("status")
                    if status in ("FINISHED", "COMPLETED"):
                        result_text = run_data.get("result", "")
                        usage = run_data.get("usage") or {}
                        p_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or max(1, len(prompt) // 4)
                        c_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or max(1, len(result_text) // 4)
                        token_tracker.record_call(
                            provider="Cursor Cloud Agent",
                            model_name=model_name,
                            prompt_tokens=p_tokens,
                            completion_tokens=c_tokens,
                        )
                        break
                    elif status in ("FAILED", "CANCELLED"):
                        print(f"Cursor Cloud Agent Run {status}: {run_data.get('error') or run_data}")
                        break

            # Best-effort async cleanup of temporary agent
            try:
                await client.delete(f"{base_url}/v1/agents/{agent_id}", headers=headers)
            except Exception:
                pass

            if result_text:
                return _parse_json_response(result_text.strip())
            else:
                print("Cursor Cloud Agent Error: Did not receive finished result within timeout")
                return None

        except Exception as exc:
            print(f"Cursor Cloud Agent Error: {exc}")
            return None


async def _call_claude(prompt: str) -> Optional[list[dict[str, Any]]]:
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY not found in .env")
        return None

    client = anthropic.AsyncAnthropic(api_key=api_key)
    model_name = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest")

    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=model_name,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            content_text = response.content[0].text.strip()
            p_tokens = getattr(response.usage, "input_tokens", None) or max(1, len(prompt) // 4)
            c_tokens = getattr(response.usage, "output_tokens", None) or max(1, len(content_text) // 4)
            token_tracker.record_call(provider="Anthropic Claude", model_name=model_name, prompt_tokens=p_tokens, completion_tokens=c_tokens)

            return _parse_json_response(content_text)
        except Exception as exc:
            err_str = str(exc)
            if "authentication_error" in err_str or "invalid x-api-key" in err_str or "401" in err_str:
                print(f"Claude Error: Authentication failed (invalid ANTHROPIC_API_KEY)")
                return None
            if _is_transient_error(exc) and attempt < 2:
                wait_secs = _retry_delay_seconds(exc, default=5 * (attempt + 1))
                print(f"  Claude rate limited/busy. Waiting {wait_secs}s...")
                await asyncio.sleep(wait_secs)
                continue
            print(f"Claude Error: {exc}")
            return None

    return None


async def _call_gemini(prompt: str) -> Optional[list[dict[str, Any]]]:
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("WARNING: GEMINI_API_KEY not found in .env")
        return None

    client = genai.Client(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    # Modern fallback models with separate quotas
    candidate_models = [model_name]
    for alt in ["gemini-3.8-flash", "gemini-flash-latest", "gemini-3.5-flash"]:
        if alt not in candidate_models:
            candidate_models.append(alt)

    for current_model in candidate_models:
        for attempt in range(3):
            try:
                response = await client.aio.models.generate_content(
                    model=current_model,
                    contents=prompt,
                )
                text = response.text.strip()
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    p_tokens = getattr(usage, "prompt_token_count", None) or max(1, len(prompt) // 4)
                    c_tokens = getattr(usage, "candidates_token_count", None) or max(1, len(text) // 4)
                else:
                    p_tokens = max(1, len(prompt) // 4)
                    c_tokens = max(1, len(text) // 4)

                token_tracker.record_call(provider="Google Gemini", model_name=current_model, prompt_tokens=p_tokens, completion_tokens=c_tokens)

                return _parse_json_response(text)
            except Exception as exc:
                err_str = str(exc).lower()
                is_daily_quota = (
                    "generaterequestsperday" in err_str
                    or "requests_per_day" in err_str
                )
                wait_secs = _retry_delay_seconds(exc, default=3 * (attempt + 1))
                if is_daily_quota or wait_secs < 0:
                    print(f"  Gemini ({current_model}) daily quota exhausted. Switching model immediately...")
                    break

                if _is_transient_error(exc) and attempt < 2:
                    print(f"  Gemini ({current_model}) transient error. Retrying in {wait_secs}s...")
                    await asyncio.sleep(wait_secs)
                    continue
                print(f"Gemini ({current_model}) Error: {exc}")
                break

    return None


def _is_transient_error(exc: Exception) -> bool:
    error = str(exc).lower()
    return any(
        term in error
        for term in [
            "429",
            "rate",
            "resource_exhausted",
            "quota",
            "too many requests",
            "overloaded",
            "503",
            "service unavailable",
            "timeout",
        ]
    )


def _retry_delay_seconds(exc: Exception, default: int = 5) -> int:
    err_str = str(exc)
    match = re.search(r"retry[- ]after[:\s]+(\d+)", err_str, re.IGNORECASE)
    if match:
        return min(int(match.group(1)), 30)
    match_s = re.search(r"wait\s+(\d+(?:\.\d+)?)\s*s", err_str, re.IGNORECASE)
    if match_s:
        return min(int(float(match_s.group(1))), 30)
    return default


def _parse_json_response(raw: str) -> Optional[list[dict[str, Any]]]:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return None

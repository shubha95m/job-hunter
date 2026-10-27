"""
Autonomous Web-Grounded Interview & Company Intelligence Engine.
Performs real-time web searches across Glassdoor, LeetCode, GeeksforGeeks,
and tech forums using Google Search Grounding to retrieve verified, real-world
interview debriefs, coding questions, and system design scenarios.
Blends search findings with the candidate profile, seniority, and location.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def research_company_interview_intelligence(
    company_name: str,
    role_title: str,
    location: str = "Pune",
    yoe: float = 8.0,
    candidate_skills: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Performs real-time web search for company-specific interview debriefs,
    then combines with candidate profile for a tailored hybrid output.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("No GEMINI_API_KEY found, falling back to local domain intelligence.")
        return {"status": "FALLBACK", "source": "local_battery", "raw_search_insights": ""}

    candidate_skills = candidate_skills or ["Java", "Spring Boot", "Microservices", "Kafka", "Redis"]
    clean_company = company_name.split("(")[0].strip()
    clean_role = role_title.split("(")[0].strip()

    prompt = f"""
You are an elite Principal Technical Recruiter and Staff Software Architect.
Perform a deep real-time web search for recent (2024-2026) interview experiences, LeetCode discuss threads, and Glassdoor interview questions for:
- Company: {company_name} (Search term: {clean_company})
- Target Role: {role_title} ({clean_role})
- Location: {location}
- Candidate Experience Level: {yoe} Years of Experience (Senior / Lead Staff Level)
- Core Stack: {', '.join(candidate_skills[:6])}

Search Glassdoor, LeetCode, GeeksforGeeks, and Reddit to find REAL interview debriefs:
1. What are the specific technical rounds (Online Assessment, Technical Rounds 1 & 2, System Design, Director Round)?
2. What specific coding problems / LeetCode patterns are frequently asked (e.g., LRU cache, sliding window, concurrency primitives)?
3. What real system design / production outage scenarios do their engineering managers probe (e.g., payment idempotency, connection pool exhaustion, Saga distributed transactions)?
4. What core language & framework internals are heavily tested (e.g., JVM memory & GC, HashMap/ConcurrentHashMap internals, Spring @Transactional proxy bypass, Hibernate N+1)?
5. What behavioral / managerial culture themes do their directors emphasize?

Return your findings as structured JSON with the following format:
{{
  "verified_rounds": [
    {{"round": "Round Name", "focus": "Round description and duration"}}
  ],
  "real_coding_patterns_reported": [
    {{"title": "Pattern/Problem Title", "description": "Details of the problem as reported by candidates", "difficulty": "Medium/Hard"}}
  ],
  "real_system_design_scenarios": [
    {{"scenario": "Scenario Title", "probe": "Exact question or architecture prompt used in the interview"}}
  ],
  "real_conceptual_focus_areas": [
    {{"area": "Technology Area", "key_questions": ["Question 1", "Question 2"]}}
  ],
  "location_specific_insights": "Specific context about {company_name}'s {location} engineering hub or project mandate",
  "summary_raw": "Concise summary of candidate experiences and overall difficulty rating"
}}

Respond ONLY with valid JSON.
"""

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.2,
            )
        )

        text = response.text.strip()
        # Clean markdown codeblocks if present
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        data = json.loads(text)
        data["status"] = "SUCCESS"
        data["source"] = "google_search_grounded"
        data["target_company"] = company_name
        data["role_title"] = role_title
        data["location"] = location
        return data

    except Exception as e:
        logger.error(f"Web research failed: {e}")
        return {
            "status": "FALLBACK",
            "source": "local_battery",
            "error": str(e),
            "target_company": company_name,
            "role_title": role_title,
            "location": location
        }

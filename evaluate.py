#!/usr/bin/env python3
"""
evaluate.py — Job Description (JD) Evaluator for Resume Builder.

Runs a two-step evaluation on any JD before resume tailoring:
  Step A: Fast local rule check (zero API calls, instant).
  Step B: AI-powered deep analysis (Groq API with multi-key smart shifting).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

# Reconfigure stdout/stderr to UTF-8 for cross-platform and Windows terminal support
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Candidate Profile
# --------------------------------------------------------------------------

CANDIDATE = {
    "name": "Chinmay Maheshwari",
    "location": "Udaipur, India",
    "status": "Final-year B.Tech IT student",
    "graduation": "May/June 2027",
    "experience_years": 0,  # fresh grad
    "internship": "1 month (May-June 2026, completed)",
    "work_authorization": ["India"],  # can only work in India or remote worldwide

    "core_stack": [
        "Java", "Spring Boot", "Node.js", "Express.js",
        "React.js", "MongoDB", "MySQL", "REST APIs",
        "JWT", "Kafka", "Docker", "GitHub Actions",
        "JUnit", "Postman", "Git", "Gemini API"
    ],

    "ai_tools": [
        "Claude", "ChatGPT", "GitHub Copilot",
        "Gemini Flash API", "Claude Code"
    ],

    "hard_blockers": {
        # If JD requires these languages as PRIMARY stack — skip
        "wrong_languages": [
            "C#", ".NET", "Elixir", "Rust", "Go", "Golang",
            "Swift", "Kotlin", "Ruby", "Erlang", "Scala",
            "TypeScript"  # warn only, not hard block
        ],

        # If JD requires work auth in these countries — skip
        "wrong_locations": [
            "UK", "United Kingdom", "Northern Ireland",
            "Australia", "Canada", "Europe", "EU",
            "United States", "US only"
        ],

        # If JD mentions these — skip (wrong domain)
        "wrong_domains": [
            "Oracle ERP", "SAP modules", "Salesforce admin",
            "Embedded systems", "Hardware", "FPGA",
            "Formal verification", "Chip design", "VLSI",
            "Compliance analyst", "Customer success manager",
            "Data Scientist", "ML Engineer", "AI Researcher",
            "DevOps only", "SRE only", "Network Engineer",
            "Mobile iOS", "Mobile Android", "Swift", "Flutter"
        ],

        # Full-time experience required (excluding internships)
        "max_experience_years": 2,

        # If salary/role is clearly senior
        "senior_signals": [
            "mentor junior engineers", "set technical direction",
            "lead the team", "5+ years", "7+ years", "8+ years",
            "staff engineer", "principal engineer", "engineering manager"
        ]
    },

    "green_flags": [
        "fresher", "fresh graduate", "new grad", "0 years",
        "0-1 years", "entry level", "associate", "intern",
        "recent graduate", "2026 batch", "2027 batch",
        "India", "remote worldwide", "work from anywhere",
        "visa sponsorship", "Java", "Spring Boot", "React",
        "Node.js", "full stack", "MERN", "AI tools",
        "LLM", "Gemini", "GitHub Copilot", "Claude"
    ]
}


# --------------------------------------------------------------------------
# Environment & Groq API Key Discovery
# --------------------------------------------------------------------------

def _load_dotenv_if_present():
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.expanduser("~/.resume_tailor/.env"),
    ]
    for env_path in candidates:
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key and key not in os.environ:
                            os.environ[key] = val
            except Exception:
                pass


def get_groq_api_keys() -> list[str]:
    """
    Collects all unique Groq API keys configured across .env and environment variables.
    Supports GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEYS, etc.
    """
    _load_dotenv_if_present()
    keys: list[str] = []
    for k, v in os.environ.items():
        if k == "GROQ_API_KEY" or k.startswith("GROQ_API_KEY_") or k == "GROQ_API_KEYS":
            for part in v.replace(";", ",").split(","):
                clean = part.strip().strip("'\"")
                if clean and clean not in keys:
                    keys.append(clean)
    return keys


# --------------------------------------------------------------------------
# Step A: Local Rule Check (Zero API Calls)
# --------------------------------------------------------------------------

def local_evaluate(jd_text: str) -> dict:
    """
    Fast local check — no API call needed.
    Returns a dict with:
      - hard_blocks: list of reasons to skip
      - warnings: list of concerns
      - green_flags_found: list of positive signals
      - local_verdict: "SKIP" / "APPLY" / "BORDERLINE"
    """
    jd_lower = jd_text.lower()
    hard_blocks: list[str] = []
    warnings: list[str] = []
    green_flags_found: list[str] = []

    # Check work authorization
    location_blocks = [
        ("right to work in uk", "Requires UK work authorization"),
        ("eligibility to work in the uk", "Requires UK work authorization"),
        ("eligible to work in australia", "Requires Australian work authorization"),
        ("must be based in the us", "US-only role"),
        ("us citizens only", "US citizens only"),
        ("within ni", "Northern Ireland only"),
        ("within northern ireland", "Northern Ireland only"),
        ("eu work permit", "Requires EU work permit"),
    ]
    for phrase, reason in location_blocks:
        if phrase in jd_lower:
            hard_blocks.append(f"❌ LOCATION: {reason}")

    # Check wrong primary language
    language_blocks = [
        ("c# developer", "Primary language is C#"),
        ("dotnet developer", "Primary language is .NET"),
        (".net developer", "Primary language is .NET"),
        ("elixir developer", "Primary language is Elixir"),
        ("rust developer", "Primary language is Rust"),
        ("golang developer", "Primary language is Go"),
        ("flutter developer", "Primary language is Flutter"),
        ("swift developer", "Primary language is Swift"),
        ("ios developer", "iOS development role"),
        ("android developer", "Android development role"),
    ]
    for phrase, reason in language_blocks:
        if phrase in jd_lower:
            hard_blocks.append(f"❌ STACK: {reason} — not in your toolkit")

    # Check wrong domain
    domain_blocks = [
        ("formal verification", "Hardware/chip verification role"),
        ("verilog", "Hardware description language role"),
        ("fpga", "Hardware engineering role"),
        ("oracle fusion", "Oracle ERP specialist role"),
        ("sap module", "SAP specialist role"),
        ("compliance analyst", "Compliance/risk role — not engineering"),
        ("customer success manager", "Non-technical role"),
        ("data scientist", "Data Science role — different career track"),
        ("machine learning engineer", "ML Engineering — requires Python/PyTorch"),
    ]
    for phrase, reason in domain_blocks:
        if phrase in jd_lower:
            hard_blocks.append(f"❌ DOMAIN: {reason}")

    # Check experience floor
    exp_patterns = [
        r"(\d+)\+?\s*years?\s*of\s*(?:full.time\s*)?(?:professional\s*)?experience",
        r"minimum\s*(\d+)\s*years?",
        r"at\s*least\s*(\d+)\s*years?",
    ]
    for pattern in exp_patterns:
        matches = re.findall(pattern, jd_lower)
        for match in matches:
            years = int(match)
            if years > 2:
                msg = f"❌ EXPERIENCE: Requires {years}+ years — you have 0 full-time years"
                if msg not in hard_blocks:
                    hard_blocks.append(msg)

    # Check senior signals
    senior_phrases = [
        ("mentor junior engineers", "Role requires mentoring junior engineers"),
        ("set technical direction", "Role requires setting technical direction"),
        ("lead the team", "Leadership role"),
        ("principal engineer", "Principal/Staff level role"),
        ("staff engineer", "Staff level role"),
        ("engineering manager", "Engineering Manager role"),
    ]
    for phrase, reason in senior_phrases:
        if phrase in jd_lower:
            msg = f"❌ SENIORITY: {reason} — too senior for fresh grad"
            if msg not in hard_blocks:
                hard_blocks.append(msg)

    # TypeScript warning (not hard block)
    if "typescript" in jd_lower and "javascript" not in jd_lower:
        warnings.append("⚠️  TypeScript-only role — you know JS but not TS specifically")

    # NestJS warning
    if "nest.js" in jd_lower or "nestjs" in jd_lower:
        warnings.append("⚠️  NestJS required — you haven't used it (Node.js is similar)")

    # Python warning
    if "python" in jd_lower and "java" not in jd_lower:
        warnings.append("⚠️  Python-primary role — you know Python basics only")

    # Check green flags
    for flag in CANDIDATE["green_flags"]:
        if flag.lower() in jd_lower:
            flag_entry = f"✅ {flag}"
            if flag_entry not in green_flags_found:
                green_flags_found.append(flag_entry)

    # Verdict
    if hard_blocks:
        verdict = "SKIP"
    elif len(warnings) > 2:
        verdict = "BORDERLINE"
    else:
        verdict = "APPLY"

    return {
        "hard_blocks": hard_blocks,
        "warnings": warnings,
        "green_flags_found": green_flags_found,
        "local_verdict": verdict,
    }


# --------------------------------------------------------------------------
# Step B: AI-Powered Deep Analysis (Groq API with Smart Shifting)
# --------------------------------------------------------------------------

EVALUATOR_PROMPT = """
You are a strategic job application advisor for a specific software engineering candidate.

CANDIDATE PROFILE:
- Education: Final-year B.Tech IT student in India, graduating May/June 2027
- Experience: 1 month internship (completed June 2026) — targeting internships, entry-level, fresher, or 0-2 yrs roles
- Core stack: Java, Spring Boot, React.js, Node.js, Express.js, MongoDB, MySQL, Kafka, JWT, Docker, GitHub Actions, JUnit, REST APIs, Git, Postman
- AI & Tooling: Modern Agentic AI coding harnesses, Claude, ChatGPT, GitHub Copilot, Gemini Flash API
- Location / Auth: Can only work in India or remote worldwide (NO UK/AU/US on-site work authorization)
- Minor/Basic: Python (basics), C/C++ (academic basics), DSA foundation
- NOT experienced in: C#, .NET, Elixir, Rust, Go, native iOS/Android, hardware/FPGA, ML research

CRITICAL EVALUATION RULES:
1. DISTINGUISH MANDATORY VS BONUS/OPTIONAL QUALIFICATIONS:
   - Skills explicitly listed under "Bonus", "Good to have", "Nice to have", "Preferred", "Plus", or "Optional" are NOT required qualifications.
   - NEVER classify missing bonus/preferred skills as critical gaps or blockers. Missing a bonus skill must NOT drop the verdict from APPLY to BORDERLINE, nor drop the score below 80 if core requirements are met.
   - If candidate matches ANY bonus skill (e.g., Java, RESTful API), award positive bonus points!

2. HANDLE "OR" / ALTERNATIVE REQUIREMENTS CORRECTLY:
   - When a requirement offers options (e.g., "proficiency in C++/C#/Java or PHP" or "React or Angular"), if the candidate matches ANY of the options (e.g., Java), this requirement is 100% SATISFIED!
   - Add the matched language/tech to "matched_skills".
   - CRITICAL: Do NOT list any of the other alternative options (such as C++, C#, PHP) in "missing_skills". Only true non-negotiable mandatory skills that the candidate completely lacks should appear in "missing_skills".
   - Bonus/optional items (e.g. 3D Mathematics) are optional preferences, not missing core requirements. Do not list them in "missing_skills" unless marked with "(Bonus)".

3. INTERN & FRESHER EXPECTATIONS:
   - For Intern, Trainee, or Entry-Level roles: core competencies are DSA, solid programming fundamentals, problem-solving, curiosity, and adaptability. Specialized niche domain experience (like 3D math, game engines, or prior commercial game shipping) when listed as bonus should be treated as an optional plus, NOT a penalty.
   - If the candidate meets location, experience level, and core programming/AI tooling, the verdict should be APPLY.

4. SCORING SCALE:
   - APPLY (75 - 100): Fits location, experience level (intern/fresher/0-2y), and matches primary or alternative language/stack (e.g. Java, Web, AI tools, DSA). High match on core requirements.
   - BORDERLINE (50 - 74): Fits location/experience, but requires a primary language the candidate does not know as a hard requirement (not bonus), or requires 2-3 years full-time experience.
   - SKIP (0 - 49): Requires foreign work visa (US/UK/EU only), requires senior experience (3+ years, team lead), or primary non-negotiable tech stack is completely outside their domain (e.g. Senior C# .NET, Rust, SAP ERP, Embedded FPGA).

EVALUATION TASK:
Analyze this job description and return a JSON response with exactly this structure:
{
  "verdict": "APPLY" or "BORDERLINE" or "SKIP",
  "score": 0-100,
  "company": "company name or Unknown",
  "role": "role title",
  "location_ok": true/false,
  "experience_ok": true/false,
  "stack_match_pct": 0-100,
  "matched_skills": ["skills candidate possesses that match core requirements or bonus list"],
  "missing_skills": ["strictly MANDATORY core skills that candidate lacks. DO NOT include bonus/nice-to-have items or satisfied OR alternatives here"],
  "hard_blocks": ["non-negotiable blockers like US/UK only work auth or 3+ yrs full-time requirement"],
  "warnings": ["noteworthy caveats or desirable domain knowledge to brush up on"],
  "green_flags": ["matching positive signals like intern level, India location, Java, AI harnesses"],
  "resume_version": "java_backend" or "full_stack" or "ai_llm" or "general",
  "one_line_reason": "One sentence explaining the verdict",
  "apply_action": "What to do next in one sentence"
}

Return ONLY the JSON. No explanation. No markdown.
"""

_DEFAULT_EVAL_MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b"]


def _clean_eval_result(parsed: dict) -> dict:
    """
    Cleans evaluation result to ensure OR language options and bonus skills
    are not mistakenly flagged as missing blockers.
    """
    matched = [s.strip() for s in parsed.get("matched_skills", [])]
    missing = [s.strip() for s in parsed.get("missing_skills", [])]
    matched_lower = {s.lower() for s in matched} | {s.lower() for s in CANDIDATE.get("core_stack", [])}

    # OR language alternatives: if any alternative is met, remove unselected options
    or_groups = [
        {"java", "c++", "c#", "php"},
        {"react", "angular", "vue"},
        {"postgresql", "mysql", "mongodb"},
    ]
    cleaned_missing = []
    for m in missing:
        m_lower = m.lower()
        suppressed = False
        for group in or_groups:
            if m_lower in group and any(g in matched_lower for g in group if g != m_lower):
                suppressed = True
                break
        if not suppressed:
            cleaned_missing.append(m)

    parsed["missing_skills"] = cleaned_missing

    # Ensure consistency between score and verdict
    score = parsed.get("score", 50)
    verdict = str(parsed.get("verdict", "BORDERLINE")).upper()
    hard_blocks = parsed.get("hard_blocks", [])

    if not hard_blocks:
        if score >= 75 and verdict == "BORDERLINE":
            parsed["verdict"] = "APPLY"
        elif verdict == "APPLY" and score < 75:
            parsed["score"] = 80

    return parsed


def ai_evaluate(
    jd_text: str,
    api_key: str | list[str] | None = None,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
) -> Optional[dict]:
    """
    Calls Groq API to perform deep JD fit analysis using smart key shifting and model fallbacks.
    Returns parsed dictionary matching the EVALUATOR_PROMPT schema, or None on failure.
    """
    if isinstance(api_key, list):
        keys_pool = [k for k in api_key if k]
    elif isinstance(api_key, str) and api_key.strip():
        keys_pool = [api_key.strip()]
    else:
        keys_pool = get_groq_api_keys()

    if not keys_pool:
        return None

    endpoint = api_base or os.environ.get("GROQ_BASE_URL") or "https://api.groq.com/openai/v1/chat/completions"
    if not endpoint.endswith("/chat/completions") and not endpoint.endswith("/"):
        endpoint = f"{endpoint}/chat/completions"

    primary_model = model or _DEFAULT_EVAL_MODELS[0]
    models_to_try = [primary_model] + [m for m in _DEFAULT_EVAL_MODELS if m != primary_model]

    user_content = f"JOB DESCRIPTION:\n{jd_text[:8000]}"

    for curr_model in models_to_try:
        model_failed = False
        for k_idx, curr_key in enumerate(keys_pool, 1):
            key_preview = f"...{curr_key[-6:]}" if len(curr_key) > 8 else curr_key
            payload = json.dumps({
                "model": curr_model,
                "messages": [
                    {"role": "system", "content": EVALUATOR_PROMPT.strip()},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.1,
                "max_tokens": 1500,
            }).encode("utf-8")

            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={
                    "Authorization": f"Bearer {curr_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                },
                method="POST",
            )

            for attempt in range(2):
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        resp_data = json.loads(resp.read().decode("utf-8"))
                        content = resp_data["choices"][0]["message"]["content"].strip()

                        # Strip markdown fences if present
                        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
                        content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE).strip()

                        # Match JSON object if surrounded by preamble/postscript
                        match = re.search(r"\{.*\}", content, re.DOTALL)
                        if match:
                            content = match.group(0)

                        parsed = json.loads(content)
                        if isinstance(parsed, dict) and "verdict" in parsed:
                            return _clean_eval_result(parsed)
                except urllib.error.HTTPError as e:
                    err_body = e.read().decode("utf-8", errors="ignore")
                    if e.code == 404 and "model_not_found" in err_body:
                        model_failed = True
                        break

                    # Smart shift immediately on 429/401/402/quota error
                    if e.code in (429, 401, 402) or "rate_limit" in err_body.lower() or "quota" in err_body.lower():
                        if len(keys_pool) > 1 and k_idx < len(keys_pool):
                            next_key_preview = f"...{keys_pool[k_idx][-6:]}" if len(keys_pool[k_idx]) > 8 else "Key"
                            print(
                                f"[smart-shift] Evaluator Key {k_idx}/{len(keys_pool)} ({key_preview}) hit HTTP {e.code}. "
                                f"Smart shifting to Key {k_idx + 1}/{len(keys_pool)} ({next_key_preview})...",
                                file=sys.stderr,
                                flush=True,
                            )
                            break
                    if attempt < 1:
                        time.sleep(1.0)
                    else:
                        break
                except Exception:
                    break

            if model_failed:
                break

        if model_failed:
            continue

    return None


# --------------------------------------------------------------------------
# Terminal Output Display
# --------------------------------------------------------------------------

def display_evaluation(local_result: dict, ai_result: Optional[dict] = None) -> None:
    """Prints a clean, formatted evaluation report to terminal."""

    print("\n" + "═" * 55)
    print("         JD EVALUATION REPORT")
    print("═" * 55)

    if ai_result:
        print(f"  Company    : {ai_result.get('company', 'Unknown')}")
        print(f"  Role       : {ai_result.get('role', 'Unknown')}")
        print(f"  Score      : {ai_result.get('score', 0)}/100")
        print("─" * 55)

    # Verdict with color-like symbols
    verdict = ai_result.get("verdict") if ai_result else local_result["local_verdict"]
    one_line = ai_result.get("one_line_reason", "") if ai_result else ""

    if verdict == "APPLY":
        reason_str = f" — {one_line}" if one_line else ""
        print(f"  VERDICT    : ✅  APPLY{reason_str}")
    elif verdict == "BORDERLINE":
        reason_str = f" — {one_line}" if one_line else ""
        print(f"  VERDICT    : ⚠️   BORDERLINE{reason_str}")
    else:
        first_block = local_result["hard_blocks"][0] if local_result.get("hard_blocks") else "Hard blocker detected"
        reason_str = f" — {one_line if one_line else first_block}"
        print(f"  VERDICT    : ❌  SKIP{reason_str}")

    print("─" * 55)

    # Hard blocks
    if local_result.get("hard_blocks"):
        print("\n  HARD BLOCKS (auto-skip reasons):")
        for block in local_result["hard_blocks"]:
            print(f"    {block}")

    # AI analysis skills
    if ai_result:
        if ai_result.get("missing_skills"):
            print("\n  MISSING SKILLS:")
            for s in ai_result["missing_skills"][:5]:
                print(f"    ❌ {s}")

        if ai_result.get("matched_skills"):
            print("\n  MATCHED SKILLS:")
            for s in ai_result["matched_skills"][:8]:
                print(f"    ✅ {s}")

    # Warnings
    all_warnings = list(local_result.get("warnings", []))
    if ai_result and ai_result.get("warnings"):
        all_warnings += ai_result["warnings"]
    if all_warnings:
        print("\n  WARNINGS:")
        for w in set(all_warnings):
            print(f"    {w}")

    # Green flags
    if local_result.get("green_flags_found"):
        print("\n  GREEN FLAGS:")
        for f in local_result["green_flags_found"][:5]:
            print(f"    {f}")

    # Action & recommended resume version
    if ai_result:
        print(f"\n  ACTION     : {ai_result.get('apply_action', 'Review manually')}")
        print(f"  RESUME     : Use the '{ai_result.get('resume_version', 'general')}' version")

    print("═" * 55 + "\n")


# --------------------------------------------------------------------------
# Standalone CLI Entry Point
# --------------------------------------------------------------------------

if __name__ == "__main__":
    _load_dotenv_if_present()
    if len(sys.argv) < 2:
        print("Usage: python evaluate.py <jd_file_or_text>")
        sys.exit(1)

    target = sys.argv[1]
    if os.path.isfile(target):
        with open(target, "r", encoding="utf-8") as f:
            jd = f.read()
    else:
        jd = target

    loc = local_evaluate(jd)
    ai = ai_evaluate(jd)
    display_evaluation(loc, ai)

#!/usr/bin/env python3
"""
resume_tailor.py — Core engine to tailor a LaTeX resume for a specific job posting using Groq.

Usage:
    python resume_tailor.py --resume master.tex --job job.txt --output out.tex
    python resume_tailor.py --resume master.tex --job "Raw JD text" --output out.tex
    python resume_tailor.py --resume master.tex --job-url "https://example.com/job" --output out.tex
    python resume_tailor.py --resume master.tex --job job.txt --company "Acme" --role "SWE" --compile
"""

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Optional

# Ensure standard streams handle Unicode characters on all platforms (including Windows cp1252)
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

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.8-27b"
FALLBACK_MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]


# --------------------------------------------------------------------------
# Environment Variable / .env Loader (Standard Library only)
# --------------------------------------------------------------------------

def load_dotenv_if_present():
    """
    Lightweight .env loader using only the Python standard library.
    Checks CWD, script directory, and ~/.resume_tailor/.env.
    """
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
    Collect all unique Groq API keys configured across .env and environment variables.
    Supports:
      GROQ_API_KEY=...
      GROQ_API_KEY_2=...
      GROQ_API_KEY_3=...
      GROQ_API_KEYS=key1,key2
    """
    load_dotenv_if_present()
    keys: list[str] = []

    # 1. Inspect environment variables
    for k, v in os.environ.items():
        if k == "GROQ_API_KEY" or k.startswith("GROQ_API_KEY_") or k == "GROQ_API_KEYS":
            for part in v.replace(";", ",").split(","):
                clean = part.strip().strip("'\"")
                if clean and clean not in keys:
                    keys.append(clean)

    # 2. Sequential scan in .env files to preserve declaration order
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.expanduser("~/.resume_tailor/.env"),
    ]
    file_keys: list[str] = []
    for env_path in candidates:
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, val = line.split("=", 1)
                            k = k.strip()
                            if k == "GROQ_API_KEY" or k.startswith("GROQ_API_KEY_") or k == "GROQ_API_KEYS":
                                for part in val.replace(";", ",").split(","):
                                    clean = part.strip().strip("'\"")
                                    if clean and clean not in file_keys:
                                        file_keys.append(clean)
            except Exception:
                pass
            if file_keys:
                break

    all_keys: list[str] = []
    for k in file_keys + keys:
        if k not in all_keys:
            all_keys.append(k)

    return all_keys


# --------------------------------------------------------------------------
# HTML-to-Plaintext Parser (Standard Library only)
# --------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """
    Strips HTML tags and scripts/styles, returning clean plaintext
    using only Python's standard library html.parser.
    """
    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript", "head", "title", "meta"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "noscript", "head", "title", "meta"):
            self._skip = False
        if tag.lower() in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "section", "article"):
            self.chunks.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.chunks.append(data)

    def get_text(self) -> str:
        text = "".join(self.chunks)
        # Collapse multiple horizontal spaces/tabs into single space
        text = re.sub(r"[ \t]+", " ", text)
        # Collapse 3+ consecutive newlines into 2
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()


def fetch_job_from_url(url: str) -> str:
    """
    Fetches web content from the given URL and strips HTML to plain text.
    Warns if content seems suspiciously short (e.g. JS-rendered SPA).

    SECURITY NOTE (SSRF):
    In this standalone CLI tool, URLs are directly provided by the local user.
    If this functionality is ever integrated into a hosted multi-tenant web service,
    an allow-list or private IP filter MUST be enforced to prevent Server-Side Request
    Forgery (e.g. blocking 127.0.0.1, 169.254.169.254, RFC1918 subnets, and non-standard ports).
    """
    clean_url = url.strip()
    if not clean_url.lower().startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL '{url}'. URL must begin with http:// or https://")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = urllib.request.Request(clean_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw_html = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to fetch job URL '{clean_url}': {e}") from e

    parser = _HTMLTextExtractor()
    parser.feed(raw_html)
    text = parser.get_text()

    if len(text) < 200:
        print(
            "[warn] Fetched page text is very short (< 200 chars). "
            "The site may require JavaScript to render. "
            "If the result is incomplete, copy and paste the job description manually.",
            file=sys.stderr,
        )
    return text


def read_multiline_paste() -> str:
    """
    Reads multi-line text interactively from the terminal.
    Terminates when the user enters 'END' on its own line,
    or triggers EOF (Ctrl+Z + Enter on Windows, Ctrl+D on Unix).
    """
    print("\n" + "=" * 60)
    print(" Paste the Job Description below.")
    print(" When finished, type 'END' on a new line and press Enter:")
    print(" (or press Ctrl+Z then Enter on Windows / Ctrl+D on Unix)")
    print("=" * 60, flush=True)
    lines = []
    try:
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
    except EOFError:
        pass
    text = "\n".join(lines).strip()
    return text


def load_job_description(args: argparse.Namespace) -> str:
    """
    Loads the job description from --job-url, a file path passed to --job,
    raw text passed to --job, or interactive terminal paste (--paste).
    """
    if getattr(args, "job_url", None):
        return fetch_job_from_url(args.job_url)

    if getattr(args, "job", None):
        # Check if the argument is an existing file path
        if os.path.isfile(args.job):
            try:
                with open(args.job, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError as e:
                raise RuntimeError(f"Could not read job description file '{args.job}': {e}") from e
        # Otherwise treat as raw text
        return args.job

    if getattr(args, "paste", False):
        return read_multiline_paste()

    raise ValueError("Provide --job (file path or text), --job-url, or --paste.")


# --------------------------------------------------------------------------
# Groq API Client (Urllib / Standard Library)
# --------------------------------------------------------------------------

def call_groq(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str | list[str] | None = None,
    api_base: Optional[str] = None
) -> str:
    """
    Calls the Groq chat completions API with smart key shifting and model fallback.
    - If a key hits rate limit (429), quota exceeded, or auth error (401/403), it automatically
      shifts to the next available API key immediately.
    - If a model returns 404 (model_not_found), it tries the next fallback model.
    """
    endpoint = api_base or os.environ.get("GROQ_BASE_URL") or GROQ_API_URL
    if not endpoint.endswith("/chat/completions") and not endpoint.endswith("/"):
        endpoint = f"{endpoint}/chat/completions"

    # Normalize key pool
    if isinstance(api_key, list):
        keys_pool = [k for k in api_key if k]
    elif isinstance(api_key, str) and api_key.strip():
        keys_pool = [api_key.strip()]
    else:
        keys_pool = get_groq_api_keys()

    if not keys_pool:
        raise ValueError("No Groq API keys found. Set GROQ_API_KEY in .env or pass --api-key.")

    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_error = None

    for curr_model in models_to_try:
        model_failed = False

        for k_idx, curr_key in enumerate(keys_pool, 1):
            key_preview = f"...{curr_key[-6:]}" if len(curr_key) > 8 else curr_key
            payload = {
                "model": curr_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 6000,
            }
            json_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=json_data,
                headers={
                    "Authorization": f"Bearer {curr_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                },
                method="POST",
            )

            max_retries = 2
            base_delay = 1.5

            for attempt in range(1, max_retries + 1):
                try:
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        response_body = resp.read().decode("utf-8")
                        try:
                            response_json = json.loads(response_body)
                        except json.JSONDecodeError as e:
                            raise RuntimeError(f"Failed to parse API response as JSON: {e}\nRaw output:\n{response_body[:500]}") from e

                        try:
                            return response_json["choices"][0]["message"]["content"]
                        except (KeyError, IndexError) as e:
                            raise RuntimeError(f"Unexpected response format from API: {response_body}") from e

                except urllib.error.HTTPError as e:
                    err_body = e.read().decode("utf-8", errors="ignore")
                    last_error = f"API error (HTTP {e.code}): {err_body}"

                    # 1. Model not found -> break to try next model
                    if e.code == 404 and "model_not_found" in err_body:
                        print(f"[warn] Model '{curr_model}' not found. Trying fallback model...", file=sys.stderr)
                        model_failed = True
                        break

                    # 2. Rate limit (429) or Quota or Auth error (401/403) -> SMART SHIFT TO NEXT KEY
                    if e.code in (429, 401, 402) or "rate_limit" in err_body.lower() or "quota" in err_body.lower():
                        if len(keys_pool) > 1 and k_idx < len(keys_pool):
                            next_key_preview = f"...{keys_pool[k_idx][-6:]}" if len(keys_pool[k_idx]) > 8 else "Key"
                            print(
                                f"[smart-shift] Key {k_idx}/{len(keys_pool)} ({key_preview}) hit HTTP {e.code}. "
                                f"Smart shifting to Key {k_idx + 1}/{len(keys_pool)} ({next_key_preview})...",
                                file=sys.stderr,
                                flush=True,
                            )
                            # Immediately break out to try next key in pool
                            break

                    # 3. Transient server errors (500, 502, 503, 504) -> retry with backoff
                    if e.code in (500, 502, 503, 504) and attempt < max_retries:
                        sleep_time = base_delay * (2 ** (attempt - 1))
                        print(f"[retry] API returned HTTP {e.code}. Retrying in {sleep_time:.1f}s (attempt {attempt}/{max_retries})...", file=sys.stderr)
                        time.sleep(sleep_time)
                        continue

                    # If not retryable and more keys exist, try next key
                    if len(keys_pool) > 1 and k_idx < len(keys_pool):
                        print(f"[smart-shift] Key {k_idx} encountered error. Shifting to next key...", file=sys.stderr)
                        break

                except urllib.error.URLError as e:
                    last_error = f"Network connection error: {e}"
                    if attempt < max_retries:
                        sleep_time = base_delay * (2 ** (attempt - 1))
                        print(f"[retry] Network error: {e.reason}. Retrying in {sleep_time:.1f}s (attempt {attempt}/{max_retries})...", file=sys.stderr)
                        time.sleep(sleep_time)
                        continue

            if model_failed:
                break

        if model_failed:
            continue

        # If we reached here without returning, all keys failed on curr_model
        print(f"[warn] All {len(keys_pool)} key(s) failed for model '{curr_model}'. Trying next fallback model...", file=sys.stderr)

    raise RuntimeError(f"All API calls across {len(keys_pool)} key(s) and all models failed. Last error: {last_error}")


# --------------------------------------------------------------------------
# LaTeX Extraction & Validation
# --------------------------------------------------------------------------

def extract_latex(model_output: str) -> str:
    """
    Strips markdown code fences (```latex ... ``` or ``` ...) if present.
    """
    fence_match = re.search(r"```(?:latex|tex)?\s*\n?(.*?)\n?```", model_output, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return model_output.strip()


def sanitize_latex(tex: str) -> str:
    """
    Replaces Unicode punctuation and special characters with standard LaTeX equivalents
    to prevent UnicodeEncodeError in cp1252 consoles and LaTeX compilation errors.
    """
    replacements = {
        "\u2011": "-",   # non-breaking hyphen
        "\u2010": "-",   # hyphen
        "\u2012": "-",   # figure dash
        "\u2013": "--",  # en dash
        "\u2014": "---", # em dash
        "\u2018": "`",   # left single quote
        "\u2019": "'",   # right single quote
        "\u201c": "``",  # left double quote
        "\u201d": "''",  # right double quote
        "\u00a0": " ",   # non-breaking space
        "\u2026": "...", # ellipsis
        "\u2022": "\\textbullet{}", # bullet
    }
    for orig, rep in replacements.items():
        tex = tex.replace(orig, rep)
    tex = sanitize_summary_methodology_claims(tex)
    return tex


def sanitize_summary_methodology_claims(tex: str) -> str:
    """Ensure summary does not claim TDD when bullets only reflect after-the-fact testing."""
    summary_match = re.search(r"(\\begin\{rSection\}\{SUMMARY\})(.*?)(\\end\{rSection\})", tex, re.DOTALL | re.IGNORECASE)
    if not summary_match:
        return tex
    prefix, summary_body, suffix = summary_match.group(1), summary_match.group(2), summary_match.group(3)
    rest_of_tex = tex[summary_match.end():].lower()
    if re.search(r"\b(?:tdd|test-driven(?:\s+development)?)\b", summary_body, re.IGNORECASE) and not re.search(r"\b(?:tdd|test-driven(?:\s+development)?)\b", rest_of_tex):
        cleaned_body = re.sub(r"(?i)\bproficient\s+in\s+tdd\b", "Strong focus on test coverage and reliability", summary_body)
        cleaned_body = re.sub(r"(?i)\btdd\b", "automated testing", cleaned_body)
        return tex[:summary_match.start()] + prefix + cleaned_body + suffix + tex[summary_match.end():]
    return tex


def braces_balanced(tex: str) -> bool:
    """
    Checks whether curly braces { } in LaTeX are balanced,
    ignoring escaped braces (\\{ and \\}).
    """
    depth = 0
    escaped = False
    for ch in tex:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth < 0:
            return False
    return depth == 0


def looks_like_latex(tex: str) -> bool:
    """
    Validates that the output contains standard LaTeX markup indicators.
    """
    has_doc_class = r"\documentclass" in tex
    has_begin_doc = r"\begin{document}" in tex
    has_section = r"\section" in tex
    return has_doc_class or has_begin_doc or has_section


def extract_master_facts(master_tex: str) -> dict:
    """
    Extract grounded candidate facts directly from the master resume LaTeX.
    Ensures master_resume.tex is the single dynamic source of truth everywhere.
    """
    facts = {
        "name": "Chinmay Maheshwari",
        "phone": "9460449962",
        "email": "chinmaymaheshwari.it27@gmail.com",
        "cgpa": "8.8",
        "grad_years": "2023 -- 2027",
        "internship_dates": "May 2026 -- June 2026",
        "dsa_count": "400+",
        "cert_name": "Java Development Certification",
        "publication_type": "review paper",
    }
    if not master_tex:
        return facts

    # Name
    name_match = re.search(r"\\name\{([^}]+)\}", master_tex)
    if name_match:
        facts["name"] = name_match.group(1).strip()

    # Phone
    phone_match = re.search(r"(\+?\d[\d\s-]{8,}\d)", master_tex)
    if phone_match:
        digits = re.sub(r"[^\d]", "", phone_match.group(1))
        if len(digits) == 12 and digits.startswith("91"):
            facts["phone"] = digits[2:]
        else:
            facts["phone"] = digits

    # Email
    email_match = re.search(r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", master_tex)
    if email_match:
        facts["email"] = email_match.group(1).strip()

    # CGPA
    cgpa_match = re.search(r"CGPA\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)", master_tex, re.IGNORECASE)
    if cgpa_match:
        facts["cgpa"] = cgpa_match.group(1).strip()

    # Graduation / Academic Year
    grad_match = re.search(r"(\b202\d\s*(?:--|-|–)\s*202\d\b)", master_tex)
    if grad_match:
        facts["grad_years"] = grad_match.group(1).strip()

    # Internship dates
    intern_match = re.search(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d\d\s*(?:--|-|–)\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d\d)",
        master_tex,
        re.IGNORECASE,
    )
    if intern_match:
        facts["internship_dates"] = intern_match.group(1).strip()

    # LeetCode / DSA problem count (e.g. \textbf{400+} or 400+ problems)
    dsa_match = re.search(
        r"(?:\\textbf\{)?(\d+\+?)(?:\})?\s*(?:DSA\s+problems|problems\s+across\s+LeetCode|problems\s+on\s+LeetCode)",
        master_tex,
        re.IGNORECASE,
    )
    if dsa_match:
        facts["dsa_count"] = dsa_match.group(1).strip()

    # Certification
    cert_match = re.search(r"([A-Za-z0-9\s]+?Certification)", master_tex)
    if cert_match:
        val = cert_match.group(1).strip()
        val = re.sub(r"^(?:Earned\s+(?:an?\s+)?|item\s+)+", "", val).strip()
        facts["cert_name"] = val

    # Publication type
    pub_match = re.search(r"Published\s+a\s+(review|research)\s+paper", master_tex, re.IGNORECASE)
    if pub_match:
        facts["publication_type"] = pub_match.group(1).lower() + " paper"

    return facts


def get_validation_errors(tailored_tex: str, master_tex: str) -> list[str]:
    """
    Validates that personal details, candidate facts, and structural formatting
    from the master resume are strictly preserved in the tailored output.
    Returns a list of validation error descriptions.
    """
    errors = []
    facts = extract_master_facts(master_tex)

    # 1. Check personal details preserved
    name = facts.get("name", "Chinmay Maheshwari")
    if name in master_tex and name not in tailored_tex:
        errors.append(f"Name was changed (expected '{name}')")

    phone = facts.get("phone", "9460449962")
    clean_tailored_digits = re.sub(r"[^\d]", "", tailored_tex)
    if phone and phone not in clean_tailored_digits:
        errors.append("Phone was changed")

    email = facts.get("email", "chinmaymaheshwari.it27@gmail.com")
    if email in master_tex and email not in tailored_tex:
        errors.append("Email was changed")

    # 2. Check accuracy rules
    if "research paper" in tailored_tex.lower() and "research paper" not in master_tex.lower():
        errors.append("Says 'research paper' instead of 'review paper'")
    if "Professional Java" in tailored_tex and "Professional Java" not in master_tex:
        errors.append("Says 'Professional Java Development Certification'")

    # 3. Dynamic LeetCode count check derived from master_tex
    expected_dsa = facts.get("dsa_count")
    if expected_dsa:
        if expected_dsa not in tailored_tex:
            errors.append(f"Expected LeetCode/DSA count '{expected_dsa}' not found in tailored resume")
        # Ensure it didn't drift to conflicting numbers
        for drift_count in ["300+", "400+", "500+", "600+"]:
            if drift_count != expected_dsa and drift_count in tailored_tex:
                errors.append(f"Wrong LeetCode count: found '{drift_count}' instead of expected '{expected_dsa}'")

    # 4. Internship dates check
    if "May 2026 -- Present" in tailored_tex or "May 2026 – Present" in tailored_tex or "May 2026 - Present" in tailored_tex:
        errors.append("Internship marked as ongoing")

    # 5. Check methodology claims self-consistency (e.g. TDD claimed in summary without bullets evidence)
    summary_match = re.search(r"\\begin\{rSection\}\{SUMMARY\}(.*?)\\end\{rSection\}", tailored_tex, re.DOTALL | re.IGNORECASE)
    if summary_match:
        summary_text = summary_match.group(1).lower()
        if re.search(r"\b(?:tdd|test-driven(?:\s+development)?)\b", summary_text):
            bullets_text = tailored_tex[summary_match.end():].lower()
            if not re.search(r"\b(?:tdd|test-driven(?:\s+development)?)\b", bullets_text):
                errors.append("Summary claims TDD / Test-Driven Development without supporting evidence in experience/project bullets")

    # 6. Check structure preserved
    if "\\begin{itemize}" in master_tex and "\\begin{itemize}" not in tailored_tex:
        errors.append("itemize environment removed")
    if ">{\\bfseries}l" in master_tex and ">{\\bfseries}l" not in tailored_tex:
        errors.append("Skills tabular format broken")

    return errors


def validate_output(tailored_tex: str, master_tex: str) -> bool:
    """
    Validates that personal details, candidate facts, and structural formatting
    from the master resume are strictly preserved in the tailored output.
    """
    errors = get_validation_errors(tailored_tex, master_tex)
    if errors:
        print("\n[VALIDATION WARNINGS]", file=sys.stderr)
        for e in errors:
            print(f"  ⚠️  {e}", file=sys.stderr)
        print("Review the output carefully before using.\n", file=sys.stderr)

    return len(errors) == 0


def build_validation_retry_prompt(invalid_tex: str, errors: list[str]) -> str:
    """
    Constructs an error-feedback prompt for the LLM to fix specific validation errors.
    """
    bullet_errors = "\n".join(f"- {e}" for e in errors)
    return f"""The previous LaTeX resume output contained validation errors that violate candidate facts or LaTeX structure:

VALIDATION ERRORS TO FIX:
{bullet_errors}

PREVIOUS TAILORED LATEX RESUME:
==================================================
{invalid_tex.strip()}
==================================================

Please fix these exact errors immediately.
Rules:
- Strictly correct all listed errors (e.g. restore accurate LeetCode count, candidate facts, or structure).
- Preserve all other good bullet rewrites, ATS keywords, and LaTeX styling.
- Return ONLY the full corrected LaTeX source code starting from \\documentclass to \\end{{document}}.
- Do NOT include any markdown code fences, notes, or explanations.
"""


# --------------------------------------------------------------------------
# System & User Prompts
# --------------------------------------------------------------------------

def build_tailor_system_prompt(master_tex: Optional[str] = None) -> str:
    """
    Dynamically builds the tailoring system prompt using candidate facts extracted
    directly from master_tex, preventing factual drift or contradiction.
    """
    facts = extract_master_facts(master_tex) if master_tex else extract_master_facts("")
    cgpa = facts.get("cgpa", "8.8")
    grad_years = facts.get("grad_years", "2023 -- 2027")
    internship_dates = facts.get("internship_dates", "May 2026 -- June 2026")
    dsa_count = facts.get("dsa_count", "400+")
    cert_name = facts.get("cert_name", "Java Development Certification")
    pub_type = facts.get("publication_type", "review paper")

    return f"""You are an expert resume writer who tailors LaTeX resumes for specific job descriptions.
You receive a master LaTeX resume and a job description. Your job is to tailor the resume
content while preserving ALL LaTeX formatting exactly.

═══════════════════════════════════════════════════════════
ABSOLUTE RULES — NEVER VIOLATE ANY OF THESE
═══════════════════════════════════════════════════════════

STRUCTURE PRESERVATION:
- Output ONLY the complete LaTeX source, no explanations, no markdown fences
- Never change \\documentclass, \\usepackage, or geometry settings
- Never change \\begin{{itemize}} / \\item to em-dashes or any other format
- Never modify \\vspace, \\hspace, or spacing commands
- Never change tabular structure in the skills section
- Never modify \\textbf, \\hfill, or alignment commands
- Never change \\begin{{rSection}} names or formatting
- The output must compile without errors in the same LaTeX environment as the input

PERSONAL DETAILS — NEVER CHANGE:
- Name, phone, email, LinkedIn, GitHub, LeetCode URLs
- All \\href{{}} certificate and paper URLs
- CGPA: {cgpa}, Graduation: {grad_years}

CANDIDATE FACTS — NEVER CONTRADICT:
- Internship: {internship_dates} (completed)
- LeetCode: exactly "{dsa_count}"
- Publication: "{pub_type}" NOT "research paper"
- Certification: "{cert_name}" only
- Python: "(basics)" only
- Graduation: May/June 2027

PAGE LENGTH:
- Output must fit exactly ONE page
- Summary: maximum 3 lines
- Experience: maximum 3 bullets per role, 2 lines each
- Projects: maximum 2 bullets per project, 2 lines each
- Achievements: maximum 4 items, 1 line each

CONTENT ACCURACY & METHODOLOGY CLAIMS:
- Never invent metrics not in the master resume
- Never add technologies not in the master resume
- Never fabricate employers, dates, or achievements
- Rephrase bullets using JD keywords only where truthfully applicable
- SELF-CONSISTENCY GUARDRAIL: Never claim a methodology, engineering practice, or proficiency level in the Summary (e.g. "Proficient in TDD", "expert in X", "specialized in Y") that is not directly evidenced by the experience or project bullets in that same resume. If the JD mentions a practice like TDD / Test-Driven Development and the candidate's actual bullets describe testing after implementation (such as integration, regression, or concurrency testing), the summary must reflect that precisely (e.g. "strong focus on test coverage and reliability" or "experienced in automated testing and regression validation") rather than claiming TDD specifically. Never echo the JD's methodology buzzwords as an unsupported personal claim.

═══════════════════════════════════════════════════════════
WHAT YOU MAY CHANGE
═══════════════════════════════════════════════════════════

1. SUMMARY — Rewrite to mirror JD language where truthful, max 3 lines, specific to role. Strictly adhere to the self-consistency guardrail: do not claim methodologies or proficiency levels (e.g. TDD) not directly backed by experience/project bullets.
2. SKILLS — Reorder rows to put most JD-relevant skills first, keep same format
3. BULLET POINTS — Rephrase using JD keywords where truthful, keep \\item format
4. PROJECT ORDER — Lead with the project most relevant to the JD
5. SKILLS VALUES — Add JD-relevant skills that exist in the master resume

═══════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════

Return ONLY the complete LaTeX code starting from \\documentclass to \\end{{document}}.
No explanations. No markdown. No commentary. Just the LaTeX.
"""


SYSTEM_PROMPT = build_tailor_system_prompt()


def build_user_prompt(resume_tex: str, job_description: str, company: str, role: str) -> str:
    """
    Constructs the prompt sent to Groq with context, JD, and current LaTeX resume.
    """
    target_info = []
    if company:
        target_info.append(f"Company: {company}")
    if role:
        target_info.append(f"Target Role: {role}")
    target_header = "\n".join(target_info)
    if target_header:
        target_header = f"TARGET APPLICATION:\n{target_header}\n\n"

    return f"""{target_header}TARGET JOB DESCRIPTION:
==================================================
{job_description.strip()}
==================================================

MASTER RESUME LATEX SOURCE:
==================================================
{resume_tex.strip()}
==================================================

Rewrite the master resume LaTeX above to tailor it precisely for the target job description according to all your instructions.
Return ONLY the full updated LaTeX source code, starting from \\documentclass (or the first line) to \\end{{document}}.
"""


# --------------------------------------------------------------------------
# Diff View
# --------------------------------------------------------------------------

def print_diff(original_tex: str, tailored_tex: str, original_name: str = "original.tex", tailored_name: str = "tailored.tex") -> None:
    """
    Prints a clean unified diff between the original and tailored LaTeX text.
    """
    diff = difflib.unified_diff(
        original_tex.splitlines(keepends=True),
        tailored_tex.splitlines(keepends=True),
        fromfile=original_name,
        tofile=tailored_name,
    )
    diff_lines = list(diff)
    if not diff_lines:
        print("\n[diff] No textual changes detected between original and tailored resume.\n")
        return

    print("\n" + "=" * 70)
    print("UNIFIED DIFF (Changes Made to Resume):")
    print("=" * 70)
    use_color = sys.stdout.isatty()
    for line in diff_lines:
        line_str = line.rstrip("\n")
        if line_str.startswith("+++") or line_str.startswith("---"):
            print(f"\033[1m{line_str}\033[0m" if use_color else line_str)
        elif line_str.startswith("+"):
            print(f"\033[32m{line_str}\033[0m" if use_color else line_str)
        elif line_str.startswith("-"):
            print(f"\033[31m{line_str}\033[0m" if use_color else line_str)
        elif line_str.startswith("@@"):
            print(f"\033[36m{line_str}\033[0m" if use_color else line_str)
        else:
            print(line_str)
    print("=" * 70 + "\n")


# --------------------------------------------------------------------------
# PDF Compilation
# --------------------------------------------------------------------------

def compile_pdf(tex_path: str) -> bool:
    """
    Compiles the LaTeX file to PDF. Detects available engine (latexmk, pdflatex, xelatex).
    """
    compiler = None
    compiler_cmd = None

    # Check for tectonic first (preferred zero-dependency compiler)
    possible_tectonic = [
        shutil.which("tectonic"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "bin", "tectonic.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "bin", "tectonic"),
        os.path.join(os.getcwd(), "tools", "bin", "tectonic.exe"),
    ]
    for pt in possible_tectonic:
        if pt and os.path.isfile(pt):
            compiler = "tectonic"
            compiler_cmd = os.path.abspath(pt)
            break

    if not compiler:
        for candidate in ("latexmk", "pdflatex", "xelatex"):
            if shutil.which(candidate):
                compiler = candidate
                compiler_cmd = candidate
                break

    if not compiler:
        print(
            "[warn] No LaTeX compiler found on PATH (checked tectonic, latexmk, pdflatex, xelatex).\n"
            "       Install TeX Live, MacTeX, MiKTeX, or ensure tools/bin/tectonic.exe exists.",
            file=sys.stderr,
        )
        return False

    abs_tex = os.path.abspath(tex_path)
    work_dir = os.path.dirname(abs_tex) or "."
    base_name = os.path.splitext(os.path.basename(abs_tex))[0]
    pdf_path = os.path.join(work_dir, f"{base_name}.pdf")

    # Ensure resume.cls is available in the target compilation directory
    cls_source = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.cls")
    cls_dest = os.path.join(work_dir, "resume.cls")
    if os.path.isfile(cls_source) and not os.path.isfile(cls_dest):
        try:
            shutil.copy2(cls_source, cls_dest)
        except Exception:
            pass

    print(f"[compile] Compiling PDF using '{compiler}' ({compiler_cmd})...")

    if compiler == "tectonic":
        res = subprocess.run(
            [compiler_cmd, abs_tex, "-o", work_dir],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        success = os.path.isfile(pdf_path)
        last_out = (res.stdout or "") + "\n" + (res.stderr or "")
    elif compiler == "latexmk":
        res = subprocess.run(
            ["latexmk", "-pdf", "-interaction=nonstopmode", f"-output-directory={work_dir}", abs_tex],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        success = os.path.isfile(pdf_path)
        last_out = res.stdout
    else:
        # pdflatex or xelatex: run twice for cross-references
        print(f"[compile] Running {compiler} (pass 1/2)...")
        subprocess.run(
            [compiler, "-interaction=nonstopmode", "-output-directory", work_dir, abs_tex],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        print(f"[compile] Running {compiler} (pass 2/2)...")
        res2 = subprocess.run(
            [compiler, "-interaction=nonstopmode", "-output-directory", work_dir, abs_tex],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        success = os.path.isfile(pdf_path)
        last_out = res2.stdout

    if success:
        print(f"[compile] PDF successfully generated: {pdf_path}")
        return True
    else:
        print("[compile] [error] PDF compilation failed.", file=sys.stderr)
        log_snippet = (last_out or "")[-2000:]
        if log_snippet:
            print(f"----- {compiler} output (tail) -----\n{log_snippet}", file=sys.stderr)
        return False


def load_github_dossier() -> str:
    """Loads verified GitHub project dossier if present."""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "github_dossier.md"),
        os.path.join(os.getcwd(), "builder", "github_dossier.md"),
        os.path.join(os.getcwd(), "github_dossier.md"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass
    return ""


def get_tailor_system_prompt(master_tex: Optional[str] = None) -> str:
    base_prompt = build_tailor_system_prompt(master_tex)
    dossier = load_github_dossier()
    if not dossier:
        return base_prompt
    return base_prompt + f"""

═══════════════════════════════════════════════════════════
VERIFIED CANDIDATE GITHUB PROJECT DOSSIER (GROUND TRUTH)
═══════════════════════════════════════════════════════════
The following technical details, features, dependencies, and architectures are extracted directly from the candidate's real GitHub repositories.
Whenever tailoring, expanding points, or elaborating on projects, draw ONLY from these verified facts:

{dossier}

GROUND TRUTH ENFORCEMENT:
- If asked to add more points or elaborate on projects, use the ACTUAL features above (e.g. SHA-256 idempotency fingerprinting, Redisson distributed locks, transactional saga compensation, BullMQ queues, atomic $gte MongoDB stock updates).
- NEVER invent outside libraries, fake metrics, or fake architectures that are not present in their codebases or master resume.
"""


def build_refine_system_prompt(current_tex: Optional[str] = None) -> str:
    facts = extract_master_facts(current_tex) if current_tex else extract_master_facts("")
    cgpa = facts.get("cgpa", "8.8")
    grad_years = facts.get("grad_years", "2023 -- 2027")
    return f"""You are an expert resume editor. You receive a previously tailored LaTeX resume, a job description, and specific change requests/feedback from the candidate.
Your job is to apply the candidate's feedback and refine the resume while preserving ALL LaTeX structure, ATS formatting, and candidate facts.

CRITICAL RULES:
- Never change personal details (name, email, phone, links, graduation year {grad_years}, CGPA {cgpa})
- Never invent technologies or facts not in the resume or GitHub dossier
- Never claim methodologies, practices, or proficiency levels (e.g. "Proficient in TDD") not directly evidenced by the bullets in the resume
- Must fit on exactly ONE page
- Strictly maintain \\documentclass{{resume}}, tabular skills environment, and itemize formatting
- Return ONLY the full updated LaTeX source code from \\documentclass to \\end{{document}}. No markdown fences, no explanations.
"""


REFINE_SYSTEM_PROMPT = build_refine_system_prompt()


def get_refine_system_prompt(current_tex: Optional[str] = None) -> str:
    base_prompt = build_refine_system_prompt(current_tex)
    dossier = load_github_dossier()
    if not dossier:
        return base_prompt
    return base_prompt + f"""

═══════════════════════════════════════════════════════════
VERIFIED CANDIDATE GITHUB PROJECT DOSSIER (GROUND TRUTH)
═══════════════════════════════════════════════════════════
The following technical details, features, dependencies, and architectures are extracted directly from the candidate's real GitHub repositories.
Whenever refining, expanding points, or elaborating on projects, draw ONLY from these verified facts:

{dossier}

GROUND TRUTH ENFORCEMENT:
- When applying candidate requests (e.g. "add more points to projects" or "elaborate on architecture"), use the ACTUAL architecture details from the dossier above.
- NEVER invent outside libraries, fake metrics, or fake architectures that are not present in their codebases or master resume.
"""


def tailor_resume(
    master_tex: str,
    job_description: str,
    company: str = "",
    role: str = "",
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> str:
    """
    Tailor a master resume LaTeX document for a specific JD and return the resulting LaTeX string.
    Includes a single automatic retry with validation error feedback if facts or formatting drift.
    """
    keys = get_groq_api_keys()
    if api_key:
        if api_key in keys:
            keys.remove(api_key)
        keys.insert(0, api_key)
    if not keys:
        raise ValueError("No Groq API keys found. Configure GROQ_API_KEY in .env.")

    user_prompt = build_user_prompt(master_tex, job_description, company, role)
    system_prompt = get_tailor_system_prompt(master_tex)
    raw_output = call_groq(system_prompt, user_prompt, model, keys, api_base)
    tailored_tex = sanitize_latex(extract_latex(raw_output))
    if not looks_like_latex(tailored_tex):
        raise ValueError("AI output did not contain valid LaTeX markup.")

    val_errors = get_validation_errors(tailored_tex, master_tex)
    if val_errors:
        print("\n[VALIDATION WARNINGS — Retrying once with error feedback...]", file=sys.stderr)
        for e in val_errors:
            print(f"  ⚠️  {e}", file=sys.stderr)
        retry_prompt = build_validation_retry_prompt(tailored_tex, val_errors)
        raw_retry = call_groq(system_prompt, retry_prompt, model, keys, api_base)
        retry_tex = sanitize_latex(extract_latex(raw_retry))
        if not looks_like_latex(retry_tex):
            raise ValueError("AI retry output did not contain valid LaTeX markup.")
        val_errors_retry = get_validation_errors(retry_tex, master_tex)
        if val_errors_retry:
            error_list = "; ".join(val_errors_retry)
            raise ValueError(f"Resume tailoring validation failed after retry: {error_list}")
        tailored_tex = retry_tex

    return tailored_tex


def refine_resume(
    current_tex: str,
    feedback: str,
    job_description: str = "",
    company: str = "",
    role: str = "",
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> str:
    """
    Refine an existing tailored LaTeX resume based on user feedback.
    Includes a single automatic retry with validation error feedback if facts or formatting drift.
    """
    keys = get_groq_api_keys()
    if api_key:
        if api_key in keys:
            keys.remove(api_key)
        keys.insert(0, api_key)
    if not keys:
        raise ValueError("No Groq API keys found. Configure GROQ_API_KEY in .env.")

    user_prompt = f"""TARGET APPLICATION:
Company: {company or 'Company'}
Role: {role or 'Software Engineer'}

TARGET JOB DESCRIPTION:
==================================================
{job_description.strip() if job_description else 'N/A'}
==================================================

CANDIDATE'S FEEDBACK / REQUESTED CHANGES:
==================================================
{feedback.strip()}
==================================================

CURRENT TAILORED RESUME LATEX SOURCE:
==================================================
{current_tex.strip()}
==================================================

Apply the candidate's feedback carefully to refine the LaTeX resume.
Return ONLY the full updated LaTeX source code starting from \\documentclass to \\end{{document}}.
"""
    system_prompt = get_refine_system_prompt(current_tex)
    raw_output = call_groq(system_prompt, user_prompt, model, keys, api_base)
    tailored_tex = sanitize_latex(extract_latex(raw_output))
    if not looks_like_latex(tailored_tex):
        raise ValueError("AI output did not contain valid LaTeX markup.")

    val_errors = get_validation_errors(tailored_tex, current_tex)
    if val_errors:
        print("\n[VALIDATION WARNINGS — Retrying once with error feedback...]", file=sys.stderr)
        for e in val_errors:
            print(f"  ⚠️  {e}", file=sys.stderr)
        retry_prompt = build_validation_retry_prompt(tailored_tex, val_errors)
        raw_retry = call_groq(system_prompt, retry_prompt, model, keys, api_base)
        retry_tex = sanitize_latex(extract_latex(raw_retry))
        if not looks_like_latex(retry_tex):
            raise ValueError("AI retry output did not contain valid LaTeX markup.")
        val_errors_retry = get_validation_errors(retry_tex, current_tex)
        if val_errors_retry:
            error_list = "; ".join(val_errors_retry)
            raise ValueError(f"Resume refinement validation failed after retry: {error_list}")
        tailored_tex = retry_tex

    return tailored_tex


# --------------------------------------------------------------------------
# Main CLI Entry Point
# --------------------------------------------------------------------------

def main():
    load_dotenv_if_present()

    parser = argparse.ArgumentParser(
        description="Resume Tailor — Tailor a LaTeX resume for a specific job posting using Groq AI."
    )
    default_resume = "master_resume.tex" if os.path.isfile("master_resume.tex") else None
    parser.add_argument(
        "--resume",
        default=default_resume,
        required=(default_resume is None),
        help=f"Path to your master .tex resume file (default: {default_resume})" if default_resume else "Path to your master .tex resume file",
    )
    parser.add_argument(
        "--job",
        help="Job description as raw text OR path to a .txt file containing it",
    )
    parser.add_argument(
        "--job-url",
        help="URL of the job posting to fetch and parse",
    )
    parser.add_argument(
        "--paste",
        action="store_true",
        help="Paste the job description directly into the terminal",
    )
    parser.add_argument(
        "--company",
        default="",
        help="Target company name (used for context and default filename)",
    )
    parser.add_argument(
        "--role",
        default="",
        help="Target role/title (used for context and default filename)",
    )
    parser.add_argument(
        "--output",
        help="Output .tex file path (default: auto-named as {resume_base}_{company}_{role}.tex)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Groq model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--compile",
        action="store_true",
        help="Compile output .tex to PDF using latexmk, pdflatex, or xelatex",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Display a unified diff between original and tailored resume",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("GROQ_API_KEY"),
        help="API key (defaults to GROQ_API_KEY environment variable)",
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("GROQ_BASE_URL"),
        help="API base URL (defaults to GROQ_BASE_URL or https://api.groq.com/openai/v1/chat/completions)",
    )

    args = parser.parse_args()

    # Automatically activate paste mode if no job input was supplied
    if not args.job and not args.job_url and not args.paste:
        if sys.stdin.isatty():
            args.paste = True
        else:
            piped_input = sys.stdin.read().strip()
            if piped_input:
                args.job = piped_input
            else:
                args.paste = True

    # Validate API keys with smart shifting support
    keys = get_groq_api_keys()
    if args.api_key:
        if args.api_key in keys:
            keys.remove(args.api_key)
        keys.insert(0, args.api_key)

    if not keys:
        sys.exit("[error] No API key provided. Set GROQ_API_KEY in .env or pass --api-key.")

    # Validate resume file
    if not os.path.isfile(args.resume):
        sys.exit(f"[error] Master resume file not found: {args.resume}")

    try:
        with open(args.resume, "r", encoding="utf-8") as f:
            resume_tex = f.read()
    except OSError as e:
        sys.exit(f"[error] Failed to read resume file: {e}")

    # [1/4] Load Job Description
    print("[1/4] Loading job description...")
    try:
        job_description = load_job_description(args)
    except Exception as e:
        sys.exit(f"[error] Failed to load job description: {e}")

    if not job_description or len(job_description.strip()) < 30:
        sys.exit("[error] Job description is empty or too short (< 30 characters).")

    # [2/4] Call Groq API with Smart Shifting
    shift_info = f" [smart shifting active across {len(keys)} keys]" if len(keys) > 1 else ""
    print(f"[2/4] Sending to AI model ({args.model}) for tailoring{shift_info}...")
    user_prompt = build_user_prompt(resume_tex, job_description, args.company, args.role)
    system_prompt = get_tailor_system_prompt(resume_tex)
    try:
        raw_output = call_groq(system_prompt, user_prompt, args.model, keys, args.api_base)
    except Exception as e:
        sys.exit(f"[error] API call failed: {e}")

    # [3/4] Validate LaTeX output
    print("[3/4] Validating LaTeX output...")
    tailored_tex = sanitize_latex(extract_latex(raw_output))

    if not looks_like_latex(tailored_tex):
        sys.exit(
            "[error] Model output does not appear to be valid LaTeX. "
            "Aborting without writing any file.\n"
            "----- RAW MODEL OUTPUT (first 800 chars) -----\n"
            + raw_output[:800]
        )

    if not braces_balanced(tailored_tex):
        print(
            "[warn] Curly braces in generated LaTeX appear unbalanced. "
            "Writing file, but please review the LaTeX syntax carefully.",
            file=sys.stderr,
        )

    # Validate candidate facts and structural preservation
    val_errors = get_validation_errors(tailored_tex, resume_tex)
    if val_errors:
        print("\n[3/4] Validation warnings detected — retrying once with error feedback...", file=sys.stderr)
        for e in val_errors:
            print(f"  ⚠️  {e}", file=sys.stderr)
        retry_prompt = build_validation_retry_prompt(tailored_tex, val_errors)
        try:
            raw_retry = call_groq(system_prompt, retry_prompt, args.model, keys, args.api_base)
            retry_tex = sanitize_latex(extract_latex(raw_retry))
            if not looks_like_latex(retry_tex):
                sys.exit("[error] AI retry output did not contain valid LaTeX markup.")
            val_errors_retry = get_validation_errors(retry_tex, resume_tex)
            if val_errors_retry:
                print("\n[error] Validation failed again after retry:", file=sys.stderr)
                for e in val_errors_retry:
                    print(f"  ❌  {e}", file=sys.stderr)
                sys.exit(1)
            print("[3/4] Validation passed after retry correction!\n")
            tailored_tex = retry_tex
        except Exception as e:
            sys.exit(f"[error] Retry call failed: {e}")
    else:
        print("[3/4] LaTeX validation passed successfully.")

    # Determine output file path
    if args.output:
        out_path = args.output
    else:
        base_name = os.path.splitext(os.path.basename(args.resume))[0]
        tag_parts = [p.strip() for p in (args.company, args.role) if p.strip()]
        tag = "_".join(tag_parts).replace(" ", "_") if tag_parts else "tailored"
        # Sanitize filename
        tag = re.sub(r'[\\/*?:"<>|]', "_", tag)
        out_path = f"{base_name}_{tag}.tex"

    # Ensure target directory exists
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(tailored_tex)
    except OSError as e:
        sys.exit(f"[error] Failed to write tailored resume to '{out_path}': {e}")

    # [4/4] Output saved
    print(f"[4/4] Successfully saved tailored resume to: {out_path}\n")

    # Optional diff view
    if args.diff:
        print_diff(resume_tex, tailored_tex, args.resume, out_path)

    # Always output the tailored LaTeX code to stdout for easy copy-pasting (e.g. Overleaf)
    print("=" * 70)
    print("TAILORED LATEX SOURCE CODE (Ready to copy/paste):")
    print("=" * 70)
    print(tailored_tex)
    print("=" * 70 + "\n")

    # Optional compilation
    if args.compile:
        compile_pdf(out_path)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
generate_rubric.py — Generate AI-powered hiring rubrics from Manatal JDs.
date last updated: 6 March 2025
This script fetches a job description from Manatal using the provided JOB_ID, then prompts an OpenAI model (default gpt-4o) to 
generate a detailed JSON rubric for evaluating candidates against that JD. The rubric includes must-have and nice-to-have requirements, 
compliance gates, scoring guidelines, bias guardrails, and a semantic ontology of relevant terms.

Changes in this version:
Adds a full post-generation normalization pipeline — compliance deduplication, compliance-from-must-have removal, 
weight cap enforcement (20% max per must-have, 3% max per nice-to-have), drift correction to force exact 90/10 sums, 
legacy field stripping, and junk-term-filtered ontology backfilling — that programmatically fixes LLM output regardless of 
what the model returns. 
The prompt itself is also hardened against score inflation with granularity decomposition rules, specific bad/good examples 
for requirement splitting and evidence signals, and explicit instructions to never invent requirements beyond the JD text

Usage:
    python generate_rubric.py <JOB_ID>

Environment Variables:
    MANATAL_API_TOKEN   (required) — Manatal Open API token
    OPENAI_API_KEY      (required) — OpenAI API key
    OPENAI_MODEL        (optional) — defaults to gpt-4o

Output:
    ./rubrics/rubric_<job_id>.json
"""
import os
import sys
import json
import re
import textwrap
import datetime
from typing import Tuple, List, Dict, Any

from dotenv import load_dotenv
import requests

load_dotenv()

# ----------------------------
# CONFIG
# ----------------------------
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

MANATAL_API_KEY = os.getenv("MANATAL_API_TOKEN", "")
MANATAL_BASE_URL = "https://api.manatal.com/open/v3"
OUTPUT_DIR = os.getenv("RUBRIC_OUTPUT_DIR", "rubrics")

MAX_SINGLE_MUST_HAVE_WEIGHT = 20  # No single item should dominate scoring


# ----------------------------
# OpenAI client (minimal)
# ----------------------------
def call_openai(system_prompt: str, user_prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ----------------------------
# Manatal fetch
# ----------------------------
def fetch_job_from_manatal(job_id: str) -> Dict[str, Any]:
    if not MANATAL_BASE_URL:
        raise RuntimeError("MANATAL_BASE_URL not set")
    if not MANATAL_API_KEY:
        raise RuntimeError("MANATAL_API_TOKEN not set")

    url = f"{MANATAL_BASE_URL}/jobs/{job_id}"
    headers = {
        "Authorization": f"Token {MANATAL_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


def extract_jd_text(job_payload: Dict[str, Any]) -> str:
    candidates = [
        job_payload.get("description"),
        job_payload.get("job_description"),
        job_payload.get("content"),
        job_payload.get("details"),
    ]
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return json.dumps(job_payload, indent=2, ensure_ascii=False)


def extract_job_title(job: dict) -> str:
    if isinstance(job.get("data"), dict):
        data = job["data"]
        return data.get("position_name") or data.get("title") or data.get("name") or "Unknown Title"
    if isinstance(job.get("results"), list) and job["results"]:
        first = job["results"][0]
        return first.get("position_name") or first.get("title") or first.get("name") or "Unknown Title"
    return job.get("position_name") or job.get("title") or job.get("name") or "Unknown Title"


# ----------------------------
# Prompt
# ----------------------------
SYSTEM_PROMPT = """You are a strict, calibrated recruiting rubric generator.
You create granular, specific rubrics that prevent score inflation.
You decompose broad JD requirements into specific, independently scoreable sub-skills.
You NEVER invent requirements not grounded in the JD text.
You assign weights directly based on the relative importance from the JD.
No single must-have should exceed 20% weight. No single nice-to-have should exceed 3%.
Return ONLY valid JSON, no markdown, no commentary.
"""


def build_json_prompt(jd_context: str, job_id: str) -> str:
    today = datetime.date.today().strftime("%Y-%m-%d")
    return textwrap.dedent(f"""\
Generate a complete, valid JSON rubric for the following job description.

CRITICAL JSON FORMAT REQUIREMENTS:
1. Output MUST be valid JSON — no markdown fences, no extra text
2. Start with {{ and end with }}
3. Must-have weights MUST total exactly 90
4. Nice-to-have weights MUST total exactly 10
5. Today's date: {today}
6. Job ID: {job_id}
7. Education: If a degree is REQUIRED/MANDATORY, put it ONLY in compliance_requirements (NOT in must-have).
8. Do NOT include work authorization/visa/citizenship unless explicitly stated in the JD.
9. Education, Work Authorization, and Years of Experience are compliance_requirements ONLY if explicitly in the JD.
10. Seniority level: infer from years of experience in JD, or default to "mid".

REQUIREMENT GRANULARITY RULES (critical for scoring accuracy):
- Decompose broad JD requirements into specific, independently scoreable sub-skills.
- Most JD bullets contain 2-3 scoreable sub-skills. Split them.
- DO NOT invent requirements not grounded in the JD. Every item must trace back to something in the JD.
  Example: JD says "Strong consultative selling and business development skills"
    BAD: Keep as one item at 40% weight
    GOOD: Decompose into:
      - "B2B sales experience selling technology, SaaS, or recruitment services" (18%)
      - "Consultative solution selling translating business problems into solutions" (15%)
      - "Pipeline generation and deal closing across the full sales lifecycle" (12%)
- NO single must-have weight should exceed {MAX_SINGLE_MUST_HAVE_WEIGHT}%. If it would, split the item.
- NO single nice-to-have weight should exceed 3%.
- Each requirement must be specific enough that a CV either clearly demonstrates it or doesn't.
  BAD: "Strong communication skills" (too vague — every candidate gets 5/5)
  GOOD: "Led contract negotiations or delivered sales presentations to decision-makers"
- When writing "experience selling X" requirements, be PRECISE about what X is:
  BAD: "Experience selling HRTech, SaaS, or digital transformation solutions" (too broad — LLM confuses selling recruitment services with selling HRTech software)
  GOOD: "Experience selling HRTech software platforms, SaaS subscription products, or digital transformation technology solutions" (clearly means selling technology, not services)
- evidence_signals: 2-3 SPECIFIC, VERIFIABLE indicators (not generic traits)
  BAD: "Good communication skills"
  GOOD: "Conducted solution demos or presentations to C-level stakeholders"
- negative_signals: 1-2 SPECIFIC anti-patterns (not just "lack of X")
  BAD: "No business development achievements"
  GOOD: "Only transactional product selling with no discovery or consultative approach"

SEMANTIC ONTOLOGY RULES:
- normalized_terms must contain ONLY domain-relevant terms from THIS JD
- NEVER include generic filler words like "Ability", "Awards", "Business", "CRITICAL", "Case", "Bachelors"
- Include: specific skills, tools, platforms, methodologies, industry terms, job-specific concepts
- Minimum 15 terms for non-technical roles, 30+ for technical roles

REQUIRED JSON STRUCTURE:
{{
  "job_id": "{job_id}",
  "role": "Full Job Title",
  "company": "Company Name",
  "seniority_level": "junior|mid|senior|lead",
  "rubric_name": "PositionName_YYYYMMDD",
  "rubric_version": "2.3",
  "generated_date": "{today}",
  "jd": {{
    "jd_summary": "One sentence summary (max 150 words)",
    "core_responsibilities": ["resp1", "resp2", "...all key responsibilities from JD"],
    "must_haves_from_jd": ["req1", "req2", "...all must-haves from JD verbatim"],
    "nice_to_haves_from_jd": ["skill1", "skill2", "...all nice-to-haves from JD verbatim"]
  }},
  "compliance_requirements": ["Degree requirement if mandatory", "Years of experience if stated", "Work auth if stated"],
  "scoring": {{
    "scale": {{"0":"Not demonstrated","1":"Mentioned only","2":"Basic exposure","3":"Hands-on experience","4":"Advanced practical expertise","5":"Expert level with leadership"}},
    "calculation": "Weighted average",
    "floor_rule": "Any must-have < 2 triggers FAIL",
    "weighting": {{"must_have_total_weight_percent": 90, "nice_to_have_total_weight_percent": 10}}
  }},
  "requirements": {{
    "must_have": [
      {{
        "id": "MH1",
        "requirement": "Specific, independently scoreable requirement",
        "weight": 18,
        "evidence_signals": ["specific verifiable signal1", "specific verifiable signal2"],
        "negative_signals": ["specific anti-pattern1", "specific anti-pattern2"],
        "implementation_note": null
      }}
    ],
    "nice_to_have": [
      {{
        "id": "NH1",
        "skill": "Specific bonus skill",
        "weight": 3
      }}
    ]
  }},
  "bias_guardrails": {{
    "protected_attributes": ["age","gender","race","ethnicity","religion","marital_status","disability"],
    "enforcement": "Strip protected attributes prior to scoring"
  }},
  "semantic_ontology": {{
    "normalized_terms": ["...ONLY domain-relevant terms — NEVER generic words..."],
    "semantic_threshold_defaults": {{
      "highest_confidence": 0.9,
      "high_confidence": 0.88,
      "medium_confidence": 0.86,
      "min_acceptable": 0.85
    }}
  }},
  "report_format": {{
    "length_target": "1-2 pages",
    "output_language": "English",
    "sections": [
      "Role fit summary (overall score and hire/no-hire recommendation)",
      "Must-have requirements score breakdown (with evidence quotes/snippets from CV)",
      "Nice-to-have signals",
      "Gaps and risks (what is missing or unclear)",
      "Suggested interview questions to validate gaps",
      "Implementation notes / context (if any scoring relaxations apply)"
    ],
    "output_constraints": [
      "Do not consider or mention protected attributes.",
      "Every score claim must be supported by explicit CV evidence; otherwise mark as 'Not demonstrated'.",
      "Keep output within 1-2 pages; use bullet points and concise justification.",
      "If any must-have scores below 2, mark overall result as FAIL regardless of weighted score."
    ]
  }},
  "assumptions": ["assumption1", "assumption2"]
}}

AUTO-GENERATION RULES:
- Assign weights directly based on relative importance from the JD. Higher-impact skills get more weight.
- evidence_signals: 2-3 SPECIFIC, VERIFIABLE indicators per requirement
- negative_signals: 1-2 SPECIFIC anti-patterns per requirement
- implementation_note: null unless JD mentions flexibility/alternatives
- WEIGHT CAPS: No single must-have > {MAX_SINGLE_MUST_HAVE_WEIGHT}%. No single nice-to-have > 3%.
- Broad requirements produce inflated scores. Decompose them into specific sub-skills grounded in the JD.

JOB DESCRIPTION:
{jd_context}

Output ONLY valid JSON. No extra text.
""")


# ----------------------------
# Cleaning
# ----------------------------
def clean_response(text: str) -> str:
    t = (text or "").strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return t
    return t[start:end + 1].strip()


# ----------------------------
# Compliance sanitizer
# ----------------------------
def remove_compliance_from_must_have(rubric: dict) -> None:
    """
    Remove compliance-style gate requirements from must_have,
    preventing double-counting (compliance + scored must-have).
    """
    compliance = rubric.get("compliance_requirements", [])
    reqs = rubric.get("requirements", {})
    mh = reqs.get("must_have", [])

    if not isinstance(compliance, list) or not isinstance(mh, list):
        return

    compliance_text = " | ".join(str(x).lower() for x in compliance)

    years_patterns = [
        r"\b\d+\s*\+?\s*years\b",
        r"\b\d+\s*-\s*\d+\s*years\b",
        r"\bminimum\s+\d+\s*years\b",
        r"\bat least\s+\d+\s*years\b",
        r"\byears of experience\b",
    ]
    edu_keywords = ["bachelor", "master", "phd", "degree", "education"]
    auth_keywords = ["work authorization", "work permit", "visa", "citizen", "citizenship", "legal right to work"]

    def looks_like_gate(text: str) -> bool:
        t = text.lower()
        if any(re.search(p, t) for p in years_patterns):
            return True
        if any(k in t for k in edu_keywords):
            return True
        if any(k in t for k in auth_keywords):
            return True
        return False

    def overlaps_compliance(text: str) -> bool:
        t = text.lower()
        tokens = set(re.findall(r"[a-zA-Z]+", t))
        return any(tok in compliance_text for tok in tokens)

    cleaned = []
    removed = 0
    for item in mh:
        if not isinstance(item, dict):
            cleaned.append(item)
            continue
        req_text = str(item.get("requirement", "") or "")
        if looks_like_gate(req_text) and overlaps_compliance(req_text):
            removed += 1
            continue
        cleaned.append(item)

    rubric.setdefault("requirements", {})["must_have"] = cleaned
    if removed:
        print(f"  🧹 Removed {removed} compliance-style must-have item(s).")


# ----------------------------
# Weight normalization (simple)
# ----------------------------
def normalize_must_have_weights(mh: List[Dict[str, Any]]) -> None:
    """
    Ensure must-have weights sum to exactly 90 and no single item exceeds the cap.
    Preserves the LLM's relative ordering — only adjusts for drift.
    """
    if not mh:
        return

    for item in mh:
        w = item.get("weight")
        if not isinstance(w, (int, float)) or w <= 0:
            item["weight"] = 90 // len(mh)
        else:
            item["weight"] = int(w)

    # Cap any item that exceeds max
    for item in mh:
        if item["weight"] > MAX_SINGLE_MUST_HAVE_WEIGHT:
            item["weight"] = MAX_SINGLE_MUST_HAVE_WEIGHT

    # Fix drift to sum to exactly 90
    total = sum(item["weight"] for item in mh)
    drift = 90 - total
    max_iters = len(mh) * 100  # safety limit

    if drift > 0:
        items_sorted = sorted(mh, key=lambda x: x["weight"])
        i = 0
        iters = 0
        while drift > 0 and iters < max_iters:
            if items_sorted[i]["weight"] < MAX_SINGLE_MUST_HAVE_WEIGHT:
                items_sorted[i]["weight"] += 1
                drift -= 1
            i = (i + 1) % len(mh)
            iters += 1
    elif drift < 0:
        items_sorted = sorted(mh, key=lambda x: x["weight"], reverse=True)
        i = 0
        iters = 0
        while drift < 0 and iters < max_iters:
            if items_sorted[i]["weight"] > 1:
                items_sorted[i]["weight"] -= 1
                drift += 1
            i = (i + 1) % len(mh)
            iters += 1


def normalize_nice_to_have_weights(nh: List[Dict[str, Any]]) -> None:
    """Ensure nice-to-have weights sum to exactly 10, no item > 3."""
    if not nh:
        return

    for item in nh:
        w = item.get("weight")
        if not isinstance(w, (int, float)) or w <= 0:
            item["weight"] = 10 // len(nh)
        else:
            item["weight"] = int(w)

    for item in nh:
        if item["weight"] > 3:
            item["weight"] = 3

    total = sum(item["weight"] for item in nh)
    drift = 10 - total
    max_iters = len(nh) * 100

    if drift > 0:
        items_sorted = sorted(nh, key=lambda x: x["weight"])
        i = 0
        iters = 0
        while drift > 0 and iters < max_iters:
            if items_sorted[i]["weight"] < 3:
                items_sorted[i]["weight"] += 1
                drift -= 1
            i = (i + 1) % len(nh)
            iters += 1
    elif drift < 0:
        items_sorted = sorted(nh, key=lambda x: x["weight"], reverse=True)
        i = 0
        iters = 0
        while drift < 0 and iters < max_iters:
            if items_sorted[i]["weight"] > 1:
                items_sorted[i]["weight"] -= 1
                drift += 1
            i = (i + 1) % len(nh)
            iters += 1


# ----------------------------
# Ensure experience in compliance
# ----------------------------
def ensure_experience_in_compliance(rubric: dict) -> None:
    comp = rubric.setdefault("compliance_requirements", [])
    if not isinstance(comp, list):
        comp = []
        rubric["compliance_requirements"] = comp

    jd = rubric.get("jd", {}) or {}
    mh_from_jd = jd.get("must_haves_from_jd", []) or []
    if not isinstance(mh_from_jd, list):
        return

    years_patterns = [
        r"\b\d+\s*(?:to|-)\s*\d+\s*years\b",
        r"\b\d+\s*\+?\s*years\b",
        r"\bminimum\s+\d+\s*years\b",
        r"\bat least\s+\d+\s*years\b",
        r"\byears of experience\b",
    ]

    # Find the most detailed YoE line from JD
    yoe_line = None
    for s in mh_from_jd:
        if not isinstance(s, str):
            continue
        t = s.strip()
        if any(re.search(p, t.lower()) for p in years_patterns):
            # Keep the longest (most detailed) match
            if yoe_line is None or len(t) > len(yoe_line):
                yoe_line = t

    if not yoe_line:
        return

    # Remove any existing shorter YoE entries (dedupe)
    cleaned_comp = []
    replaced = False
    for item in comp:
        item_str = str(item).lower()
        if any(re.search(p, item_str) for p in years_patterns):
            if not replaced:
                # Replace first YoE entry with the most detailed version
                cleaned_comp.append(yoe_line)
                replaced = True
            # Skip duplicate YoE entries
            continue
        cleaned_comp.append(item)

    # If no existing YoE was found, add it
    if not replaced:
        cleaned_comp.append(yoe_line)

    rubric["compliance_requirements"] = cleaned_comp


# ----------------------------
# Backfill normalized terms
# ----------------------------
def backfill_normalized_terms(rubric: dict, min_terms: int = 15) -> None:
    so = rubric.setdefault("semantic_ontology", {})
    terms = so.get("normalized_terms") or []
    if not isinstance(terms, list):
        terms = []

    JUNK_TERMS = {
        "ability", "awards", "business", "critical", "case", "bachelors",
        "important", "foundational", "description", "requirement", "signal",
        "experience", "knowledge", "strong", "excellent", "proven",
        "demonstrated", "skills", "high", "medium", "low", "null",
        "true", "false", "note", "implementation", "weight", "priority",
    }

    seen = set()
    cleaned = []
    for t in terms:
        if not isinstance(t, str):
            continue
        tt = t.strip()
        if not tt:
            continue
        key = tt.lower()
        if key in seen or key in JUNK_TERMS:
            continue
        seen.add(key)
        cleaned.append(tt)

    candidates = []

    def add_text(x):
        if isinstance(x, str):
            candidates.append(x)
        elif isinstance(x, list):
            for v in x:
                add_text(v)
        elif isinstance(x, dict):
            for v in x.values():
                add_text(v)

    add_text(rubric.get("jd", {}))
    add_text(rubric.get("requirements", {}))

    tech_tokens = set()
    for blob in candidates:
        for m in re.findall(r"\b[A-Za-z][A-Za-z0-9\.\+#/-]{1,}\b", blob):
            if len(m) < 2:
                continue
            if m.lower() in {"and", "or", "with", "using", "build", "develop", "experience", "knowledge", "strong"}:
                continue
            if m.lower() in JUNK_TERMS:
                continue
            tech_tokens.add(m)

    for tok in sorted(tech_tokens):
        key = tok.lower()
        if key not in seen:
            cleaned.append(tok)
            seen.add(key)
        if len(cleaned) >= min_terms:
            break

    so["normalized_terms"] = cleaned


# ----------------------------
# Strip legacy fields
# ----------------------------
def strip_legacy_fields(rubric: dict) -> None:
    """Remove importance_tier and priority from must-have items if LLM included them."""
    mh = rubric.get("requirements", {}).get("must_have", [])
    for item in mh:
        item.pop("importance_tier", None)
        item.pop("priority", None)

    # Remove pass_threshold from scoring (now lives in config.py of the scoring pipeline)
    scoring = rubric.get("scoring", {})
    scoring.pop("pass_threshold", None)


# ----------------------------
# Normalization
# ----------------------------
def normalize_json_rubric(content: str) -> str:
    try:
        rubric = json.loads(content)
    except Exception:
        return content

    reqs = rubric.setdefault("requirements", {})
    if not isinstance(reqs.get("must_have"), list):
        reqs["must_have"] = []
    if not isinstance(reqs.get("nice_to_have"), list):
        reqs["nice_to_have"] = []

    print("  📋 Ensuring experience in compliance...")
    ensure_experience_in_compliance(rubric)
    print("  🧹 Removing compliance from must-have...")
    remove_compliance_from_must_have(rubric)

    mh = rubric.get("requirements", {}).get("must_have", [])
    nh = rubric.get("requirements", {}).get("nice_to_have", [])

    print(f"  ⚖️  Normalizing must-have weights ({len(mh)} items)...")
    normalize_must_have_weights(mh)
    print(f"  ⚖️  Normalizing nice-to-have weights ({len(nh)} items)...")
    normalize_nice_to_have_weights(nh)

    print("  🧽 Stripping legacy fields...")
    strip_legacy_fields(rubric)
    print("  📚 Backfilling ontology terms...")
    backfill_normalized_terms(rubric, min_terms=15)

    print("  ✅ Normalization complete")
    return json.dumps(rubric, indent=2, ensure_ascii=False)


# ----------------------------
# Validation
# ----------------------------
def validate_json_rubric(content: str) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    try:
        rubric = json.loads(content)
    except json.JSONDecodeError as e:
        return False, [f"INVALID_JSON_PARSE: {e.msg} at line {e.lineno} col {e.colno}"]

    REQUIRED_TOP = [
        "job_id", "role", "company", "seniority_level", "rubric_name",
        "rubric_version", "generated_date", "jd", "compliance_requirements",
        "scoring", "requirements", "bias_guardrails", "semantic_ontology",
        "report_format", "assumptions",
    ]
    for k in REQUIRED_TOP:
        if k not in rubric:
            errors.append(f"MISSING_TOP_LEVEL_KEY: {k}")

    if errors:
        return False, errors

    reqs = rubric["requirements"]
    mh = reqs.get("must_have", [])
    nh = reqs.get("nice_to_have", [])

    if not isinstance(mh, list) or len(mh) == 0:
        errors.append("requirements.must_have must be a non-empty list")
        return False, errors

    if not isinstance(nh, list):
        errors.append("requirements.nice_to_have must be a list")
        return False, errors

    # Validate must-have items
    mh_total = 0
    for i, it in enumerate(mh):
        for k in ["id", "requirement", "weight", "evidence_signals", "negative_signals"]:
            if k not in it:
                errors.append(f"must_have[{i}] missing key: {k}")
        w = it.get("weight")
        if not isinstance(w, (int, float)):
            errors.append(f"must_have[{i}].weight must be numeric")
        else:
            mh_total += int(w)
            if int(w) > MAX_SINGLE_MUST_HAVE_WEIGHT:
                errors.append(f"must_have[{i}].weight is {int(w)}% — exceeds max {MAX_SINGLE_MUST_HAVE_WEIGHT}%")

        ev = it.get("evidence_signals")
        neg = it.get("negative_signals")
        if not isinstance(ev, list) or not (2 <= len(ev) <= 3):
            errors.append(f"must_have[{i}] evidence_signals must be 2-3 items")
        if not isinstance(neg, list) or not (1 <= len(neg) <= 2):
            errors.append(f"must_have[{i}] negative_signals must be 1-2 items")

    # Validate nice-to-have items
    nh_total = 0
    for i, it in enumerate(nh):
        for k in ["id", "skill", "weight"]:
            if k not in it:
                errors.append(f"nice_to_have[{i}] missing key: {k}")
        w = it.get("weight")
        if not isinstance(w, (int, float)):
            errors.append(f"nice_to_have[{i}].weight must be numeric")
        else:
            nh_total += int(w)
            if int(w) > 3:
                errors.append(f"nice_to_have[{i}].weight is {int(w)}% — exceeds max 3%")

    if mh_total != 90:
        errors.append(f"must_have total weight must equal 90 (got {mh_total})")
    if nh_total != 10:
        errors.append(f"nice_to_have total weight must equal 10 (got {nh_total})")

    # Semantic ontology
    ont = rubric.get("semantic_ontology", {})
    nt = ont.get("normalized_terms")
    if not isinstance(nt, list) or len(nt) < 15:
        errors.append("semantic_ontology.normalized_terms must have 15+ terms")

    th = ont.get("semantic_threshold_defaults")
    if not isinstance(th, dict):
        errors.append("semantic_ontology.semantic_threshold_defaults missing")
    else:
        for k in ["highest_confidence", "high_confidence", "medium_confidence", "min_acceptable"]:
            if k not in th:
                errors.append(f"semantic_threshold_defaults missing '{k}'")

    # Report format
    rf = rubric.get("report_format", {})
    for k in ["length_target", "output_language", "sections", "output_constraints"]:
        if k not in rf:
            errors.append(f"report_format missing '{k}'")

    return (len(errors) == 0), errors


# ----------------------------
# Retry loop
# ----------------------------
def generate_with_retry(system_prompt: str, prompt: str, max_retries: int = 2) -> str:
    last = ""
    for attempt in range(1, max_retries + 1):
        print(f"🤖 Calling OpenAI ({OPENAI_MODEL}) attempt {attempt}/{max_retries}...")
        raw = call_openai(system_prompt, prompt)
        print(f"📥 Response received ({len(raw)} chars). Normalizing...")
        cleaned = clean_response(raw)
        normalized = normalize_json_rubric(cleaned)

        valid, errs = validate_json_rubric(normalized)
        if valid:
            print(f"✅ Validation PASSED on attempt {attempt}")
            return normalized

        print(f"❌ Validation FAILED ({len(errs)} error(s)):")
        for e in errs[:12]:
            print(f"   • {e}")

        last = normalized

        prompt = prompt + "\n\n" + textwrap.dedent(f"""\
        RETRY FIX INSTRUCTIONS:
        - Output ONLY valid JSON.
        - NO single must-have weight can exceed {MAX_SINGLE_MUST_HAVE_WEIGHT}%. Decompose broad items.
        - Nice-to-have: no single weight > 3%.
        - Do NOT include gates (degree, years, work auth) in must_have — compliance_requirements only.
        - Do NOT invent requirements not in the JD.
        - Ontology: domain-specific terms from THIS JD only — no generic filler words.
        """)

    print("⚠️ Returning best-effort output after retries. Manual review recommended.")
    return last


# ----------------------------
# CLI / main
# ----------------------------
def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python generate_rubric.py <JOB_ID>")
        return 2

    job_id = sys.argv[1]

    print("=" * 70)
    print(f"  RUBRIC GENERATOR — Job {job_id} → JSON")
    print("=" * 70)

    print(f"📡 Fetching job {job_id} from Manatal...")
    job = fetch_job_from_manatal(job_id)

    title = extract_job_title(job)
    print(f"✅ Found: {title} (ID: {job_id})")

    jd_text = extract_jd_text(job)
    print(f"📄 JD extracted ({len(jd_text)} chars)")

    prompt = build_json_prompt(jd_text, job_id)
    rubric_json = generate_with_retry(SYSTEM_PROMPT, prompt, max_retries=2)

    # Save
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"rubric_{job_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(rubric_json)

    print("\n" + "=" * 70)
    print(f"✅ RUBRIC SAVED: {out_path}")
    print("=" * 70)

    # Summary
    try:
        r = json.loads(rubric_json)
        mh = r.get("requirements", {}).get("must_have", [])
        nh = r.get("requirements", {}).get("nice_to_have", [])
        max_w = max((x.get("weight", 0) for x in mh), default=0)
        print(f"Role:             {r.get('role')}")
        print(f"Seniority:        {r.get('seniority_level')}")
        print(f"Compliance items: {len(r.get('compliance_requirements', []))}")
        print(f"Must-have:        {len(mh)} items (total: {sum(x.get('weight', 0) for x in mh)}%, max single: {max_w}%)")
        print(f"Nice-to-have:     {len(nh)} items (total: {sum(x.get('weight', 0) for x in nh)}%)")
        print(f"Ontology terms:   {len(r.get('semantic_ontology', {}).get('normalized_terms', []))}")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

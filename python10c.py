#!/usr/bin/env python3
# python10c.py - Two-Tier Scoring with Direct Airtable Integration
# Tier 1: Fast screening with gpt-4o-mini (simple score)
# Tier 2: Detailed evaluation with gpt-4o-mini (full breakdown)

from __future__ import annotations
from dotenv import load_dotenv

import csv
import json
import os
import re
import sys
import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from pypdf import PdfReader
import docx
from openai import OpenAI
from pyairtable import Api

load_dotenv()

# =========================
# CONFIG (edit here)
# =========================

# Two-Tier Configuration
TIER1_MODEL = "gpt-4o-mini"          # Fast screening
TIER2_MODEL = "gpt-4o-mini"          # Detailed evaluation (change to "gpt-4o" for better quality)
TIER1_PASS_THRESHOLD = 65            # Candidates >= 65 proceed to Tier 2

# Cost reference (per 1M tokens):
# gpt-4o-mini: $0.15 input / $0.60 output (cheap, fast)
# gpt-4o: $2.50 input / $10.00 output (expensive, best quality)

# Job selection
TARGET_STAGE_NAME = "Processing"
PAGE_SIZE = 100

# Paths
EXPORT_PATH = "/Users/subrasuppiah/Desktop/manatal"
RUBRIC_DIR = "/Users/subrasuppiah/Desktop/manatal/rubrics"
CACHE_FILE = "/Users/subrasuppiah/Desktop/manatal/scored_cache.json"

# Behavior
SKIP_ALREADY_SCORED = True
FORCE_RESCORE = False
DOWNLOAD_RESUMES = True

# Limits
MAX_RESUME_CHARS = 30_000
MAX_RUBRIC_CHARS = 50_000

# Airtable
WRITE_TO_AIRTABLE = True            # Set False to disable Airtable writes
AIRTABLE_BATCH_SIZE = 10            # Write 10 records at a time
AIRTABLE_RETRY_ATTEMPTS = 3         # Retry failed writes 3 times

# CSV Backup
WRITE_CSV_BACKUP = True             # Keep CSV backup (set False to disable)

BASE_URL = "https://api.manatal.com/open/v3"

# =========================
# Secrets (from .env)
# =========================
MANATAL_API_TOKEN = os.getenv('MANATAL_API_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
AIRTABLE_TOKEN = os.getenv('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = os.getenv('AIRTABLE_BASE_ID')
AIRTABLE_TABLE_ID = os.getenv('AIRTABLE_TABLE_ID')

# =========================
# Utility helpers
# =========================
def sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()

def safe_filename(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\-. ]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:180] if s else "export"

def clip(s: str, n: int) -> str:
    s = s or ""
    return s[:n]

# =========================
# Rubric + cache
# =========================
def load_rubric_json(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Rubric JSON not found: {p}")
    rubric_text = p.read_text(encoding="utf-8", errors="ignore")
    rubric_text = rubric_text[:MAX_RUBRIC_CHARS]
    return json.loads(rubric_text)

def rubric_compact_json(rubric: dict) -> str:
    return json.dumps(rubric, ensure_ascii=False, separators=(",", ":"))

def load_cache(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_cache(path: str, data: dict) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# =========================
# HTTP helpers
# =========================
def manatal_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Token {MANATAL_API_TOKEN}",
        "accept": "application/json",
    }

def api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, headers=manatal_headers(), params=params, timeout=60)
    if not resp.ok:
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        raise RuntimeError(f"GET {url} failed: {resp.status_code}\n{body}")
    return resp.json()

def fetch_all_paginated(path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    next_path = path
    next_params = dict(params or {})
    next_params.setdefault("page_size", PAGE_SIZE)

    while True:
        data = api_get(next_path, params=next_params)

        if isinstance(data, list):
            items.extend(data)
            break

        if isinstance(data, dict) and "results" in data:
            items.extend(data.get("results") or [])
            nxt = data.get("next")
            if not nxt:
                break

            m = re.search(r"https?://[^/]+(/open/v3/.*)$", str(nxt))
            if not m:
                raise RuntimeError(f"Pagination 'next' not recognized: {nxt}")
            rel = m.group(1).replace("/open/v3", "")
            next_path = rel
            next_params = {}
            continue

        raise RuntimeError(f"Unexpected response shape for {path}: {data}")

    return items

# =========================
# Extraction helpers
# =========================
def extract_stage_name(match: Dict[str, Any]) -> Optional[str]:
    for key in ("job_pipeline_stage", "stage"):
        v = match.get(key)
        if isinstance(v, dict) and v.get("name"):
            return str(v["name"])
    return None

def extract_candidate_id(match: Dict[str, Any]) -> Optional[int]:
    v = match.get("candidate")
    if isinstance(v, int):
        return v
    if isinstance(v, dict) and isinstance(v.get("id"), int):
        return v["id"]
    return None

def get_job_and_org(job_id: str) -> Tuple[Dict[str, Any], str, Optional[int], Optional[str], str]:
    job = api_get(f"/jobs/{job_id}/")
    job_name = (
        job.get("position_name")
        or job.get("name")
        or job.get("title")
        or f"job_{job_id}"
    )

    org_id: Optional[int] = None
    org_name: Optional[str] = None
    org = job.get("organization")

    if isinstance(org, dict):
        if isinstance(org.get("id"), int):
            org_id = org["id"]
        if org.get("name"):
            org_name = str(org["name"])
    elif isinstance(org, int):
        org_id = org
        try:
            org_obj = api_get(f"/organizations/{org_id}/")
            if isinstance(org_obj, dict) and org_obj.get("name"):
                org_name = str(org_obj["name"])
        except Exception:
            org_name = None

    org_name = org_name or job.get("organization_name") or job.get("client_name")
    jd_text = (
        job.get("job_description")
        or job.get("description")
        or job.get("details")
        or ""
    )

    return job, str(job_name), org_id, org_name, str(jd_text or "")

def maybe_fill_org_from_match(
    match: Dict[str, Any],
    org_id: Optional[int],
    org_name: Optional[str]
) -> Tuple[Optional[int], Optional[str]]:
    if org_name:
        return org_id, org_name
    mo = match.get("organization")
    if isinstance(mo, dict):
        if isinstance(mo.get("id"), int) and not org_id:
            org_id = mo["id"]
        if mo.get("name") and not org_name:
            org_name = str(mo["name"])
    return org_id, org_name

def extract_resume_url_from_candidate(candidate: Dict[str, Any]) -> Optional[str]:
    for k in ("resume_file", "resume_url", "resume", "cv_url", "cv_file", "cv"):
        v = candidate.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    res = candidate.get("resume")
    if isinstance(res, dict):
        for kk in ("resume_file", "url", "file"):
            v = res.get(kk)
            if isinstance(v, str) and v.startswith("http"):
                return v
    return None

def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=90)
    if not resp.ok:
        raise RuntimeError(f"Download failed: {resp.status_code}")
    dest.write_bytes(resp.content)

def resume_text_from_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""
    elif ext in (".docx", ".doc"):
        try:
            doc = docx.Document(str(path))
            return "\n".join(para.text for para in doc.paragraphs)
        except Exception:
            return ""
    elif ext == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""

# =========================
# Airtable Integration
# =========================
class AirtableManager:
    def __init__(self):
        if not WRITE_TO_AIRTABLE:
            self.table = None
            return
            
        if not AIRTABLE_TOKEN:
            raise ValueError("AIRTABLE_TOKEN not found in .env")
        if not AIRTABLE_BASE_ID:
            raise ValueError("AIRTABLE_BASE_ID not found in .env")
        if not AIRTABLE_TABLE_ID:
            raise ValueError("AIRTABLE_TABLE_ID not found in .env")
            
        api = Api(AIRTABLE_TOKEN)
        self.table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID)
        self.batch_buffer = []
        
    def create_or_update_record(self, record_data: Dict[str, Any]) -> bool:
        """Add record to batch buffer. Returns True if successful."""
        if not WRITE_TO_AIRTABLE:
            return True
            
        self.batch_buffer.append(record_data)
        
        if len(self.batch_buffer) >= AIRTABLE_BATCH_SIZE:
            return self.flush_batch()
        return True
    
    def flush_batch(self) -> bool:
        """Write batch to Airtable with retry logic."""
        if not WRITE_TO_AIRTABLE or not self.batch_buffer:
            return True
            
        for attempt in range(AIRTABLE_RETRY_ATTEMPTS):
            try:
                # Upsert based on candidate_id + job_id combination
                for record in self.batch_buffer:
                    candidate_id = record.get("candidate_id")
                    job_id = record.get("job_id")
                    
                    # Search for existing record
                    formula = f"AND({{candidate_id}}={candidate_id}, {{job_id}}={job_id})"
                    existing = self.table.all(formula=formula)
                    
                    if existing:
                        # Update existing record
                        self.table.update(existing[0]["id"], record)
                    else:
                        # Create new record
                        self.table.create(record)
                
                self.batch_buffer = []
                time.sleep(0.2)  # Rate limiting: 5 req/sec
                return True
                
            except Exception as e:
                if attempt == AIRTABLE_RETRY_ATTEMPTS - 1:
                    print(f"  ❌ Airtable batch write failed after {AIRTABLE_RETRY_ATTEMPTS} attempts: {e}")
                    self.batch_buffer = []
                    return False
                time.sleep(1)  # Wait before retry
        return False

# =========================
# Tier 1: Fast Screening
# =========================
def tier1_screen(
    oa: OpenAI,
    rubric_json: str,
    resume_text: str
) -> int:
    """
    Tier 1: Quick screening with simple 0-100 score.
    Returns just a number for fast filtering.
    """
    prompt = f"""Score this resume against the rubric below. Return ONLY a number from 0-100. No explanation, no JSON, just the number.

RUBRIC:
{rubric_json}

RESUME:
{clip(resume_text, MAX_RESUME_CHARS)}

Score (0-100):""".strip()

    try:
        r = oa.chat.completions.create(
            model=TIER1_MODEL,
            messages=[
                {"role": "system", "content": "Return only a number 0-100. Nothing else."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=10
        )
        
        text = (r.choices[0].message.content or "").strip()
        # Extract first number found
        match = re.search(r'\d+', text)
        if match:
            score = int(match.group())
            return min(max(score, 0), 100)  # Clamp to 0-100
        return 0
        
    except Exception as e:
        print(f"  ⚠️  Tier 1 screening error: {e}")
        return 0

# =========================
# HTML Report Generation
# =========================

def generate_html_report(
    candidate_name: str,
    job_name: str,
    overall_score: float,
    detailed_json: dict,
    submission_date: str = None
) -> str:
    """
    Generate professional HTML report matching the design template.
    Returns HTML string for ai_report_html field.
    """
    from datetime import datetime
    
    # Use current date if not provided
    if not submission_date:
        submission_date = datetime.now().strftime("%B %d, %Y")
    
    # Parse detailed JSON
    compliance = detailed_json.get("compliance", [])
    must_have = detailed_json.get("must_have", [])
    nice_to_have = detailed_json.get("nice_to_have", [])
    ai_summary = detailed_json.get("ai_summary", "")
    ai_strengths = detailed_json.get("ai_strengths", "")
    ai_gaps = detailed_json.get("ai_gaps", "")
    recommendation = detailed_json.get("recommendation", "REVIEW")
    floor_triggered = detailed_json.get("floor_triggered", False)
    
    # Determine badge color based on recommendation
    if recommendation == "PASS":
        badge_color = "#16a34a"  # Green
        badge_text = "PASS"
    elif recommendation == "FAIL":
        badge_color = "#dc2626"  # Red
        badge_text = "FAIL"
    else:
        badge_color = "#ea580c"  # Orange
        badge_text = "REVIEW"
    
    # Score color coding function
    def get_score_color(score: int) -> str:
        if score >= 5: return "#15803d"  # Dark green
        elif score >= 4: return "#16a34a"  # Green
        elif score >= 3: return "#ea580c"  # Orange
        elif score >= 2: return "#dc2626"  # Red
        else: return "#991b1b"  # Dark red
    
    # Generate skill tags from ai_strengths
    strength_tags = []
    if ai_strengths:
        # Split by comma and take first 5
        strengths_list = [s.strip() for s in ai_strengths.split(",")]
        strength_tags = strengths_list[:5]
    
    # Generate gap badges from ai_gaps
    gap_badges = []
    if ai_gaps:
        gaps_list = [g.strip() for g in ai_gaps.split(",")]
        gap_badges = gaps_list[:3]
    
    # Build HTML
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Candidate Evaluation - {candidate_name}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #1f2937;
            background: #f9fafb;
            padding: 20px;
        }}
        
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            padding: 30px;
        }}
        
        .header {{
            margin-bottom: 30px;
        }}
        
        .candidate-name {{
            font-size: 28px;
            font-weight: 700;
            color: #111827;
            margin-bottom: 5px;
        }}
        
        .position-title {{
            font-size: 14px;
            color: #6b7280;
            margin-bottom: 20px;
        }}
        
        .info-boxes {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 15px;
            margin-bottom: 30px;
        }}
        
        .info-box {{
            background: #f3f4f6;
            padding: 15px;
            border-radius: 6px;
        }}
        
        .info-label {{
            font-size: 11px;
            font-weight: 600;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }}
        
        .info-value {{
            font-size: 16px;
            font-weight: 600;
            color: #111827;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            color: white;
        }}
        
        .badge-pass {{ background: #16a34a; }}
        .badge-fail {{ background: #dc2626; }}
        .badge-review {{ background: #ea580c; }}
        
        .score-large {{
            font-size: 32px;
            font-weight: 700;
            color: #111827;
        }}
        
        .section {{
            margin-bottom: 30px;
        }}
        
        .section-title {{
            font-size: 16px;
            font-weight: 700;
            color: #111827;
            margin-bottom: 12px;
        }}
        
        .section-content {{
            font-size: 14px;
            color: #4b5563;
            line-height: 1.7;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
            font-size: 13px;
        }}
        
        thead {{
            background: #9ca3af;
            color: white;
        }}
        
        thead.must-have {{
            background: #3b82f6;
        }}
        
        thead.nice-to-have {{
            background: #3b82f6;
        }}
        
        th {{
            padding: 10px;
            text-align: left;
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }}
        
        td {{
            padding: 12px 10px;
            border-bottom: 1px solid #e5e7eb;
        }}
        
        tr:last-child td {{
            border-bottom: none;
        }}
        
        .requirement-text {{
            font-weight: 500;
            color: #111827;
            margin-bottom: 3px;
        }}
        
        .score-cell {{
            font-weight: 700;
            font-size: 14px;
        }}
        
        .weight-cell {{
            color: #6b7280;
        }}
        
        .evidence-text {{
            font-size: 12px;
            color: #6b7280;
            font-style: italic;
        }}
        
        .tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 15px 0;
        }}
        
        .tag {{
            background: #15803d;
            color: white;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
        }}
        
        .tag-green {{
            background: #16a34a;
        }}
        
        .tag-red {{
            background: #dc2626;
        }}
        
        .strength-list {{
            list-style: none;
            padding-left: 0;
        }}
        
        .strength-list li {{
            padding: 8px 0;
            padding-left: 20px;
            position: relative;
        }}
        
        .strength-list li:before {{
            content: "✓";
            position: absolute;
            left: 0;
            color: #16a34a;
            font-weight: bold;
        }}
        
        .interview-questions {{
            background: #f9fafb;
            padding: 20px;
            border-radius: 6px;
            border-left: 4px solid #3b82f6;
        }}
        
        .interview-questions ul {{
            list-style: none;
            padding-left: 0;
        }}
        
        .interview-questions li {{
            padding: 10px 0;
            padding-left: 25px;
            position: relative;
        }}
        
        .interview-questions li:before {{
            content: "•";
            position: absolute;
            left: 10px;
            color: #3b82f6;
            font-weight: bold;
            font-size: 18px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1 class="candidate-name">{candidate_name}</h1>
            <p class="position-title">Candidate Evaluation Report</p>
        </div>
        
        <!-- Info Boxes -->
        <div class="info-boxes">
            <div class="info-box">
                <div class="info-label">Position</div>
                <div class="info-value">{job_name}</div>
                <div style="margin-top: 8px;">
                    <span class="badge" style="background: {badge_color};">{badge_text}</span>
                </div>
            </div>
            
            <div class="info-box">
                <div class="info-label">Overall Score</div>
                <div class="score-large">{overall_score:.1f}</div>
            </div>
            
            <div class="info-box">
                <div class="info-label">Report Date</div>
                <div class="info-value">{submission_date}</div>
            </div>
        </div>
        
        <!-- Executive Summary -->
        <div class="section">
            <h2 class="section-title">Executive Summary</h2>
            <p class="section-content">{ai_summary}</p>
        </div>
'''
    
    # Compliance Requirements
    if compliance:
        html += '''
        <div class="section">
            <h2 class="section-title">Compliance Requirements</h2>
            <table>
                <thead>
                    <tr>
                        <th style="width: 50%;">Requirement</th>
                        <th style="width: 15%;">Status</th>
                        <th style="width: 35%;">Details</th>
                    </tr>
                </thead>
                <tbody>
'''
        for comp in compliance:
            req_text = comp.get("requirement", "")
            status = comp.get("status", "UNKNOWN")
            evidence = comp.get("evidence", "")
            
            status_badge = f'<span class="badge badge-pass">COMPLY</span>' if status == "PASS" else f'<span class="badge badge-fail">REVIEW</span>'
            
            html += f'''
                    <tr>
                        <td class="requirement-text">{req_text}</td>
                        <td>{status_badge}</td>
                        <td class="evidence-text">{evidence}</td>
                    </tr>
'''
        html += '''
                </tbody>
            </table>
        </div>
'''
    
    # Must-Have Requirements
    if must_have:
        html += '''
        <div class="section">
            <h2 class="section-title">Must-Have Requirements (90% Weight)</h2>
            <table>
                <thead class="must-have">
                    <tr>
                        <th style="width: 40%;">Requirement</th>
                        <th style="width: 10%;">Score</th>
                        <th style="width: 10%;">Weight</th>
                        <th style="width: 40%;">Evidence</th>
                    </tr>
                </thead>
                <tbody>
'''
        for req in must_have:
            req_text = req.get("requirement", "")
            score = req.get("score", 0)
            weight = req.get("weight", 0)
            evidence = req.get("evidence", "Not demonstrated")
            
            score_color = get_score_color(score)
            
            html += f'''
                    <tr>
                        <td class="requirement-text">{req_text}</td>
                        <td class="score-cell" style="color: {score_color};">{score}/5</td>
                        <td class="weight-cell">{weight}%</td>
                        <td class="evidence-text">{evidence}</td>
                    </tr>
'''
        html += '''
                </tbody>
            </table>
        </div>
'''
    
    # Nice-to-Have Skills
    if nice_to_have:
        html += '''
        <div class="section">
            <h2 class="section-title">Nice-to-Have Skills (10% Weight)</h2>
            <table>
                <thead class="nice-to-have">
                    <tr>
                        <th style="width: 40%;">Skill</th>
                        <th style="width: 10%;">Score</th>
                        <th style="width: 10%;">Weight</th>
                        <th style="width: 40%;">Evidence</th>
                    </tr>
                </thead>
                <tbody>
'''
        for skill in nice_to_have:
            skill_text = skill.get("skill", "")
            score = skill.get("score", 0)
            weight = skill.get("weight", 0)
            evidence = skill.get("evidence", "Not demonstrated")
            
            score_color = get_score_color(score)
            
            html += f'''
                    <tr>
                        <td class="requirement-text">{skill_text}</td>
                        <td class="score-cell" style="color: {score_color};">{score}/5</td>
                        <td class="weight-cell">{weight}%</td>
                        <td class="evidence-text">{evidence}</td>
                    </tr>
'''
        html += '''
                </tbody>
            </table>
        </div>
'''
    
    # Assessment Summary
    html += '''
        <div class="section">
            <h2 class="section-title">Assessment Summary</h2>
'''
    
    # Key Strengths
    if ai_strengths:
        html += '''
            <h3 style="font-size: 14px; font-weight: 600; margin: 15px 0 10px 0;">Key Strengths</h3>
'''
        if strength_tags:
            html += '            <div class="tags">\n'
            for tag in strength_tags:
                html += f'                <span class="tag">{tag}</span>\n'
            html += '            </div>\n'
    
    # Development Focus (Gaps)
    if ai_gaps:
        html += '''
            <h3 style="font-size: 14px; font-weight: 600; margin: 20px 0 10px 0;">Gap</h3>
            <p class="section-content" style="margin-bottom: 10px;">Missing skills or experience in key areas</p>
'''
        if gap_badges:
            html += '            <div class="tags">\n'
            for gap in gap_badges:
                html += f'                <span class="tag tag-red">{gap}</span>\n'
            html += '            </div>\n'
    
    html += '''
        </div>
'''
    
    # Interview Questions
    html += '''
        <div class="section">
            <h2 class="section-title">Suggested Interview Questions</h2>
            <div class="interview-questions">
                <ul>
'''
    
    # Generate interview questions based on must-have requirements
    question_count = 0
    for req in must_have[:5]:  # Top 5 requirements
        req_text = req.get("requirement", "")
        score = req.get("score", 0)
        
        # Generate question based on score
        if score >= 4:
            question = f"Can you walk us through your experience with {req_text.lower()}? Please provide specific examples."
        elif score >= 2:
            question = f"We noticed some experience with {req_text.lower()}. Can you elaborate on your hands-on work in this area?"
        else:
            question = f"This role requires {req_text.lower()}. How would you approach learning this skill?"
        
        html += f'                    <li>{question}</li>\n'
        question_count += 1
    
    # Add a general question
    html += f'''                    <li>What interests you most about this {job_name} role, and how do your skills align with our requirements?</li>
                </ul>
            </div>
        </div>
'''
    
    # Footer
    html += f'''
        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #9ca3af; text-align: center;">
            <p>Generated on {submission_date} • AI-Powered Candidate Evaluation</p>
        </div>
    </div>
</body>
</html>
'''
    
    return html


# =========================
# Tier 2: Detailed Evaluation
# (Reusing existing llm_score_detailed from python9.py)
# =========================

def _get_scoring_config(rubric: dict) -> dict:
    """Extract scoring configuration from rubric"""
    scoring = rubric.get("scoring") or rubric.get("scoring_rules") or {}
    return {
        "pass_threshold": scoring.get("pass_threshold", 70),
        "floor_rule": scoring.get("floor_rule", "Any must-have < 2 triggers FAIL")
    }

def build_detailed_scoring_prompt(rubric: dict, resume_text: str, rubric_version: str) -> str:
    """Build detailed scoring prompt for Tier 2"""
    # Extract compliance items
    compliance_items = rubric.get("compliance_requirements") or rubric.get("compliance") or []
    if isinstance(compliance_items, list) and compliance_items:
        if isinstance(compliance_items[0], dict):
            compliance_text = "\n".join(f"- {item.get('item', item)}" for item in compliance_items)
        else:
            compliance_text = "\n".join(f"- {item}" for item in compliance_items)
    else:
        compliance_text = "None specified"

    # Extract must-have requirements
    requirements = rubric.get("requirements", {})
    must_have = requirements.get("must_have", [])
    nice_to_have = requirements.get("nice_to_have", [])
    
    must_have_ids = [item.get("id", f"MH{i+1}") for i, item in enumerate(must_have)]
    nth_ids = [item.get("id", f"NH{i+1}") for i, item in enumerate(nice_to_have)]
    
    # Build must-have text
    must_have_text = []
    for item in must_have:
        item_id = item.get("id", "")
        requirement = item.get("requirement", "")
        weight = item.get("weight", 0)
        evidence_signals = item.get("evidence_signals", [])
        negative_signals = item.get("negative_signals", [])
        
        text = f"{item_id}: {requirement} (weight: {weight}%)"
        if evidence_signals:
            text += f"\n  Evidence signals: {', '.join(evidence_signals)}"
        if negative_signals:
            text += f"\n  Red flags: {', '.join(negative_signals)}"
        must_have_text.append(text)
    
    # Build nice-to-have text
    nice_to_have_text = []
    for item in nice_to_have:
        item_id = item.get("id", "")
        skill = item.get("skill", "")
        weight = item.get("weight", 0)
        nice_to_have_text.append(f"{item_id}: {skill} (weight: {weight}%)")
    
    prompt = f"""You are an expert technical recruiter. Score this candidate's resume against the job requirements.

=== COMPLIANCE REQUIREMENTS (Pass/Fail) ===
{compliance_text}

=== MUST-HAVE REQUIREMENTS (90% total weight) ===
{chr(10).join(must_have_text)}

=== NICE-TO-HAVE SKILLS (10% total weight) ===
{chr(10).join(nice_to_have_text)}

=== RESUME ===
{clip(resume_text, MAX_RESUME_CHARS)}

=== SCORING INSTRUCTIONS ===
For each requirement/skill, assign:
- score: 0-5 (0=Not demonstrated, 1=Mentioned, 2=Basic, 3=Hands-on, 4=Advanced, 5=Expert)
- evidence: Direct quote or specific detail from resume (or "Not demonstrated")
- contribution: (score/5) * weight

Return ONLY valid JSON (no markdown, no code blocks):
{{
  "compliance": [
    {{"requirement": "<exact text>", "status": "PASS|FAIL", "evidence": "<quote or explanation>"}}
  ],
  "must_have": [
    {{"id": "<exact ID e.g. MH1>", "requirement": "<exact requirement text>", "score": <0-5>, "weight": <exact weight from rubric>, "contribution": <score/5 * weight>, "evidence": "<direct quote or specific detail from resume, or 'Not demonstrated'>"}}
  ],
  "nice_to_have": [
    {{"id": "<exact ID e.g. NH1>", "skill": "<exact skill text>", "score": <0-5>, "weight": <exact weight from rubric>, "contribution": <score/5 * weight>, "evidence": "<direct quote or specific detail from resume, or 'Not demonstrated'>"}}
  ],
  "overall_score": <sum of all contributions, 1 decimal>,
  "ai_score": <same as overall_score>,
  "ai_summary": "<3-5 sentence assessment. Must mention role fit, key strengths, and key gaps. 50-80 words.>",
  "ai_strengths": "<comma-separated list of actual strengths found in resume>",
  "ai_gaps": "<comma-separated list of missing or weak requirements>",
  "recommendation": "PASS|FAIL",
  "floor_triggered": <true|false>
}}

=== HARD RULES ===
1. must_have array MUST contain EXACTLY these IDs in order: {must_have_ids}
2. nice_to_have array MUST contain EXACTLY these IDs in order: {nth_ids}
3. compliance array MUST match the compliance items listed above
4. DO NOT rename, merge, or skip any item
5. Use the EXACT weight values from this rubric — do NOT use weight=1 for everything
6. evidence must be a specific quote or detail from the resume — NOT a generic statement
7. If evidence is absent, set score=0 and evidence="Not demonstrated in resume"
8. Recalculate overall_score yourself using the formula above — do NOT guess
"""
    return prompt


def llm_score_detailed(
    oa: OpenAI,
    rubric: dict,
    rubric_json: str,
    rubric_version: str,
    resume_text: str
) -> Dict[str, Any]:
    """
    Tier 2: Detailed evaluation with full breakdown.
    Returns dict with all fields including ai_detailed_json.
    """
    prompt = build_detailed_scoring_prompt(rubric, resume_text, rubric_version)
    
    api_kwargs: Dict[str, Any] = {
        "model": TIER2_MODEL,
        "messages": [
            {"role": "system", "content": "You are a technical recruiter. Respond only with valid JSON. No markdown, no code blocks."},
            {"role": "user", "content": prompt}
        ],
    }

    MODELS_SUPPORTING_TEMPERATURE = {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"}
    if any(TIER2_MODEL.startswith(m) for m in MODELS_SUPPORTING_TEMPERATURE):
        api_kwargs["temperature"] = 0.2

    try:
        r = oa.chat.completions.create(**api_kwargs)
        text = r.choices[0].message.content or ""
        
        # Clean markdown code blocks if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            if text.startswith("json"):
                text = text[4:].strip()
        
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                data = json.loads(m.group(0))
            else:
                raise ValueError("Could not extract valid JSON from response")
        
        # Recompute score
        def _recompute_score(data: dict) -> float:
            total = 0.0
            for item in data.get("must_have", []):
                s = float(item.get("score", 0) or 0)
                w = float(item.get("weight", 0) or 0)
                contrib = round((s / 5.0) * w, 4)
                item["contribution"] = contrib
                total += contrib
            for item in data.get("nice_to_have", []):
                s = float(item.get("score", 0) or 0)
                w = float(item.get("weight", 0) or 0)
                contrib = round((s / 5.0) * w, 4)
                item["contribution"] = contrib
                total += contrib
            return round(min(total, 100.0), 1)

        recomputed = _recompute_score(data)
        data["overall_score"] = recomputed
        data["ai_score"] = recomputed

        # Floor rule
        scoring_cfg = _get_scoring_config(rubric)
        floor_triggered = any(
            float(item.get("score", 0) or 0) < 2
            for item in data.get("must_have", [])
        )
        pass_threshold = scoring_cfg.get("pass_threshold", 70)
        data["floor_triggered"] = floor_triggered
        data["recommendation"] = "FAIL" if (floor_triggered or recomputed < pass_threshold) else "PASS"

        # Ensure backward-compatible fields
        if "ai_score" not in data:
            data["ai_score"] = data.get("overall_score", 0)
        if "ai_summary" not in data:
            data["ai_summary"] = data.get("summary", "No summary provided")
        if "ai_strengths" not in data:
            strengths = data.get("strengths", [])
            data["ai_strengths"] = ", ".join(strengths) if isinstance(strengths, list) else str(strengths)
        if "ai_gaps" not in data:
            gaps = data.get("gaps", [])
            data["ai_gaps"] = ", ".join(gaps) if isinstance(gaps, list) else str(gaps)
        
        data["ai_detailed_json"] = json.dumps(data, ensure_ascii=False)
        return data
        
    except Exception as e:
        print(f"  ⚠️  Tier 2 evaluation error: {e}")
        return {
            "ai_score": 0,
            "ai_summary": f"ERROR: {str(e)[:100]}",
            "ai_strengths": "",
            "ai_gaps": "Scoring failed",
            "ai_detailed_json": json.dumps({
                "compliance": [],
                "must_have": [],
                "nice_to_have": [],
                "overall_score": 0,
                "ai_score": 0,
                "ai_summary": f"ERROR: {str(e)[:100]}",
                "ai_strengths": "",
                "ai_gaps": "Scoring failed",
                "recommendation": "FAIL",
                "floor_triggered": False
            }, ensure_ascii=False)
        }

# =========================
# Main
# =========================
def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 python9_tier2.py <JOB_ID>", file=sys.stderr)
        return 2

    job_id = str(sys.argv[1]).strip()
    if not job_id.isdigit():
        print(f"ERROR: JOB_ID must be numeric, got: {job_id}", file=sys.stderr)
        return 2

    job_id_int = int(job_id)

    # Check credentials
    if not MANATAL_API_TOKEN:
        print("ERROR: MANATAL_API_TOKEN env var is not set.", file=sys.stderr)
        return 2
    if not OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY env var is not set.", file=sys.stderr)
        return 2

    export_dir = Path(EXPORT_PATH).expanduser()
    export_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = export_dir / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Load rubric
    rubric_path = f"{RUBRIC_DIR}/rubric_{job_id}.json"
    if not os.path.exists(rubric_path):
        print(f"ERROR: Rubric JSON not found for Job ID {job_id}", file=sys.stderr)
        print(f"Expected: {rubric_path}", file=sys.stderr)
        return 2

    rubric = load_rubric_json(rubric_path)
    rubric_json = rubric_compact_json(rubric)
    rubric_version = str(rubric.get("version", rubric.get("rubric_version", "unknown")))
    rubric_hash = sha256_text(rubric_json)[:12]

    cache = load_cache(CACHE_FILE)
    oa = OpenAI(api_key=OPENAI_API_KEY)
    airtable = AirtableManager()

    # Job info
    _, job_name, org_id, org_name, _ = get_job_and_org(job_id)

    # Fetch candidates
    matches = fetch_all_paginated(f"/jobs/{job_id}/matches/", params={"page_size": PAGE_SIZE})
    
    total_in_stage = sum(
        1 for m in matches 
        if extract_stage_name(m) == TARGET_STAGE_NAME and extract_candidate_id(m) is not None
    )
    
    print(f"\n{'='*60}")
    print(f"TWO-TIER SCORING")
    print(f"{'='*60}")
    print(f"Job: {job_name} (ID: {job_id})")
    print(f"Candidates in '{TARGET_STAGE_NAME}': {total_in_stage}")
    print(f"Tier 1 Model: {TIER1_MODEL}")
    print(f"Tier 2 Model: {TIER2_MODEL}")
    print(f"Pass Threshold: {TIER1_PASS_THRESHOLD}")
    print(f"{'='*60}\n")

    # Tier 1: Screening
    print(f"=== TIER 1: SCREENING ===\n")
    
    tier1_results = {"pass": 0, "fail": 0, "total": 0}
    tier2_candidates = []
    rows: List[Dict[str, Any]] = []
    
    for match in matches:
        stage_name = extract_stage_name(match)
        if stage_name != TARGET_STAGE_NAME:
            continue

        candidate_id = extract_candidate_id(match)
        if not candidate_id:
            continue

        tier1_results["total"] += 1
        org_id, org_name = maybe_fill_org_from_match(match, org_id, org_name)
        
        candidate = api_get(f"/candidates/{candidate_id}/")
        full_name = candidate.get("full_name")
        email = candidate.get("email")
        resume_url = extract_resume_url_from_candidate(candidate)
        
        # Cache keys
        tier1_cache_key = f"{job_id}-{candidate_id}-{rubric_hash}-tier1"
        tier2_cache_key = f"{job_id}-{candidate_id}-{rubric_hash}-tier2"
        
        # Tier 1 Screening
        if SKIP_ALREADY_SCORED and not FORCE_RESCORE and tier1_cache_key in cache:
            cached_tier1 = cache[tier1_cache_key]
            tier1_score = cached_tier1.get("tier1_score", 0)
            tier1_status = cached_tier1.get("tier1_status", "FAIL")
            resume_local_path = cached_tier1.get("resume_local_path", "")
            print(f"  [Cached] {tier1_results['total']}/{total_in_stage}. {full_name} → Tier 1: {tier1_score} ({tier1_status})")
        else:
            tier1_score = 0
            tier1_status = "FAIL"
            resume_local_path = ""
            resume_text = ""
            
            if resume_url and DOWNLOAD_RESUMES:
                ext = Path(resume_url.split("?")[0]).suffix or ".pdf"
                out = export_dir / "resumes" / f"{candidate_id}-{safe_filename(full_name or str(candidate_id))}{ext}"
                try:
                    download_file(resume_url, out)
                    resume_local_path = str(out)
                    resume_text = resume_text_from_file(out)
                    
                    if resume_text.strip():
                        tier1_score = tier1_screen(oa, rubric_json, resume_text)
                        tier1_status = "PASS" if tier1_score >= TIER1_PASS_THRESHOLD else "FAIL"
                    
                except Exception as e:
                    print(f"  ⚠️  Resume error for {candidate_id}: {e}")
            
            # Cache Tier 1 result
            cache[tier1_cache_key] = {
                "job_id": job_id_int,
                "candidate_id": candidate_id,
                "rubric_hash": rubric_hash,
                "tier1_score": tier1_score,
                "tier1_status": tier1_status,
                "resume_local_path": resume_local_path,
            }
            save_cache(CACHE_FILE, cache)
            print(f"  [Tier 1] {tier1_results['total']}/{total_in_stage}. {full_name} → {tier1_score} ({tier1_status})")
        
        # Track stats
        if tier1_status == "PASS":
            tier1_results["pass"] += 1
            tier2_candidates.append({
                "match": match,
                "candidate_id": candidate_id,
                "candidate": candidate,
                "full_name": full_name,
                "email": email,
                "resume_url": resume_url,
                "resume_local_path": resume_local_path,
                "tier1_score": tier1_score,
                "tier1_status": tier1_status,
                "tier2_cache_key": tier2_cache_key,
            })
        else:
            tier1_results["fail"] += 1
            
            # Write Tier 1 failure to Airtable (no Tier 2 data)
            airtable_record = {
                "organisation_id": int(org_id) if org_id is not None else None,
                "organisation_name": org_name,
                "job_id": job_id_int,
                "job_name": job_name,
                "created_at": match.get("created_at"),
                "updated_at": match.get("updated_at"),
                "match_stage_name": stage_name,
                "candidate_id": candidate_id,
                "full_name": full_name,
                "email": email,
                "resume_file": resume_url,
                "CV": [{"url": resume_url}] if resume_url else [],
                "resume_local_path": resume_local_path,
                "tier1_score": tier1_score,
                "tier1_status": tier1_status,
                "rubric_version": rubric_version,
                "rubric_hash": rubric_hash,
                "cache_key": tier1_cache_key,
            }
            airtable.create_or_update_record(airtable_record)
            
            # Add to CSV backup
            if WRITE_CSV_BACKUP:
                rows.append(airtable_record)
    
    # Flush any remaining Tier 1 records
    airtable.flush_batch()
    
    print(f"\n{'='*60}")
    print(f"TIER 1 COMPLETE")
    print(f"{'='*60}")
    print(f"Total: {tier1_results['total']}")
    print(f"PASS: {tier1_results['pass']} ({tier1_results['pass']*100//tier1_results['total'] if tier1_results['total'] > 0 else 0}%)")
    print(f"FAIL: {tier1_results['fail']} ({tier1_results['fail']*100//tier1_results['total'] if tier1_results['total'] > 0 else 0}%)")
    print(f"{'='*60}\n")
    
    # Tier 2: Detailed Evaluation
    if tier2_candidates:
        print(f"=== TIER 2: DETAILED EVALUATION ===\n")
        
        tier2_results = {"pass": 0, "review": 0, "fail": 0, "total": len(tier2_candidates)}
        
        for idx, cand_data in enumerate(tier2_candidates, 1):
            candidate_id = cand_data["candidate_id"]
            full_name = cand_data["full_name"]
            tier2_cache_key = cand_data["tier2_cache_key"]
            
            # Check Tier 2 cache
            if SKIP_ALREADY_SCORED and not FORCE_RESCORE and tier2_cache_key in cache:
                cached_tier2 = cache[tier2_cache_key]
                score = {
                    "ai_score": cached_tier2.get("ai_score", 0),
                    "ai_summary": cached_tier2.get("ai_summary", ""),
                    "ai_strengths": cached_tier2.get("ai_strengths", ""),
                    "ai_gaps": cached_tier2.get("ai_gaps", ""),
                    "ai_detailed_json": cached_tier2.get("ai_detailed_json", "{}"),
                }
                print(f"  [Cached] {idx}/{tier2_results['total']}. {full_name} → Tier 2: {score['ai_score']}")
            else:
                # Get resume
                resume_local_path = cand_data["resume_local_path"]
                if resume_local_path and Path(resume_local_path).exists():
                    resume_text = resume_text_from_file(Path(resume_local_path))
                else:
                    resume_text = ""
                
                if resume_text.strip():
                    score = llm_score_detailed(oa, rubric, rubric_json, rubric_version, resume_text)
                else:
                    score = {
                        "ai_score": 0,
                        "ai_summary": "Resume text extraction failed",
                        "ai_strengths": "",
                        "ai_gaps": "",
                        "ai_detailed_json": "{}",
                    }
                
                # Cache Tier 2 result
                cache[tier2_cache_key] = {
                    "job_id": job_id_int,
                    "candidate_id": candidate_id,
                    "rubric_hash": rubric_hash,
                    "ai_score": score.get("ai_score"),
                    "ai_summary": score.get("ai_summary"),
                    "ai_strengths": score.get("ai_strengths"),
                    "ai_gaps": score.get("ai_gaps"),
                    "ai_detailed_json": score.get("ai_detailed_json", "{}"),
                }
                save_cache(CACHE_FILE, cache)
                print(f"  [Tier 2] {idx}/{tier2_results['total']}. {full_name} → {score.get('ai_score')}")
            
            # Categorize
            ai_score = score.get("ai_score", 0)
            if ai_score >= 75:
                tier2_results["pass"] += 1
            elif ai_score >= 65:
                tier2_results["review"] += 1
            else:
                tier2_results["fail"] += 1
            
            # Generate HTML report
            try:
                detailed_data = json.loads(score.get("ai_detailed_json", "{}"))
                html_report = generate_html_report(
                    candidate_name=full_name,
                    job_name=job_name,
                    overall_score=ai_score,
                    detailed_json=detailed_data
                )
            except Exception as e:
                print(f"  ⚠️  HTML report generation failed for {candidate_id}: {e}")
                html_report = f"<p>HTML report generation failed: {e}</p>"
            
            # Write to Airtable
            airtable_record = {
                "organisation_id": int(org_id) if org_id is not None else None,
                "organisation_name": org_name,
                "job_id": job_id_int,
                "job_name": job_name,
                "created_at": cand_data["match"].get("created_at"),
                "updated_at": cand_data["match"].get("updated_at"),
                "match_stage_name": extract_stage_name(cand_data["match"]),
                "candidate_id": candidate_id,
                "full_name": full_name,
                "email": cand_data["email"],
                "resume_file": cand_data["resume_url"],
                "CV": [{"url": cand_data["resume_url"]}] if cand_data["resume_url"] else [],
                "resume_local_path": cand_data["resume_local_path"],
                "tier1_score": cand_data["tier1_score"],
                "tier1_status": cand_data["tier1_status"],
                "ai_score": score.get("ai_score"),
                "ai_summary": score.get("ai_summary"),
                "ai_strengths": score.get("ai_strengths"),
                "ai_gaps": score.get("ai_gaps"),
                "ai_detailed_json": score.get("ai_detailed_json", "{}"),
                "ai_report_html": html_report,
                "rubric_version": rubric_version,
                "rubric_hash": rubric_hash,
                "cache_key": tier2_cache_key,
            }
            airtable.create_or_update_record(airtable_record)
            
            # Add to CSV backup
            if WRITE_CSV_BACKUP:
                rows.append(airtable_record)
        
        # Flush remaining Tier 2 records
        airtable.flush_batch()
        
        print(f"\n{'='*60}")
        print(f"TIER 2 COMPLETE")
        print(f"{'='*60}")
        print(f"Total evaluated: {tier2_results['total']}")
        print(f"PASS (≥75): {tier2_results['pass']}")
        print(f"REVIEW (65-74): {tier2_results['review']}")
        print(f"FAIL (<65): {tier2_results['fail']}")
        print(f"{'='*60}\n")
    
    # Write CSV backup
    if WRITE_CSV_BACKUP and rows:
        base = safe_filename(f"manatal_job_{job_id}_{TARGET_STAGE_NAME}")
        json_path = upload_dir / f"{base}_tier2_scored.json"
        csv_path = upload_dir / f"{base}_tier2_scored.csv"
        
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        
        fieldnames = [
            "organisation_id", "organisation_name", "job_id", "job_name",
            "created_at", "updated_at", "match_stage_name",
            "candidate_id", "full_name", "email",
            "resume_file", "resume_local_path",
            "tier1_score", "tier1_status",
            "ai_score", "ai_summary", "ai_strengths", "ai_gaps", "ai_detailed_json", "ai_report_html",
            "rubric_version", "rubric_hash", "cache_key",
        ]
        
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        
        print(f"\n{'='*60}")
        print(f"CSV BACKUP")
        print(f"{'='*60}")
        print(f"JSON: {json_path}")
        print(f"CSV: {csv_path}")
        print(f"{'='*60}\n")
    
    print(f"✅ Done! Processed {tier1_results['total']} candidates")
    print(f"Cache: {CACHE_FILE}")
    if WRITE_TO_AIRTABLE:
        print(f"Airtable: Updated successfully")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

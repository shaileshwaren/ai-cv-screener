#!/usr/bin/env python3
"""generate_detailed_reports.py

Generates detailed HTML reports for candidates scoring 80+ by RE-SCORING them
with AI to get granular item-by-item breakdown.

This script:
1. Reads scored candidates from output/upload/*.csv
2. For candidates with ai_score >= 80:
   - RE-SCORES them using OpenAI with detailed prompt
   - Gets REAL scores for each compliance/must-have/nice-to-have item
   - Generates detailed scoring JSON (NO placeholders!)
   - Creates beautiful HTML report
   - Uploads HTML to Supabase (ai_report_html field)
   - Generates text embeddings and saves to Supabase (candidate_chunks)

Usage:
  python3 generate_detailed_reports.py <JOB_ID>
  python3 generate_detailed_reports.py 3419430

Output:
  - output/reports/candidate_{ID}_report.json
  - output/reports/candidate_{ID}_report.html
  - Uploads HTML to Supabase (ai_report_html)
  - Upserts vector chunks to Supabase (candidate_chunks)
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from openai import OpenAI

# Import from consolidated modules
from config import Config
from src.supabase_client import SupabaseClient
from src.embedding_client import EmbeddingClient
from utils import extract_resume_text, clip


# =========================
# Supabase update function
# =========================
def update_supabase_html_and_embeddings(
    match_id: str,
    candidate_id: int,
    job_id: int,
    detailed_json: dict,
    html_path: Path,
    resume_text: str,
    supabase: SupabaseClient,
    embedder: EmbeddingClient
) -> bool:
    """Update the ai_report_html field in Supabase and generate embeddings. Candidates table uses match_id as primary key."""
    
    try:
        html_text = html_path.read_text(encoding="utf-8")
        
        # 1. Upload HTML file to Supabase Storage
        file_name = f"{candidate_id}_report_{job_id}.html"
        storage_path = f"{candidate_id}/reports/{file_name}"
        
        supabase.client.storage.from_(Config.SUPABASE_STORAGE_BUCKET).upload(
            path=storage_path,
            file=html_text.encode("utf-8"),
            file_options={"content-type": "text/html", "upsert": "true"},
        )
        
        # Wrap in HTML Preview proxy because Supabase blocks inline HTML rendering on its default domains
        base_url = supabase.client.storage.from_(Config.SUPABASE_STORAGE_BUCKET).get_public_url(storage_path)
        public_html_url = f"https://htmlpreview.github.io/?{base_url}"
        
        # 2. Update ai_report_html and detailed score/summary in candidates table (keyed by match_id)
        report_score = int(detailed_json.get("overall_score") or detailed_json.get("ai_score") or 0)
        supabase.client.table("candidates").update({
            "ai_report_html": public_html_url,
            "ai_score": report_score,
            "ai_summary": (detailed_json.get("ai_summary") or "").strip(),
            "ai_strengths": (detailed_json.get("ai_strengths") or "").strip(),
            "ai_gaps": (detailed_json.get("ai_gaps") or "").strip(),
        }).eq("match_id", match_id).execute()
        
        # 3. Extract clean text from HTML for embedding
        import unicodedata
        clean_html_text = re.sub(r'<[^>]+>', ' ', html_text)
        clean_html_text = unicodedata.normalize("NFKD", clean_html_text)
        clean_html_text = " ".join(clean_html_text.split())
        
        # 3. Create rich text block for embedding
        strengths = detailed_json.get("ai_strengths", "")
        gaps = detailed_json.get("ai_gaps", "")
        summary = detailed_json.get("ai_summary", "")
        
        chunk_text = (
            f"Candidate Summary: {summary}\n\n"
            f"Strengths: {strengths}\n\n"
            f"Gaps: {gaps}\n\n"
            f"Detailed Report:\n{clean_html_text}\n\n"
            f"Resume Excerpt:\n{clip(resume_text, 2000)}"
        )
        
        # 4. Generate Vector Embedding
        embedding_vector = embedder.generate_embedding(chunk_text)
        if embedding_vector:
            # Upsert into candidate_chunks
            chunk_data = {
                "candidate_id": candidate_id,
                "job_id": job_id,
                "chunk_text": chunk_text,
                "embedding": embedding_vector,
                "chunk_index": 0
            }
            supabase.client.table("candidate_chunks").upsert(chunk_data).execute()
            return True
            
        return False
        
    except Exception as e:
        print(f"[WARN] Supabase update/embedding failed: {e}")
        return False


# =========================
# Rubric parsing
# =========================
def load_rubric_yaml(job_id: str) -> dict:
    """Load rubric YAML for a job."""
    rubric_path = Config.get_rubric_path(job_id)
    
    if not rubric_path.exists():
        raise FileNotFoundError(f"Rubric not found: {rubric_path}")
    
    with rubric_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_rubric_structure(rubric: dict) -> Dict[str, Any]:
    """Extract structured rubric data.
    
    Supports both formats:
    - Old format: compliance_gates, must_haves, nice_to_haves, global_policies
    - New format: compliance, must_have, nice_to_have, scoring_rules
    """
    
    compliance = []
    must_have = []
    nice_to_have = []
    
    # ===== COMPLIANCE PARSING =====
    # Try new format first (list with "item" field)
    compliance_list = rubric.get("compliance", [])
    if isinstance(compliance_list, list) and compliance_list:
        for comp in compliance_list:
            if isinstance(comp, dict):
                # New format: {"item": "Bachelor's degree..."}
                compliance.append({
                    "item": comp.get("item", comp.get("requirement", "")),
                    "details": comp.get("details", "")
                })
            elif isinstance(comp, str):
                # Simple string format
                compliance.append({
                    "item": comp,
                    "details": ""
                })
    
    # Fall back to old format (nested dict)
    if not compliance:
        compliance_gates = rubric.get("compliance_gates", {})
        if isinstance(compliance_gates, dict):
            for key, gate_data in compliance_gates.items():
                if isinstance(gate_data, dict):
                    compliance.append({
                        "item": gate_data.get("requirement", key.replace("_", " ").title()),
                        "details": gate_data.get("details", "")
                    })
                elif isinstance(gate_data, str):
                    compliance.append({
                        "item": key.replace("_", " ").title(),
                        "details": gate_data
                    })
    
    # ===== MUST-HAVE PARSING =====
    # Try new format first (must_have)
    must_have_reqs = rubric.get("must_have", rubric.get("must_haves", []))
    if isinstance(must_have_reqs, list):
        for req in must_have_reqs:
            if isinstance(req, dict):
                must_have.append({
                    "requirement": req.get("requirement", ""),
                    "weight": float(req.get("weight", 0)),
                    "details": req.get("description", req.get("details", ""))
                })
    
    # ===== NICE-TO-HAVE PARSING =====
    # Try new format first (nice_to_have)
    nice_to_have_skills = rubric.get("nice_to_have", rubric.get("nice_to_haves", []))
    if isinstance(nice_to_have_skills, list):
        for skill in nice_to_have_skills:
            if isinstance(skill, dict):
                nice_to_have.append({
                    "skill": skill.get("skill", ""),
                    "weight": float(skill.get("weight", 0)),
                    "details": skill.get("description", skill.get("details", ""))
                })
    
    # ===== PASS THRESHOLD PARSING =====
    # Try new format first (scoring_rules)
    pass_threshold = Config.PASS_THRESHOLD  # Default
    
    scoring_rules = rubric.get("scoring_rules", {})
    if isinstance(scoring_rules, dict):
        pass_threshold = scoring_rules.get("pass_threshold", pass_threshold)
    
    # Fall back to old format
    if pass_threshold == Config.PASS_THRESHOLD:
        global_policies = rubric.get("global_policies", {})
        if isinstance(global_policies, dict):
            pass_threshold = global_policies.get("pass_threshold", pass_threshold)
    
    return {
        "compliance": compliance,
        "must_have": must_have,
        "nice_to_have": nice_to_have,
        "pass_threshold": pass_threshold
    }


# =========================
# AI DETAILED SCORING PROMPT (from python8.py)
# =========================
def build_detailed_scoring_prompt(rubric: dict, rubric_structure: Dict[str, Any], resume_text: str, rubric_version: str) -> str:
    """Build prompt requesting detailed JSON with item-by-item scores.
    
    CRITICAL: Uses parsed rubric_structure (normalized format) as source of truth.
    """
    
    # Use rubric's jd_summary for context (not raw JD)
    role_applied = rubric.get('role_applied', '')
    jd_summary = rubric.get('jd_summary', '')
    
    prompt = f"""You are an expert technical recruiter. Evaluate this candidate against the rubric requirements and provide DETAILED item-by-item scoring.

CRITICAL: The rubric below is the SINGLE SOURCE OF TRUTH for all scoring decisions. Do not add criteria beyond what is explicitly stated in the rubric. Do not make assumptions about requirements not listed.

RUBRIC_VERSION: {rubric_version}
ROLE: {role_applied}
JOB SUMMARY: {jd_summary}

"""
    
    # Add semantic ontology for better understanding of aliases/synonyms
    normalized_terms = rubric.get('normalized_terms', {})
    if normalized_terms and isinstance(normalized_terms, dict):
        prompt += "\n**SEMANTIC GUIDANCE (Aliases & Synonyms):**\n"
        prompt += "When evaluating skills, recognize these equivalent terms:\n"
        for term, details in list(normalized_terms.items())[:15]:  # Limit to first 15 to avoid token overflow
            if isinstance(details, dict):
                aliases = details.get('aliases', [])
                if aliases:
                    prompt += f"- {term}: {', '.join(aliases[:5])}\n"  # Show up to 5 aliases
        prompt += "\n"
    
    prompt += "**Requirements from Rubric (Score Against These ONLY):**\n"
    
    # Add compliance items - ONLY if compliance section exists
    compliance_items = rubric_structure.get('compliance', [])
    if compliance_items and isinstance(compliance_items, list):
        prompt += "\n**COMPLIANCE (Pass/Fail - Not Scored):**\n"
        for idx, item in enumerate(compliance_items, 1):
            item_text = item.get('item', '') if isinstance(item, dict) else str(item)
            if item_text:
                prompt += f"{idx}. {item_text}\n"
    
    # Add must-have requirements with weights - ONLY if must_have section exists
    must_have_reqs = rubric_structure.get('must_have', [])
    if must_have_reqs and isinstance(must_have_reqs, list):
        prompt += "\n**MUST-HAVE REQUIREMENTS (Critical - Heavily Weighted):**\n"
        for idx, req in enumerate(must_have_reqs, 1):
            requirement = req.get('requirement', '') if isinstance(req, dict) else ''
            weight = req.get('weight', 0) if isinstance(req, dict) else 0
            if requirement:
                prompt += f"{idx}. {requirement} (Weight: {weight}%)\n"
    
    # Add nice-to-have items - ONLY if nice_to_have section exists
    nice_to_have_skills = rubric_structure.get('nice_to_have', [])
    if nice_to_have_skills and isinstance(nice_to_have_skills, list):
        prompt += "\n**NICE-TO-HAVE SKILLS (Bonus Points):**\n"
        for idx, skill in enumerate(nice_to_have_skills, 1):
            skill_name = skill.get('skill', '') if isinstance(skill, dict) else ''
            weight = skill.get('weight', 0) if isinstance(skill, dict) else 0
            if skill_name:
                prompt += f"{idx}. {skill_name} (Weight: {weight}%)\n"
    
    prompt += f"""

**Candidate's Resume:**
{clip(resume_text, Config.MAX_RESUME_CHARS)}

**SCORING SCALE (0-5):**
- 5 = Exceptional - Exceeds requirements significantly, proven track record
- 4 = Strong - Clearly meets requirements with solid evidence
- 3 = Adequate - Meets minimum requirements
- 2 = Weak - Partially meets requirements, notable gaps
- 1 = Poor - Minimal evidence, major concerns
- 0 = None - No evidence of this requirement/skill

**CRITICAL INSTRUCTIONS:**
1. The rubric above is the EXHAUSTIVE list of ALL requirements - if it's not in the rubric, don't score it
2. Score EVERY requirement/skill listed above - do NOT add, remove, or modify any requirements
3. Use the EXACT requirement text from the rubric above - do NOT rephrase or create new requirements
4. The compliance array must have EXACTLY {len(compliance_items)} items
5. The must_have array must have EXACTLY {len(must_have_reqs)} items with the EXACT requirement text
6. The nice_to_have array must have EXACTLY {len(nice_to_have_skills)} items with the EXACT skill text
7. Do NOT invent or add requirements that are not in the rubric above
8. Do NOT consider factors not explicitly stated in the rubric (e.g., don't score "passion" unless rubric requires it)
9. Base scores ONLY on evidence in resume vs. rubric requirements
10. Respond with ONLY valid JSON. No preamble, no markdown, no explanation.

**Required JSON Structure:**
{{
  "compliance": [
    {{"item": "EXACT text from rubric", "status": "PASS|FAIL|NOT_ASSESSED", "details": "brief reason"}}
  ],
  "must_have": [
    {{"requirement": "EXACT text from rubric", "score": 0-5, "weight": number, "evidence": "specific evidence from resume"}}
  ],
  "nice_to_have": [
    {{"skill": "EXACT text from rubric", "score": 0-5, "weight": number, "evidence": "specific evidence from resume"}}
  ],
  "overall_score": calculated_score,
  "ai_score": calculated_score,
  "ai_summary": "2-3 sentence overall assessment (max 60 words)",
  "ai_strengths": "comma-separated strengths",
  "ai_gaps": "comma-separated gaps",
  "recommendation": "PASS|FAIL",
  "floor_triggered": boolean
}}

**IMPORTANT RULES:**
1. Score EVERY requirement/skill listed above (don't skip any)
2. Use EXACT requirement text - do NOT create new ones or modify existing ones
3. Provide specific evidence from the resume (not generic statements)
4. overall_score = (sum of weighted must-have scores) + (sum of weighted nice-to-have scores)
5. ai_score = overall_score (both should be the same integer 0-100)
6. Floor rule: If ANY must-have scores < 2, set floor_triggered = true and recommendation = FAIL
7. Pass threshold: overall_score >= 70 (unless floor triggered)
8. ai_summary must be concise (max 60 words)
9. ai_strengths and ai_gaps should be comma-separated strings

Respond with ONLY the JSON object using the EXACT requirements from the rubric above, nothing else."""
    
    return prompt


def llm_score_detailed(
    oa: OpenAI,
    rubric: dict,
    rubric_structure: Dict[str, Any],
    rubric_version: str,
    resume_text: str
) -> Dict[str, Any]:
    """Score candidate with detailed item-by-item breakdown using AI.
    
    CRITICAL: Uses parsed rubric_structure (normalized format) as source of truth.
    
    Returns dict with complete detailed scoring (NO placeholders).
    """
    
    prompt = build_detailed_scoring_prompt(rubric, rubric_structure, resume_text, rubric_version)
    
    try:
        r = oa.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a technical recruiter. Respond only with valid JSON. No markdown, no code blocks."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
        )
        
        text = r.choices[0].message.content or ""
        
        # Clean markdown code blocks if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            if text.startswith("json"):
                text = text[4:].strip()
        
        # Try to parse JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: try to extract JSON from text
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                data = json.loads(m.group(0))
            else:
                raise ValueError("Could not extract valid JSON from response")
        
        # Validate that we have the required fields
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
        
        return data
        
    except Exception as e:
        print(f"      ✗ Detailed scoring error: {e}")
        # Return error response
        return {
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
        }


# =========================
# Enhanced JSON generation with AI scoring
# =========================
def generate_detailed_json_with_ai(
    candidate: Dict[str, Any],
    rubric: dict,
    rubric_structure: Dict[str, Any],
    resume_text: str,
    openai_client: OpenAI
) -> Dict[str, Any]:
    """Generate detailed JSON by re-scoring with AI for granular breakdown.
    
    CRITICAL: Uses parsed rubric_structure (normalized format) as source of truth.
    """
    
    print(f"    🤖 Re-scoring with AI for detailed breakdown...")
    
    # Get detailed AI scoring
    rubric_version = rubric.get("version", "1.0")
    ai_data = llm_score_detailed(openai_client, rubric, rubric_structure, rubric_version, resume_text)
    
    # Parse strengths and gaps into lists
    ai_strengths = ai_data.get("ai_strengths", "")
    ai_gaps = ai_data.get("ai_gaps", "")
    strengths_list = [s.strip() for s in ai_strengths.split(",") if s.strip()]
    gaps_list = [g.strip() for g in ai_gaps.split(",") if g.strip()]
    
    # Calculate actual weights from rubric (not hardcoded)
    must_have_total_weight = sum(float(item.get("weight", 0)) for item in rubric_structure["must_have"])
    nice_to_have_total_weight = sum(float(item.get("weight", 0)) for item in rubric_structure["nice_to_have"])
    
    # Get company name from rubric (not hardcoded)
    company_name = rubric.get("company", "Recruitment System")
    
    # Build complete JSON with REAL AI data (no placeholders!)
    detailed_json = {
        # Core fields matching example format (ALL FROM AI!)
        "compliance": ai_data.get("compliance", []),
        "must_have": ai_data.get("must_have", []),
        "nice_to_have": ai_data.get("nice_to_have", []),
        "overall_score": ai_data.get("overall_score", 0),
        "ai_score": ai_data.get("ai_score", 0),
        "ai_summary": ai_data.get("ai_summary", ""),
        "ai_strengths": ai_strengths,
        "ai_gaps": ai_gaps,
        "recommendation": ai_data.get("recommendation", "FAIL"),
        "floor_triggered": ai_data.get("floor_triggered", False),
        
        # Additional fields for HTML rendering
        "candidate_name": candidate.get("full_name", ""),
        "candidate_id": candidate.get("candidate_id", ""),
        "position": candidate.get("job_name", ""),
        "pass_threshold": rubric_structure["pass_threshold"],
        "report_date": datetime.now().strftime("%B %d, %Y"),
        "generated_at": datetime.now().isoformat(),
        "generated_by": f"{company_name} Recruitment System",
        
        # Parsed strengths and gaps for HTML tags
        "key_strengths": strengths_list,
        "development_areas": gaps_list,
        
        # Weights calculated from rubric (not hardcoded!)
        "must_have_weight": int(must_have_total_weight),
        "nice_to_have_weight": int(nice_to_have_total_weight),
    }
    
    return detailed_json


# =========================
# HTML generation (same as before - shortened for space)
# =========================
def generate_html_report(detailed_json: Dict[str, Any]) -> str:
    """Generate professional HTML report."""
    
    candidate_name = detailed_json.get("candidate_name", "Candidate")
    position = detailed_json.get("position", "Position")
    overall_score = detailed_json.get("overall_score", 0)
    recommendation = detailed_json.get("recommendation", "REVIEW")
    report_date = detailed_json.get("report_date", datetime.now().strftime("%B %d, %Y"))
    executive_summary = detailed_json.get("ai_summary", "")
    candidate_id = detailed_json.get("candidate_id", "")
    generated_by = detailed_json.get("generated_by", "Recruitment System")
    
    key_strengths = detailed_json.get("key_strengths", [])
    development_areas = detailed_json.get("development_areas", [])
    compliance = detailed_json.get("compliance", [])
    must_have = detailed_json.get("must_have", [])
    nice_to_have = detailed_json.get("nice_to_have", [])
    
    badge_class = "badge-pass" if recommendation == "PASS" else "badge-fail"
    
    def get_score_dot(score: float, max_score: float = 5) -> str:
        ratio = score / max_score
        if ratio >= 0.8:
            return "dot-green"
        elif ratio >= 0.5:
            return "dot-yellow"
        else:
            return "dot-red"
    
    def get_status_class(status: str) -> str:
        if status == "PASS":
            return "status-pass"
        elif status == "FAIL":
            return "status-fail"
        else:
            return ""
    
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Candidate Report - {candidate_name}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 20px; font-family: -apple-system, system-ui, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #f5f7fa; color: #2c3e50; line-height: 1.6; }}
    .container {{ max-width: 900px; margin: 0 auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 2px 20px rgba(0,0,0,0.08); }}
    h1 {{ margin: 0 0 10px 0; font-size: 32px; color: #1a1a1a; font-weight: 700; }}
    .subtitle {{ color: #7f8c8d; font-size: 16px; margin-bottom: 30px; }}
    .info-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin-bottom: 30px; padding: 20px; background: #ecf0f1; border-radius: 8px; }}
    .info-label {{ font-size: 12px; color: #7f8c8d; font-weight: 600; text-transform: uppercase; }}
    .info-value {{ font-size: 18px; font-weight: 600; margin-top: 5px; }}
    .score-badge {{ display: inline-block; padding: 8px 18px; border-radius: 20px; font-weight: 700; font-size: 18px; }}
    .badge-pass {{ background: #d4edda; color: #155724; border: 2px solid #28a745; }}
    .badge-fail {{ background: #f8d7da; color: #721c24; border: 2px solid #dc3545; }}
    h2 {{ font-size: 20px; margin: 30px 0 15px 0; padding-bottom: 10px; border-bottom: 2px solid #e1e8ed; font-weight: 600; }}
    .summary-box {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 25px; border-left: 4px solid #3498db; }}
    table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px; }}
    th {{ background: #34495e; color: white; padding: 14px 12px; text-align: left; font-weight: 600; }}
    td {{ padding: 14px 12px; border-bottom: 1px solid #e1e8ed; vertical-align: top; }}
    tr:nth-child(even) {{ background: #f8f9fa; }}
    tr:hover {{ background: #ecf0f1; }}
    .score-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }}
    .dot-green {{ background: #27ae60; box-shadow: 0 0 0 3px rgba(39, 174, 96, 0.2); }}
    .dot-yellow {{ background: #f39c12; box-shadow: 0 0 0 3px rgba(243, 156, 18, 0.2); }}
    .dot-red {{ background: #e74c3c; box-shadow: 0 0 0 3px rgba(231, 76, 60, 0.2); }}
    .must-have th {{ background: #e74c3c; }}
    .nice-to-have th {{ background: #3498db; }}
    .compliance th {{ background: #95a5a6; }}
    .status-pass {{ color: #27ae60; font-weight: 600; }}
    .status-fail {{ color: #e74c3c; font-weight: 600; }}
    .tag {{ display: inline-block; padding: 8px 14px; margin: 4px; background: #3498db; color: white; border-radius: 6px; font-size: 13px; font-weight: 500; }}
    .tag.gap {{ background: #e74c3c; }}
    .summary-label {{ font-weight: 600; margin: 20px 0 10px; display: block; font-size: 15px; }}
    .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e1e8ed; text-align: center; color: #7f8c8d; font-size: 12px; }}
    @media print {{ body {{ background: white; }} .container {{ box-shadow: none; }} }}
  </style>
</head>
<body>
  <div class="container">
    <h1>{candidate_name}</h1>
    <div class="subtitle">Candidate Evaluation Report</div>
    
    <div class="info-grid">
      <div><div class="info-label">Position</div><div class="info-value">{position}</div></div>
      <div><div class="info-label">Overall Score</div><div class="info-value" style="color: #27ae60;">{overall_score}/100</div></div>
      <div><div class="info-label">Recommendation</div><div class="info-value"><span class="score-badge {badge_class}">{recommendation}</span></div></div>
      <div><div class="info-label">Report Date</div><div class="info-value">{report_date}</div></div>
    </div>
    
    <h2>Executive Summary</h2>
    <div class="summary-box">{executive_summary}</div>
"""
    
    if compliance:
        html += '<h2>Compliance Requirements</h2><table class="compliance"><thead><tr><th style="width: 35%">Requirement</th><th style="width: 15%">Status</th><th style="width: 50%">Details</th></tr></thead><tbody>'
        for item in compliance:
            status = item.get("status", "NOT_ASSESSED")
            status_class = get_status_class(status)
            html += f'<tr><td><strong>{item.get("item", "")}</strong></td><td class="{status_class}" style="text-align: center;">{status}</td><td style="font-size: 13px;">{item.get("details", "")}</td></tr>'
        html += '</tbody></table>'
    
    if must_have:
        html += f'<h2>Must-Have Requirements ({detailed_json.get("must_have_weight", 90)}% Weight)</h2><table class="must-have"><thead><tr><th style="width: 38%">Requirement</th><th style="width: 10%">Score</th><th style="width: 8%">Weight</th><th style="width: 44%">Evidence</th></tr></thead><tbody>'
        for item in must_have:
            score = item.get("score", 0)
            weight = item.get("weight", 0)
            dot_class = get_score_dot(score, 5)
            html += f'<tr><td><strong>{item.get("requirement", "")}</strong></td><td style="text-align: center; font-weight: 600;"><span class="score-dot {dot_class}"></span>{score}/5</td><td style="text-align: center;">{weight}%</td><td style="font-size: 13px;">{item.get("evidence", "")}</td></tr>'
        html += '</tbody></table>'
    
    if nice_to_have:
        html += f'<h2>Nice-to-Have Skills ({detailed_json.get("nice_to_have_weight", 10)}% Weight)</h2><table class="nice-to-have"><thead><tr><th style="width: 38%">Skill</th><th style="width: 10%">Score</th><th style="width: 8%">Weight</th><th style="width: 44%">Evidence</th></tr></thead><tbody>'
        for item in nice_to_have:
            score = item.get("score", 0)
            weight = item.get("weight", 0)
            dot_class = get_score_dot(score, 5)
            html += f'<tr><td><strong>{item.get("skill", "")}</strong></td><td style="text-align: center; font-weight: 600;"><span class="score-dot {dot_class}"></span>{score}/5</td><td style="text-align: center;">{weight}%</td><td style="font-size: 13px;">{item.get("evidence", "")}</td></tr>'
        html += '</tbody></table>'
    
    html += '<h2>Assessment Summary</h2>'
    if key_strengths:
        html += '<span class="summary-label">🌟 Key Strengths:</span><div>'
        for strength in key_strengths:
            html += f'<span class="tag">{strength}</span>'
        html += '</div>'
    
    if development_areas:
        html += '<span class="summary-label">📈 Development Areas:</span><div>'
        for area in development_areas:
            html += f'<span class="tag gap">{area}</span>'
        html += '</div>'
    
    html += f'<div class="footer">Generated by {generated_by} • {report_date}<br>Candidate ID: {candidate_id}</div></div></body></html>'
    
    return html


# =========================
# Helper functions
# =========================
def load_job_description(job_id: str) -> str:
    """Load job description from various sources (in priority order)."""
    
    # Priority 1: Dedicated JD file for this job
    jd_file_specific = Path(f"offline_input/jd_{job_id}.txt")
    if jd_file_specific.exists():
        return jd_file_specific.read_text(encoding="utf-8")
    
    # Priority 2: Generic JD file
    jd_file_generic = Path("offline_input/jd.txt")
    if jd_file_generic.exists():
        return jd_file_generic.read_text(encoding="utf-8")
    
    # Priority 3: JD embedded in offline job JSON
    offline_json = Path(f"offline_input/job_{job_id}.json")
    if offline_json.exists():
        try:
            import json
            with offline_json.open("r", encoding="utf-8") as f:
                data = json.load(f)
                jd_text = data.get("jd_text", "")
                if jd_text:
                    print(f"  📄 Loaded JD from {offline_json}")
                    return jd_text
        except Exception as e:
            print(f"  ⚠ Failed to read JD from JSON: {e}")
    
    # No JD found
    print(f"  ⚠ No JD found for job {job_id}")
    return ""


def get_resume_path(candidate: Dict[str, Any]) -> Optional[Path]:
    """Get resume path from candidate data."""
    
    candidate_id = candidate.get("candidate_id", "")
    
    # Check if resume_local_path is in candidate data
    resume_local = candidate.get("resume_local_path", "")
    if resume_local:
        path = Path(resume_local)
        if path.exists():
            return path
    
    # Check output/resumes folder
    resumes_dir = Config.OUTPUT_DIR / "resumes"
    if resumes_dir.exists():
        for ext in [".pdf", ".docx", ".doc"]:
            path = resumes_dir / f"{candidate_id}{ext}"
            if path.exists():
                return path
    
    # Check offline_input/resumes folder
    offline_resumes = Path("offline_input/resumes")
    if offline_resumes.exists():
        for file in offline_resumes.glob(f"*{candidate_id}*"):
            if file.suffix.lower() in ['.pdf', '.docx', '.doc']:
                return file
        
        # Try by name
        full_name = candidate.get("full_name", "")
        if full_name:
            name_safe = re.sub(r'[^\w\s-]', '', full_name).replace(' ', '_')
            for file in offline_resumes.glob(f"*{name_safe}*"):
                if file.suffix.lower() in ['.pdf', '.docx', '.doc']:
                    return file
    
    return None


# =========================
# Main
# =========================
def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 generate_detailed_reports.py <JOB_ID>")
        return 2
    
    job_id = sys.argv[1].strip()
    
    try:
        Config.validate()
        supabase = SupabaseClient()
        embedder = EmbeddingClient()
        openai_client = OpenAI(api_key=Config.OPENAI_API_KEY)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    
    Config.ensure_dirs()
    
    scored_csv = Config.get_scored_csv_path(job_id)
    if not scored_csv.exists():
        print(f"ERROR: Scored CSV not found: {scored_csv}")
        print("Run python8.py first to generate scored data.")
        return 2
    
    try:
        rubric = load_rubric_yaml(job_id)
        print(f"Loaded rubric: {Config.get_rubric_path(job_id)}")
        rubric_structure = parse_rubric_structure(rubric)
    except Exception as e:
        print(f"ERROR: Failed to load rubric: {e}")
        return 2
    
    # Note: JD text is NOT loaded here - rubric is the single source of truth for scoring
    # JD is only stored in job_3419430.json for recruiter reference
    
    with scored_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        candidates = list(reader)
    
    total_candidates = len(candidates)
    min_score = Config.MIN_SCORE_FOR_REPORT
    high_scorers = [c for c in candidates if float(c.get("ai_score", 0)) >= min_score]
    
    generated_count = 0
    uploaded_count = 0
    
    print(f"\n{'='*70}")
    print(f"Generating Detailed AI-Powered Reports for Job {job_id}")
    print(f"{'='*70}")
    print(f"Total candidates: {total_candidates}")
    print(f"Candidates scoring ≥ {min_score}: {len(high_scorers)}")
    print(f"{'='*70}\n")

    
    for candidate in high_scorers:
        ai_score = float(candidate.get("ai_score", 0))
        candidate_id = candidate.get("candidate_id", "")
        full_name = candidate.get("full_name", "Unknown")
        
        print(f"Processing: {full_name} (Score: {ai_score}, ID: {candidate_id})")
        
        try:
            resume_path = get_resume_path(candidate)
            if not resume_path:
                print(f"  ⚠ Resume not found, skipping")
                continue
            
            print(f"  📄 Resume: {resume_path}")
            
            resume_text = extract_resume_text(resume_path)
            if not resume_text:
                print(f"  ⚠ Could not extract text, skipping")
                continue
            
            detailed_json = generate_detailed_json_with_ai(
                candidate, rubric, rubric_structure, resume_text, openai_client
            )
            
            json_path = Config.REPORTS_DIR / f"candidate_{candidate_id}_report.json"
            with json_path.open("w", encoding="utf-8") as f:
                json.dump(detailed_json, f, ensure_ascii=False, indent=2)
            
            html_content = generate_html_report(detailed_json)
            html_path = Config.REPORTS_DIR / f"candidate_{candidate_id}_report.html"
            with html_path.open("w", encoding="utf-8") as f:
                f.write(html_content)
            
            generated_count += 1
            print(f"  ✓ Generated: {json_path.name}, {html_path.name}")
            
            cache_key = candidate.get("cache_key", "")
            
            # Update Supabase (candidates table uses match_id as primary key)
            match_id = (candidate.get("match_id") or "").strip() or f"{job_id}-{candidate_id}"
            if update_supabase_html_and_embeddings(
                match_id,
                int(candidate_id),
                int(job_id),
                detailed_json,
                html_path,
                resume_text,
                supabase,
                embedder,
            ):
                uploaded_count += 1
                print(f"  ✓ Uploaded to Supabase & Generated Embeddings")
            else:
                print(f"  ✗ Supabase upload failed")
        
        except Exception as e:
            print(f"  ✗ Error: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\n{'='*70}")
    print(f"AI-Powered Report Generation Complete")
    print(f"{'='*70}")
    print(f"Generated: {generated_count} reports (REAL AI scoring - no placeholders!)")
    print(f"Uploaded: {uploaded_count} to Supabase with Embeddings")
    print(f"Output: {Config.REPORTS_DIR}/")
    print(f"{'='*70}\n")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""generate_offline_input.py

Generates an offline input JSON file for python8.py from:
- A folder of CV files (PDF/DOCX)
- A job description (text file or string)
- A rubric YAML file

Uses OpenAI API to extract candidate information (name, email) from CVs.

Usage:
  python3 generate_offline_input.py --job-id 3419430 --job-name "Generative AI Engineer (MY)" --cv-folder ./resumes --jd-file jd.txt --rubric rubrics/rubric_3419430.yaml
  python3 generate_offline_input.py --job-id 3419430 --job-name "GenAI Engineer" --cv-folder ./resumes --jd-text "Role: GenAI Engineer..." --rubric rubrics/rubric_3419430.yaml --org-id 312677 --org-name "Oxydata"

Output:
  offline_input/job_{JOB_ID}.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

# Import from consolidated modules
from config import Config
from utils import extract_resume_text


# =========================
# OpenAI extraction
# =========================
def extract_candidate_info_with_ai(resume_text: str, filename: str, client: OpenAI) -> Dict[str, Any]:
    """Use OpenAI to extract candidate name and email from resume text."""
    
    # Truncate resume text to avoid token limits
    resume_text = resume_text[:Config.MAX_RESUME_CHARS_INFO_EXTRACTION]
    
    prompt = f"""Extract the candidate's information from this resume text.

Resume text:
{resume_text}

Return ONLY a JSON object with this exact structure:
{{
    "full_name": "candidate's full name",
    "email": "candidate's email address"
}}

Rules:
- Extract the primary/full name (not just first name)
- Extract a valid email address if present
- If email is not found, use "noemail@example.com"
- If name is unclear, use the filename as fallback
- Return ONLY the JSON object, no other text

Filename for fallback: {filename}"""

    try:
        response = client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise data extraction assistant. Extract candidate information from resumes and return ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=200
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Try to extract JSON from response (in case model adds markdown)
        json_match = re.search(r'\{[^}]+\}', result_text, re.DOTALL)
        if json_match:
            result_text = json_match.group(0)
        
        result = json.loads(result_text)
        
        return {
            "full_name": result.get("full_name", extract_name_from_filename(filename)),
            "email": result.get("email", "noemail@example.com")
        }
        
    except Exception as e:
        print(f"[WARN] AI extraction failed for {filename}: {e}")
        # Fallback to filename parsing
        return {
            "full_name": extract_name_from_filename(filename),
            "email": "noemail@example.com"
        }


# =========================
# Fallback extraction from filename
# =========================
def extract_name_from_filename(filename: str) -> str:
    """
    Extract candidate name from filename as fallback.
    Examples:
      "125417709-Dimuthu Pahindra.pdf" -> "Dimuthu Pahindra"
      "John_Doe_CV.pdf" -> "John Doe CV"
      "resume.pdf" -> "resume"
    """
    # Remove extension
    name = Path(filename).stem
    
    # Remove leading ID if present (e.g., "125417709-")
    name = re.sub(r"^\d+-", "", name)
    
    # Replace underscores and multiple spaces
    name = name.replace("_", " ").strip()
    name = re.sub(r"\s+", " ", name)
    
    return name if name else "Unknown"


def generate_candidate_id(filename: str, index: int) -> int:
    """
    Generate a pseudo candidate ID from filename.
    """
    # Try to extract numeric ID from filename (e.g., "125417709-Name.pdf")
    match = re.match(r"^(\d+)", filename)
    if match:
        return int(match[1])
    
    # Otherwise, generate from hash + index to avoid collisions
    hash_val = abs(hash(filename)) % 1000000
    return 100000000 + (hash_val * 1000) + index


# =========================
# File operations
# =========================
def get_cv_files(cv_folder: Path) -> List[Path]:
    """Get all CV files from folder (PDF, DOCX, DOC)."""
    if not cv_folder.exists():
        raise FileNotFoundError(f"CV folder not found: {cv_folder}")
    
    if not cv_folder.is_dir():
        raise ValueError(f"CV folder path is not a directory: {cv_folder}")
    
    cv_files = []
    for ext in Config.CV_EXTENSIONS:
        cv_files.extend(cv_folder.glob(f"*{ext}"))
    
    cv_files.sort()  # Consistent ordering
    
    if not cv_files:
        raise ValueError(f"No CV files found in {cv_folder} with extensions: {Config.CV_EXTENSIONS}")
    
    return cv_files


def load_jd_text(jd_file: Optional[Path] = None, jd_text: Optional[str] = None) -> str:
    """Load job description from file or use provided text."""
    if jd_text:
        return jd_text.strip()
    
    if jd_file:
        if not jd_file.exists():
            raise FileNotFoundError(f"JD file not found: {jd_file}")
        return jd_file.read_text(encoding="utf-8").strip()
    
    raise ValueError("Either --jd-file or --jd-text must be provided")


def validate_rubric_file(rubric_path: Path) -> str:
    """Validate rubric file exists and return relative path."""
    if not rubric_path.exists():
        raise FileNotFoundError(f"Rubric file not found: {rubric_path}")
    
    # Return relative path from current directory
    try:
        rel_path = rubric_path.relative_to(Path.cwd())
        return str(rel_path)
    except ValueError:
        # If not relative, return absolute path
        return str(rubric_path)


def generate_timestamp() -> str:
    """Generate ISO 8601 timestamp with +08:00 timezone (Malaysia)."""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat()


def copy_cv_to_offline_folder(cv_file: Path, candidate_id: int, full_name: str) -> str:
    """Copy CV file to offline_input/resumes/ with standardized name."""
    import shutil
    
    resumes_dir = Config.OFFLINE_INPUT_DIR / "resumes"
    resumes_dir.mkdir(parents=True, exist_ok=True)
    
    # Create standardized filename
    safe_name = re.sub(r'[^\w\s-]', '', full_name).strip().replace(' ', ' ')
    ext = cv_file.suffix
    new_filename = f"{candidate_id}-{safe_name}{ext}"
    
    dest_path = resumes_dir / new_filename
    
    # Check if source and destination are the same (avoid Windows file lock)
    if cv_file.resolve() == dest_path.resolve():
        # File is already in the correct location, just return the path
        return f"offline_input/resumes/{new_filename}"
    
    # Copy file only if different locations
    shutil.copy2(cv_file, dest_path)
    
    # Return relative path for JSON
    return f"offline_input/resumes/{new_filename}"


# =========================
# Main logic
# =========================
def process_cv_file(
    cv_file: Path,
    index: int,
    client: OpenAI,
    copy_files: bool = False,
    timestamp: str = None
) -> Dict[str, Any]:
    """Process a single CV file and return candidate entry."""
    
    print(f"Processing [{index + 1}]: {cv_file.name}...", end=" ")
    
    # Extract text from CV using shared utility
    resume_text = extract_resume_text(cv_file)
    
    if not resume_text.strip():
        print("⚠️  No text extracted (possibly scanned PDF)")
        candidate_info = {
            "full_name": extract_name_from_filename(cv_file.name),
            "email": "noemail@example.com"
        }
    else:
        # Use AI to extract candidate info
        candidate_info = extract_candidate_info_with_ai(resume_text, cv_file.name, client)
        print(f"✓ {candidate_info['full_name']}")
    
    # Generate candidate ID
    candidate_id = generate_candidate_id(cv_file.name, index)
    
    # Copy file to offline folder if requested, otherwise use relative path
    if copy_files:
        resume_local_path = copy_cv_to_offline_folder(cv_file, candidate_id, candidate_info['full_name'])
    else:
        # Use relative path from current directory
        try:
            resume_local_path = str(cv_file.relative_to(Path.cwd()))
        except ValueError:
            # If not relative to cwd, just use the filename in offline_input/resumes
            resume_local_path = f"offline_input/resumes/{cv_file.name}"
    
    return {
        "candidate_id": candidate_id,
        "full_name": candidate_info["full_name"],
        "email": candidate_info["email"],
        "resume_local_path": resume_local_path,
        "resume_file": "",
        "created_at": timestamp,
        "updated_at": timestamp
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate offline input JSON for python8.py with AI-extracted candidate information"
    )
    
    # Required arguments
    parser.add_argument("--job-id", required=True, help="Manatal Job ID")
    parser.add_argument("--job-name", required=True, help="Job position name")
    parser.add_argument("--cv-folder", required=True, help="Folder containing CV files (PDF/DOCX)")
    parser.add_argument("--rubric", required=True, help="Path to rubric YAML file")
    
    # JD: either file or text
    jd_group = parser.add_mutually_exclusive_group(required=True)
    jd_group.add_argument("--jd-file", help="Path to job description text file")
    jd_group.add_argument("--jd-text", help="Job description text (inline)")
    
    # Optional arguments
    parser.add_argument("--org-id", type=int, help="Organisation ID")
    parser.add_argument("--org-name", help="Organisation name")
    parser.add_argument("--stage-name", default=Config.TARGET_STAGE_NAME, 
                       help=f"Stage name (default: {Config.TARGET_STAGE_NAME})")
    parser.add_argument("--output", help="Output JSON file path (default: offline_input/job_{JOB_ID}.json)")
    parser.add_argument("--copy-files", action="store_true", 
                       help="Copy CV files to offline_input/resumes/ (default: use files in place)")
    
    args = parser.parse_args()
    
    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    
    try:
        # Initialize OpenAI client
        client = OpenAI(api_key=Config.OPENAI_API_KEY)
        
        # Load inputs
        cv_folder = Path(args.cv_folder).expanduser().resolve()
        cv_files = get_cv_files(cv_folder)
        
        jd_file = Path(args.jd_file).expanduser().resolve() if args.jd_file else None
        jd_text = load_jd_text(jd_file=jd_file, jd_text=args.jd_text)
        
        rubric_path = Path(args.rubric).expanduser().resolve()
        rubric_rel_path = validate_rubric_file(rubric_path)
        
        print(f"\n{'='*60}")
        print(f"Job ID: {args.job_id}")
        print(f"Job Name: {args.job_name}")
        print(f"CV Files: {len(cv_files)}")
        print(f"Rubric: {rubric_rel_path}")
        print(f"{'='*60}\n")
        
        # Generate timestamp
        timestamp = generate_timestamp()
        
        # Process each CV
        candidates = []
        for index, cv_file in enumerate(cv_files):
            try:
                candidate = process_cv_file(
                    cv_file,
                    index,
                    client,
                    copy_files=args.copy_files,
                    timestamp=timestamp
                )
                candidates.append(candidate)
            except Exception as e:
                print(f"✗ Error: {e}")
                continue
        
        if not candidates:
            print("\nERROR: No candidates were successfully processed.", file=sys.stderr)
            return 2
        
        # Build JSON structure
        json_data = {
            "job_id": args.job_id,
            "job_name": args.job_name,
            "rubric_meta": {
                "rubric_file": rubric_rel_path
            },
            "jd_text": jd_text,
            "stage_name": args.stage_name,
            "candidates": candidates
        }
        
        # Add optional fields
        if args.org_id:
            json_data["organisation_id"] = args.org_id
        if args.org_name:
            json_data["organisation_name"] = args.org_name
        
        # Determine output path using Config
        if args.output:
            output_path = Path(args.output).expanduser()
        else:
            output_path = Config.get_offline_json_path(args.job_id)
        
        # Write JSON file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        
        print(f"\n{'='*60}")
        print(f"✅ Success!")
        print(f"{'='*60}")
        print(f"Processed: {len(candidates)} candidates")
        print(f"Output: {output_path}")
        if args.copy_files:
            print(f"CV files copied to: offline_input/resumes/")
        else:
            print(f"CV files referenced in place (not copied)")
        print(f"\nNext steps:")
        print(f"  python3 run_pipeline_complete.py --job-id {args.job_id}")
        print(f"{'='*60}\n")
        
        return 0
        
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

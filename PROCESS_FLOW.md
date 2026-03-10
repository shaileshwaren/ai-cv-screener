# Current Process Flow

## 1. When you open the Render webpage

```
You open:  https://recruitment-pipeline-render.onrender.com
                │
                ▼
         Render runs app.py (FastAPI)
                │
                ▼
         GET / → returns the "Run AI Scoring" UI (HTML page)
                │
                ▼
         You see a form with Job ID input + Run button
```

---

## 2. Pipeline flow (when you click Run or call POST /run)

```
  POST /run/form  (job_ids, stage, optional rubric files)
        │
        ▼
  app.py starts online_pipeline.py in a background thread
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  online_pipeline.py  (for each job_id)                          │
  │                                                                  │
  │  STEP 0: generate_rubric.py  (rubric check / generate)          │
  │          • Fetches job description from Manatal API             │
  │          • Checks for existing local rubric file first          │
  │          • If missing: calls OpenAI GPT-4o to generate rubric   │
  │          • Saves to rubrics/rubric_{job_id}.json                │
  │          • Can also upsert into Airtable Rubric table            │
  │                                                                  │
  │  STEP 1: python8.py  (AI scoring)                               │
  │          • Fetches candidates from Manatal API (stage filter)   │
  │          • Loads rubric from local file → Airtable fallback      │
  │          • Tier 1: quick score with GPT-4o-mini                 │
  │          • Writes scored CSV/JSON to output/upload/             │
  │                                                                  │
  │  STEP 2: upload_airtable.py  (Airtable upsert)                  │
  │          • Reads scored CSV                                      │
  │          • Upserts rows into Airtable Candidate table           │
  │            (create new or update existing, keyed by match_id)   │
  │          • Attaches CV via public URL (online) or direct upload  │
  │          • Attaches rubric_text to each record                   │
  │                                                                  │
  │  STEP 3: generate_detailed_reports.py  (Tier 2 re-score)        │
  │          • For candidates with score ≥ MIN_SCORE_FOR_REPORT     │
  │          • Re-scores with detailed per-criterion prompt          │
  │          • Generates detailed JSON + HTML report locally         │
  │          • Uploads HTML as attachment → ai_report_html field     │
  │          • Stores tier2_score + tier2_status + ai_detailed_json  │
  └─────────────────────────────────────────────────────────────────┘
        │
        ▼
  Airtable base app285aKVVr7JYL43
        │
        ├── Candidate table (tblJ2OkvaWI7vi0vI)
        │      full_name, email, job_id, candidate_id
        │      tier1_score, tier2_score, tier2_status
        │      ai_summary, ai_strengths, ai_gaps
        │      ai_report_html (attachment), cv_text, rubric_text
        │
        ├── Rubric table (tblZgr3F6DWEOorG7)
        │      rubric_name (= job_id), rubric_json
        │
        └── Job table (tblCV6w4fGex9VgzK)
               job_id, job_name, jd, client_id, rubric
```

---

## 3. Airtable schema overview

| Table | ID | Key fields |
|---|---|---|
| **Candidate** | `tblJ2OkvaWI7vi0vI` | full_name, match_id (formula), job_id, candidate_id, tier1_score, tier2_score, tier2_status, ai_summary, ai_strengths, ai_gaps, ai_report_html (attachment), cv_text, rubric_text, match_stage_name |
| **Rubric** | `tblZgr3F6DWEOorG7` | rubric_name (primary = job_id), rubric_json |
| **Job** | `tblCV6w4fGex9VgzK` | job_id (primary), job_name, jd, rubric, client_id, client_name |

`match_id` is a **formula field** in Airtable: `{job_id} & "-" & {candidate_id}`

---

## 4. Step-by-step summary

| Step | Script | What happens |
|---|---|---|
| **0** | `generate_rubric.py` | Fetches JD from Manatal → GPT-4o generates structured rubric JSON → saved locally + optionally to Airtable Rubric table |
| **1** | `python8.py` | Fetches candidates from Manatal → loads rubric → GPT-4o-mini scores each resume → writes `output/upload/manatal_job_{id}_scored.csv` |
| **2** | `upload_airtable.py` | Reads scored CSV → upserts into Airtable Candidate table (create/update by match_id) → attaches CV and rubric text |
| **3** | `generate_detailed_reports.py` | For candidates scoring ≥ `MIN_SCORE_FOR_REPORT`: GPT-4o detailed re-score → HTML report → uploaded as Airtable attachment → `tier2_score` / `tier2_status` updated |

---

## 5. Environment variables required

| Variable | Used by |
|---|---|
| `MANATAL_API_TOKEN` | python8.py, generate_rubric.py (fetch JD + candidates) |
| `OPENAI_API_KEY` | python8.py, generate_detailed_reports.py (scoring + reports) |
| `AIRTABLE_TOKEN` | upload_airtable.py, generate_detailed_reports.py, app.py |
| `AIRTABLE_BASE_ID` | All Airtable operations (default: `app285aKVVr7JYL43`) |
| `AIRTABLE_TABLE_ID` | Candidate table (default: `tblJ2OkvaWI7vi0vI`) |
| `AIRTABLE_RUBRIC_TABLE_ID` | Rubric table (default: `tblZgr3F6DWEOorG7`) |
| `MIN_SCORE_FOR_REPORT` | Tier 2 cutoff (default: 75) |
| `TARGET_STAGE_NAME` | Manatal pipeline stage to pull (default: `New Candidates`) |

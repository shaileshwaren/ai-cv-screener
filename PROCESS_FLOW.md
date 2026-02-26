# Current process flow

## 1. When you open the Render webpage

```
You open:  https://recruitment-pipeline-m841.onrender.com
                │
                ▼
         Render runs the app connected to your service
                │
    ┌───────────┴───────────┐
    │                       │
    ▼                       ▼
 If connected repo     If a different repo
 is THIS project      is connected (e.g. another
 (with app.py below)   "Recruitment Pipeline API")
    │                       │
    ▼                       ▼
 GET / returns          GET / returns JSON:
 the Run Pipeline      {"service":"Recruitment Pipeline API",
 UI (HTML page with     "status":"idle", "running_jobs":[], ...}
 job IDs + Run button)  or /status returns "APP_API_KEY not configured"
    │                       │
    ▼                       ▼
 You see the UI.        You see JSON or an error (no UI).
```

**To see the UI at that URL:** the Render service must use **this repo** (the one containing this `app.py` and `PROCESS_FLOW.md`). In Render Dashboard → your service → Settings → connect this repository and redeploy.

---

## 2. Pipeline flow (when you click Run or run from CLI)

Once the Run Pipeline UI is loaded (or you call `POST /run`), this is what runs in the background:

```
  POST /run  (job_ids e.g. "3419430")
        │
        ▼
  app.py starts online_pipeline.py in a background thread
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  online_pipeline.py  (for each job_id)                           │
  │                                                                  │
  │  STEP 1: python8.py  (AI scoring)                                │
  │          • Fetches candidates from Manatal API                  │
  │          • Loads rubric YAML (rubrics/rubric_{job_id}.yaml)     │
  │          • Scores with OpenAI GPT-4o-mini                        │
  │          • Writes scored CSV/JSON to output/upload/              │
  │                                                                  │
  │  STEP 2: upload_supabase.py                                      │
  │          • Reads scored CSV                                      │
  │          • Upserts rows into Supabase candidates table           │
  │          • Uploads CVs to Supabase Storage                       │
  │          • Generates embeddings → candidate_chunks                │
  │          • Syncs NocoDB columns (add missing)                     │
  │          • Reloads PostgREST schema                               │
  │                                                                  │
  │  STEP 3: generate_detailed_reports.py                            │
  │          • For candidates with score ≥ MIN_SCORE_FOR_REPORT      │
  │          • Re-scores with detailed prompt                        │
  │          • Generates HTML report, uploads to Storage             │
  │          • Updates ai_report_html, embeddings                     │
  └─────────────────────────────────────────────────────────────────┘
        │
        ▼
  Supabase (candidates + candidate_chunks + Storage)
        │
        ▼
  NocoDB (live sync with Supabase — view/filter candidates)
```

---

## 3. Summary

| Step | What happens |
|------|----------------|
| Open Render URL | Render serves whatever app is connected to that service. This project’s app serves an HTML “Run Pipeline” UI at `/`. |
| Click Run pipeline | Browser sends `POST /run` with job IDs → app starts `online_pipeline.py` in background → you see “Pipeline started” and can watch logs in Render. |
| Pipeline (per job) | 1) python8: Manatal → score with OpenAI → CSV/JSON. 2) upload_supabase: CSV → Supabase + Storage + embeddings + NocoDB sync. 3) generate_detailed_reports: high scorers → HTML report → Storage + embeddings. |
| Result | Data in Supabase and NocoDB; CVs and reports in Storage. |

To fix “I only see JSON or error on the Render page”: connect **this repository** to your Render web service and redeploy so `/` serves the UI from this project’s `app.py`.

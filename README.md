# Supabase-NocoDB Pipeline

A recruitment pipeline that fetches candidate data from the **Manatal API**, scores it with AI, and writes results **directly to Supabase** — with NocoDB used as the front-end view.

## Data Flow

```
Manatal API
    ↓  (python8.py)
AI Scoring & CSV output
    ↓  (upload_supabase.py)
Supabase (candidates table + Storage + embeddings)
    ↓  (generate_detailed_reports.py)
HTML Reports
```

**No Airtable involved.**

---

## Setup

### 1. Create virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure `.env`

Edit `.env` and confirm all values:

| Variable | Description |
|---|---|
| `MANATAL_API_TOKEN` | Manatal API token |
| `OPENAI_API_KEY` | OpenAI API key |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase service role key |
| `SUPABASE_DB_URL` | Direct PostgreSQL connection string |
| `SUPABASE_STORAGE_BUCKET` | Storage bucket (default: `candidate_files`) |

### 3. Seed rubrics in Supabase

Rubrics are stored in a Supabase table called `rubrics` and are loaded at runtime by job ID.

During development you can:

- Author rubrics locally under `rubrics/` (YAML or JSON), e.g. `rubrics/rubric_<JOB_ID>.json`
- Then run:

```bash
python sync_rubrics_to_supabase.py
```

This will upsert all local rubric files into the `rubrics` table. The online pipeline (`python8.py`) and detailed reports (`generate_detailed_reports.py`) will then fetch rubrics directly from Supabase.

---

## Usage

### Online Pipeline (full run)

```bash
# Single job
python online_pipeline.py 3419430

# Multiple jobs
python online_pipeline.py "3419430, 3261113"

# Skip steps
python online_pipeline.py 3419430 --skip-upload --skip-reports
```

### Upload to Supabase only

```bash
python upload_supabase.py 3419430
```

---

## Project Structure

```
supabase nocodb pipeline/
├── online_pipeline.py          # Main orchestrator
├── upload_supabase.py          # Supabase upsert + embeddings
├── python8.py                  # AI scoring (fetches from Manatal)
├── generate_detailed_reports.py
├── config.py                   # Centralized config
├── utils.py
├── src/
│   ├── supabase_client.py      # Supabase wrapper
│   ├── embedding_client.py     # OpenAI embeddings
│   └── text_processor.py       # PDF/DOCX text extraction
├── rubrics/                    # Per-job YAML rubrics
├── output/                     # Scored CSVs, reports
├── .env                        # Credentials (do not commit)
└── requirements.txt
```

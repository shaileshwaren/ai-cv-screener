# Supabase-NocoDB Recruitment Pipeline

## Project Overview

An **AI-powered recruitment automation system** that streamlines candidate screening by fetching applications from an ATS, scoring them with AI against custom rubrics, storing results in a cloud database, and presenting data through a user-friendly interface.

---

## System Architecture

```
┌─────────────┐
│ Manatal ATS │ (Candidate Source)
└──────┬──────┘
       │ API Fetch
       ▼
┌─────────────────────┐
│   python8.py        │ (AI Scoring Engine)
│   - OpenAI GPT-4o   │
│   - YAML Rubrics    │
│   - Caching System  │
└──────┬──────────────┘
       │ Scored Data
       ▼
┌─────────────────────┐
│ upload_supabase.py  │ (Data Upload)
│   - Upsert Records  │
│   - CV Storage      │
│   - Embeddings      │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│   Supabase          │ (Database + Storage)
│   - PostgreSQL      │
│   - pgvector        │
│   - Storage Bucket  │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ HTML Reports        │ (Detailed Analysis)
│   - Compliance      │
│   - Scoring         │
│   - Recommendations │
└─────────────────────┘
```

---

## Tools & Platforms

### **AI & Machine Learning**
| Tool | Purpose | Version |
|------|---------|---------|
| **OpenAI API** | AI scoring & embeddings | GPT-4o-mini |
| **text-embedding-3-small** | Vector embeddings for semantic search | Latest |

### **Database & Storage**
| Platform | Purpose | Features Used |
|----------|---------|---------------|
| **Supabase** | Primary database & file storage | PostgreSQL, pgvector, Storage, PostgREST |
| **PostgreSQL** | Relational database | v15+ with pgvector extension |
| **pgvector** | Vector similarity search | Embedding storage & hybrid search |

### **External Integrations**
| Service | Purpose | API Version |
|---------|---------|-------------|
| **Manatal** | Applicant Tracking System | Open API v3 |

### **Programming & Frameworks**
| Technology | Purpose | Version |
|------------|---------|---------|
| **Python** | Core language | 3.8+ |
| **python-dotenv** | Environment management | 1.0.0+ |
| **requests** | HTTP client | 2.32.0+ |
| **psycopg2-binary** | PostgreSQL adapter | Latest |
| **supabase-py** | Supabase client | 2.10.0 |

### **Document Processing**
| Library | Purpose | Formats |
|---------|---------|---------|
| **pypdf** | PDF text extraction | .pdf |
| **python-docx** | Word document parsing | .docx, .doc |
| **tiktoken** | Token counting | OpenAI models |

### **Data Formats**
| Format | Usage |
|--------|-------|
| **YAML/JSON** | Rubric authoring in `rubrics/` (synced into Supabase `rubrics` table) |
| **JSON** | Data interchange, caching, API responses |
| **CSV** | Scored candidate exports |
| **HTML** | Detailed candidate reports |

---

## Key Features

### 1. **AI-Powered Scoring**
- Uses OpenAI GPT-4o-mini for intelligent candidate evaluation
- YAML-based rubrics with semantic ontology (skill aliases/synonyms)
- Structured scoring: Compliance → Must-Have → Nice-to-Have
- Caching system prevents re-scoring (rubric + candidate hash)

### 2. **Semantic Search**
- Vector embeddings generated for all candidate resumes
- Stored in Supabase using pgvector extension
- Enables semantic similarity search across candidates
- Hybrid search: keyword + semantic matching

### 3. **Multi-Job Processing**
- Process multiple job postings in a single run
- Job-specific rubrics (e.g., `rubric_3419430.yaml`)
- Parallel processing support
- Stage-based filtering (e.g., "Processing" stage)

### 4. **Comprehensive Reporting**
- Detailed HTML reports with visual scoring indicators
- Compliance checks (Pass/Fail gates)
- Weighted scoring for must-have requirements
- Strengths and gaps analysis
- Uploaded to Supabase Storage with public URLs

---

## Project Structure

```
supabase nocodb pipeline/
│
├── 📄 Core Pipeline Scripts
│   ├── online_pipeline.py          # Main orchestrator (multi-job)
│   ├── python8.py                  # AI scoring engine
│   ├── upload_supabase.py          # Supabase upsert + embeddings
│   └── generate_detailed_reports.py # HTML report generator
│
├── 📄 Offline Mode Scripts
│   ├── offline_pipeline.py         # Local file processing
│   └── generate_offline_input.py   # Offline input generator
│
├── ⚙️ Configuration
│   ├── config.py                   # Centralized settings
│   ├── .env                        # API keys & credentials
│   ├── requirements.txt            # Python dependencies
│   └── online_config.txt           # Pipeline settings
│
├── 🔧 Utilities
│   ├── utils.py                    # Resume parsing, hashing
│   └── src/
│       ├── supabase_client.py      # Database wrapper
│       ├── embedding_client.py     # OpenAI embeddings
│       └── text_processor.py       # PDF/DOCX extraction
│
├── 📋 Rubrics (authoring)
│   └── rubrics/
│       ├── rubric_3419430.json     # Gen AI Engineer rubric (synced to Supabase)
│       └── rubric_3261113.json     # Other job rubrics
│
├── 📂 Input Data
│   ├── local_input/                # Local candidate files
│   │   └── job_<ID>/
│   │       ├── job_<ID>.json       # Job metadata
│   │       ├── jd_<ID>.txt         # Job description
│   │       ├── config_<ID>.txt     # Job config
│   │       └── *.pdf, *.docx       # Candidate resumes
│   └── offline_input/              # Offline processing
│
├── 📤 Output
│   ├── output/
│   │   ├── scored_cache.json       # Scoring cache
│   │   ├── upload/                 # Scored CSVs & JSONs
│   │   ├── reports/                # HTML reports
│   │   └── resumes/                # Downloaded CVs
│
└── 🚀 Batch Scripts (Windows)
    ├── setup.bat                   # Environment setup
    ├── run_online.bat              # Run online pipeline
    └── run_offline.bat             # Run offline pipeline
```

---

## Data Flow

### **1. Candidate Ingestion**
```
Manatal API → Fetch candidates in "Processing" stage
            → Download resumes (PDF/DOCX)
            → Extract text content
```

### **2. AI Scoring**
```
Resume Text + Job Description + YAML Rubric
            ↓
OpenAI GPT-4o-mini (Structured Prompt)
            ↓
JSON Response:
  - ai_score (0-100)
  - ai_summary (60 words)
  - ai_strengths (comma-separated)
  - ai_gaps (comma-separated)
            ↓
Cache (rubric_hash + candidate_id)
```

### **3. Database Storage**
```
Scored Data → Supabase candidates table (19 columns)
            → Upload CV to Storage bucket
            → Generate embeddings (OpenAI)
            → Store in candidate_chunks table
            → Trigger PostgREST schema reload
```

### **4. Report Generation**
```
High-scoring candidates (≥75) → Re-score with detailed prompt
                              → Generate HTML report
                              → Upload to Supabase Storage
                              → Create embeddings
                              → Update ai_report_html field
```

---

## Database Schema

### **Supabase: `candidates` Table**

| Column | Type | Description |
|--------|------|-------------|
| `candidate_id` | INTEGER (PK) | Unique candidate identifier |
| `job_id` | INTEGER | Job posting ID |
| `job_name` | TEXT | Job title |
| `org_id` | INTEGER | Organization ID |
| `org_name` | TEXT | Company name |
| `match_id` | TEXT | Manatal match ID |
| `full_name` | TEXT | Candidate name |
| `email` | TEXT | Contact email |
| `resume_file` | TEXT (URL) | CV file URL |
| `match_stage_name` | TEXT | Current stage (e.g., "Processing") |
| `ai_score` | INTEGER | AI score (0-100) |
| `ai_summary` | TEXT | Brief assessment |
| `ai_strengths` | TEXT | Comma-separated strengths |
| `ai_gaps` | TEXT | Comma-separated gaps |
| `ai_report_html` | TEXT (URL) | Detailed report URL |
| `rubric_version` | TEXT | Rubric version used |
| `rubric_hash` | TEXT | Rubric hash (first 12 chars) |
| `cache_key` | TEXT | Unique cache identifier |
| `updated_at` | TIMESTAMP | Last update time |

### **Supabase: `candidate_chunks` Table**

| Column | Type | Description |
|--------|------|-------------|
| `candidate_id` | INTEGER | Foreign key to candidates |
| `job_id` | INTEGER | Job posting ID |
| `chunk_text` | TEXT | Resume + report text |
| `embedding` | VECTOR(1536) | OpenAI embedding vector |
| `chunk_index` | INTEGER | Chunk sequence number |

---

## Configuration

### **Environment Variables (.env)**

```bash
# Manatal ATS
MANATAL_API_TOKEN=<token>

# OpenAI
OPENAI_API_KEY=<key>
OPENAI_MODEL=gpt-4o-mini

# Supabase
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_KEY=<service_role_key>
SUPABASE_DB_URL=postgresql://postgres.<project>:password@...
SUPABASE_STORAGE_BUCKET=candidate_files

# Pipeline Settings
MIN_SCORE_FOR_REPORT=75
TARGET_STAGE_NAME=Processing
```

### **Rubric Structure (YAML)**

```yaml
rubric_name: "Job_Title_YYYYMMDD"
role_applied: "Job Title"
version: "1.0"
company: "Company Name"
jd_summary: "Brief job description"

# Semantic ontology for skill matching
normalized_terms:
  Python:
    aliases: ["Python3", "Py"]
    related_terms: ["FastAPI", "Django"]

# Pass/Fail gates
compliance:
  - item: "Bachelor's degree required"
  - item: "Work authorization"

# Weighted requirements (90% total)
must_have:
  - requirement: "5+ years Python experience"
    weight: 20
  - requirement: "React.js proficiency"
    weight: 15

# Bonus skills (10% total)
nice_to_have:
  - skill: "Docker experience"
    weight: 3
  - skill: "CI/CD pipelines"
    weight: 2

# Scoring rules
scoring_rules:
  pass_threshold: 70
  floor_rule: "Any must-have < 2 triggers FAIL"
```

---

## Usage

### **Online Mode (Manatal API)**

```bash
# Single job
python online_pipeline.py 3419430

# Multiple jobs
python online_pipeline.py "3419430, 3261113"

# Skip specific steps
python online_pipeline.py 3419430 --skip-upload --skip-reports
```

### **Individual Steps**

```bash
# 1. AI Scoring only
python python8.py 3419430

# 2. Upload to Supabase only
python upload_supabase.py 3419430

# 3. Generate reports only
python generate_detailed_reports.py 3419430

```

### **Offline Mode (Local Files)**

```bash
# Process local candidates
python offline_pipeline.py 3419430

# Generate offline input template
python generate_offline_input.py 3419430
```

---

## Current State

### **Processed Jobs**
- **Job 3419430**: Generative AI Full-stack Engineer (Oxydata)
  - 10 candidates in local input
  - 6 candidates scored and uploaded
  - Score range: 70-85
  - Rubric version: 2.2

### **Database Statistics**
- Supabase: 19 columns in `candidates` table
- Storage: CVs and HTML reports in `candidate_files` bucket
- Embeddings: Vector search enabled via pgvector

---

## Key Advantages

1. **Scalability**: Process hundreds of candidates across multiple jobs
2. **Consistency**: YAML rubrics ensure uniform evaluation criteria
3. **Transparency**: Detailed scoring breakdowns with evidence
4. **Semantic Search**: Find similar candidates using AI embeddings
5. **Caching**: Prevents redundant API calls and costs
6. **Flexibility**: Online (API) and offline (local files) modes
7. **Extensibility**: Modular design allows easy feature additions

---

## Technology Stack Summary

| Layer | Technologies |
|-------|-------------|
| **AI/ML** | OpenAI GPT-4o-mini, text-embedding-3-small |
| **Database** | Supabase (PostgreSQL + pgvector) |
| **Storage** | Supabase Storage (S3-compatible) |
| **Interface** | Supabase Dashboard / any SQL or REST client |
| **Backend** | Python 3.8+, FastAPI concepts |
| **APIs** | Manatal ATS, OpenAI, Supabase REST |
| **Document Processing** | pypdf, python-docx |
| **Data Formats** | YAML, JSON, CSV, HTML |
| **Version Control** | Git (implied) |
| **Deployment** | Local execution, cloud-ready |

---

## Deployment (Render)

The pipeline can run on [Render](https://render.com) as a Web Service and optionally as a Cron Job.

- **Web Service**: Serves `/health` and `POST /run` to trigger the pipeline (runs in background; see logs in Render).
- **Cron Job**: Optional scheduled runs via `run_cron.py` and `RENDER_CRON_JOB_IDS`.

See **[RENDER_DEPLOY.md](RENDER_DEPLOY.md)** for setup, env vars, endpoints, and troubleshooting.

---

## Future Enhancements

- [ ] Real-time candidate notifications
- [ ] Multi-language support for resumes
- [ ] Interview scheduling integration
- [ ] Candidate ranking algorithms
- [ ] Email automation for outreach
- [ ] Analytics dashboard
- [ ] Mobile app integration
- [ ] Webhook support for real-time updates

---

**Last Updated**: February 24, 2026  
**Project Status**: Production-ready  
**Maintainer**: Recruitment Automation Team

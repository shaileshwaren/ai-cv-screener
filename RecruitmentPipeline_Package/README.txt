================================================================================
RECRUITMENT PIPELINE - DISTRIBUTION PACKAGE
================================================================================

QUICK START
-----------

1. Setup
   Run the setup script to create virtual environment and install dependencies:
   
   setup.bat

2. Configure Environment
   The .env file is already configured with API keys.
   If needed, edit .env to update your credentials.

3. Run Pipelines

   OFFLINE PIPELINE (Local CVs)
   
   Double-click: run_offline.bat
   
   You will be prompted to enter job IDs:
   - Single job: 3419430
   - Multiple jobs: 3419430, 3261113
   
   Configuration:
   - local_input/job_{id}/config_{id}.txt - Basic config (job_name, org_id, org_name)
   - local_input/job_{id}/advanced_config_{id}.txt - Optional settings
   - Place CVs in local_input/job_{id}/
   - JD file: local_input/job_{id}/jd_{id}.txt
   - Rubric: rubrics/rubric_{id}.yaml

   ONLINE PIPELINE (Manatal API)
   
   Double-click: run_online.bat
   
   You will be prompted to enter job IDs:
   - Single job: 3419430
   - Multiple jobs: 3419430, 3261113
   
   Configuration:
   - online_config.txt - Stage name (default: "Processing")
   - online_advanced_config.txt - Optional settings

================================================================================
FEATURES
================================================================================

Offline Pipeline:
  - Multi-job processing
  - Local CV extraction (PDF, DOCX)
  - AI scoring against rubrics
  - Airtable upload with attachments
  - Detailed AI-powered reports

Online Pipeline:
  - Multi-job processing
  - Fetch from Manatal API
  - AI scoring against rubrics
  - Airtable upload
  - Detailed AI-powered reports

================================================================================
DIRECTORY STRUCTURE
================================================================================

RecruitmentPipeline_Package/
|
+-- Batch Scripts
|   +-- setup.bat              Setup environment
|   +-- run_offline.bat        Run offline pipeline (prompts for job IDs)
|   +-- run_online.bat         Run online pipeline (prompts for job IDs)
|
+-- Python Scripts
|   +-- offline_pipeline.py    Offline multi-job pipeline
|   +-- online_pipeline.py     Online multi-job pipeline
|   +-- python8.py             AI scoring engine
|   +-- upload_airtable.py     Airtable integration
|   +-- generate_detailed_reports.py - Report generation
|   +-- generate_offline_input.py - CV extraction
|
+-- Configuration
|   +-- .env                   API keys (pre-configured)
|   +-- online_config.txt      Online stage name
|   +-- online_advanced_config.txt - Online optional settings
|   +-- local_input/           Offline job configs & CVs
|   +-- rubrics/               Job rubrics
|
+-- Output
|   +-- output/                Generated outputs
|
+-- Environment
    +-- requirements.txt       Python dependencies

================================================================================
SUPPORT
================================================================================

For issues or questions, contact the development team.

# Deploying on Render

This project runs on [Render](https://render.com) as a **Web Service** (optional **Cron Job** for scheduled runs).

---

## Seeing JSON or an error instead of the Run Pipeline UI?

If opening your Render URL shows **JSON** (`"service":"Recruitment Pipeline API"`, `"status":"idle"`) or an **error** (e.g. `APP_API_KEY is not configured`), Render is running **another app**, not this one.

**To show the Run Pipeline webpage (form with Job IDs + Run button):**

1. In [Render Dashboard](https://dashboard.render.com), open your **Web Service**.
2. Go to **Settings** → **Build & Deploy** → **Repository**.
3. **Connect the repository that contains this project** (this `app.py`, `PROCESS_FLOW.md`, `render.yaml`). If you have multiple repos, pick the one with this codebase.
4. Set the **branch** (e.g. `main`) and save.
5. Go to **Manual Deploy** → **Deploy latest commit**.
6. When the deploy is **Live**, open your Render URL again. You should see the **Run recruitment pipeline** page.

The link to open: **https://your-service-name.onrender.com** (e.g. `https://recruitment-pipeline-render.onrender.com`).

---

## Quick start (new deployment)

1. **Push this repo to GitHub/GitLab/Bitbucket** (if not already).
2. In [Render Dashboard](https://dashboard.render.com): **New → Blueprint**.
3. Connect the repo and select the branch. Render will detect `render.yaml`.
4. **Add environment variables** for the web service (Render will show “Sync” for secrets — add values in the Dashboard):
   - `MANATAL_API_TOKEN`
   - `OPENAI_API_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `SUPABASE_DB_URL`
   - `NOCODB_TOKEN`
   - `NOCODB_BASE_ID`
   - `NOCODB_CANDIDATES_TABLE_ID`
5. **Deploy.** The web service will be live at `https://<your-service>.onrender.com`.

## Web service endpoints

| Endpoint        | Method | Description |
|----------------|--------|-------------|
| `/`            | GET    | **Run Pipeline UI** (webpage with job IDs + Run button) |
| `/health`      | GET    | Health check (used by Render) |
| `/docs`        | GET    | Swagger UI |
| `/run`         | POST   | Start pipeline in background (returns immediately) |
| `/run/sync`    | POST   | Run pipeline and wait for completion (may timeout on long runs) |

### Triggering the pipeline

**Background (recommended):**
```bash
curl -X POST https://<your-service>.onrender.com/run \
  -H "Content-Type: application/json" \
  -d '{"job_ids": "3419430"}'
```

**Multiple jobs:**
```bash
curl -X POST https://<your-service>.onrender.com/run \
  -H "Content-Type: application/json" \
  -d '{"job_ids": "3419430, 3261113"}'
```

**Skip steps:**
```json
{"job_ids": "3419430", "skip_scoring": true, "skip_upload": false, "skip_reports": true}
```

Pipeline output appears in **Render Logs** for the service.

## Optional: scheduled runs (Cron Job)

To run the pipeline on a schedule (e.g. daily):

1. In `render.yaml`, **uncomment** the `cron` service block.
2. Set **RENDER_CRON_JOB_IDS** (e.g. `3419430, 3261113`) in the cron service’s environment, or in the `value` in `render.yaml`.
3. Adjust **schedule** (cron expression). Example: `0 6 * * *` = 06:00 UTC daily.
4. Add the same env vars as the web service to the cron service (in Dashboard or in `render.yaml`).
5. Redeploy. The cron job will run at the given schedule.

Cron runs use `run_cron.py`, which reads `RENDER_CRON_JOB_IDS` and executes `online_pipeline.py`.

## Local run (same as Render)

```bash
pip install -r requirements.txt
# Set .env (same vars as Render)
uvicorn app:app --host 0.0.0.0 --port 8000
# Then: POST http://localhost:8000/run with body {"job_ids": "3419430"}
```

## Timeouts and limits

- **Free tier**: Request timeout is typically ~5 minutes. Use **POST /run** (background) so the request returns immediately; the pipeline continues and logs appear in Render.
- For **POST /run/sync**, only use it for short runs or if you’re on a plan with longer timeouts.

## Troubleshooting

- **Pipeline fails in logs**: Check that all env vars (Manatal, OpenAI, Supabase, NocoDB) are set for the web (or cron) service.
- **Health check failing**: Ensure `PORT` is not overridden; Render sets it automatically.
- **Cron not running**: Confirm the cron service is uncommented in `render.yaml`, has the same env vars, and that `RENDER_CRON_JOB_IDS` is set.

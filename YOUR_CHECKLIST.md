# What you need to do

Repo is ready (git initialized, first commit done). Follow these steps.

---

## 1. Push this project to GitHub â€” **Already done**

Your code is already pushed to **https://github.com/shaileshwaren/recruitment-pipeline-render** (branch `main`). Skip this step.

To push again later (e.g. after edits), use Source Control in Cursor (`Ctrl+Shift+G`): stage, commit, then push.

---

## 2. Point Render at this repo

1. Go to [Render Dashboard](https://dashboard.render.com).
2. Open your **Web Service** (e.g. recruitment-pipeline-render).
3. Go to **Settings** â†’ **Build & Deploy** â†’ **Repository**.
4. Click **Connect repository** (or **Change repository**).
5. Select **recruitment-pipeline-render** (or your GitHub repo name).
6. Set **Branch** to `main` (or the branch you pushed).
7. Save.

---

## 3. Add credentials in Render

1. Same service â†’ **Environment**.
2. Add these variables (use â€œSecretâ€ for tokens and keys):

   | Key | Value (you fill in) |
   |-----|----------------------|
   | MANATAL_API_TOKEN | From Manatal API settings |
   | OPENAI_API_KEY | From OpenAI |
   | SUPABASE_URL | From Supabase project â†’ Settings â†’ API |
   | SUPABASE_KEY | Supabase **service_role** key |
   | SUPABASE_DB_URL | Supabase â†’ Database â†’ Connection string (URI) |
3. Optional: `SUPABASE_STORAGE_BUCKET` (default: `candidate_files`), `TARGET_STAGE_NAME` (default: `Processing`), `MIN_SCORE_FOR_REPORT` (default: `85`).
4. Save.

---

## 4. Redeploy

1. Go to **Manual Deploy** â†’ **Deploy latest commit** (or push to `main` again and let it auto-deploy).
2. Wait until status is **Live**.

---

## 5. Open the webpage

Open your Render URL, e.g.:

**https://recruitment-pipeline-render.onrender.com**

You should see the **Run recruitment pipeline** form. Enter a job ID (e.g. `3419430` or `3261113`), click **Run pipeline**, then check Render **Logs** for progress. Results go to Supabase.

---

## Rubrics

Job IDs `3419430` and `3261113` already have rubrics in `rubrics/`. For any new job ID, add a file `rubrics/rubric_<JOB_ID>.yaml` (see existing rubrics as a template) and commit + push so Render has it.

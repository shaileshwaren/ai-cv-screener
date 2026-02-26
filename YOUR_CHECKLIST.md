# What you need to do

Repo is ready (git initialized, first commit done). Follow these steps.

---

## 1. Push this project to GitHub (or GitLab / Bitbucket)

1. Create a **new repository** on GitHub (e.g. `supabase-nocodb-pipeline`). Do **not** add a README or .gitignore (we already have them).
2. In a terminal, in this folder, run:

   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   git branch -M main
   git push -u origin main
   ```

   Replace `YOUR_USERNAME` and `YOUR_REPO_NAME` with your GitHub username and repo name. Use the HTTPS URL from the “Create repository” page. If you use SSH, use the SSH URL instead.

---

## 2. Point Render at this repo

1. Go to [Render Dashboard](https://dashboard.render.com).
2. Open your **Web Service** (e.g. recruitment-pipeline-m841).
3. Go to **Settings** → **Build & Deploy** → **Repository**.
4. Click **Connect repository** (or **Change repository**).
5. Select the repo you just pushed (e.g. `supabase-nocodb-pipeline`).
6. Set **Branch** to `main` (or the branch you pushed).
7. Save.

---

## 3. Add credentials in Render

1. Same service → **Environment**.
2. Add these variables (use “Secret” for tokens and keys):

   | Key | Value (you fill in) |
   |-----|----------------------|
   | MANATAL_API_TOKEN | From Manatal API settings |
   | OPENAI_API_KEY | From OpenAI |
   | SUPABASE_URL | From Supabase project → Settings → API |
   | SUPABASE_KEY | Supabase **service_role** key |
   | SUPABASE_DB_URL | Supabase → Database → Connection string (URI) |
   | NOCODB_TOKEN | From NocoDB |
   | NOCODB_BASE_ID | Your NocoDB base ID |
   | NOCODB_CANDIDATES_TABLE_ID | Your NocoDB candidates table ID |

3. Optional: `SUPABASE_STORAGE_BUCKET` (default: `candidate_files`), `TARGET_STAGE_NAME` (default: `Processing`), `MIN_SCORE_FOR_REPORT` (default: `85`).
4. Save.

---

## 4. Redeploy

1. Go to **Manual Deploy** → **Deploy latest commit** (or push to `main` again and let it auto-deploy).
2. Wait until status is **Live**.

---

## 5. Open the webpage

Open your Render URL, e.g.:

**https://recruitment-pipeline-m841.onrender.com**

You should see the **Run recruitment pipeline** form. Enter a job ID (e.g. `3419430` or `3261113`), click **Run pipeline**, then check Render **Logs** for progress. Results go to Supabase and NocoDB.

---

## Rubrics

Job IDs `3419430` and `3261113` already have rubrics in `rubrics/`. For any new job ID, add a file `rubrics/rubric_<JOB_ID>.yaml` (see existing rubrics as a template) and commit + push so Render has it.

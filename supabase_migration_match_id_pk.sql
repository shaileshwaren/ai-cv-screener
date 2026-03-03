-- Migration: Make match_id the primary key of candidates
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor) or: python run_supabase_migration.py
--
-- Prerequisites:
--   - candidates table has a match_id column (TEXT).
--   - Existing rows have match_id populated (e.g. "job_id-candidate_id" from Manatal).

-- 1. Drop FK from candidate_chunks so we can drop candidates PK
ALTER TABLE candidate_chunks
  DROP CONSTRAINT IF EXISTS candidate_chunks_candidate_id_fkey;

-- 2. Drop the existing primary key on candidates
ALTER TABLE candidates
  DROP CONSTRAINT IF EXISTS candidates_pkey;

-- 3. Ensure match_id is non-null (backfill from job_id + candidate_id if needed)
UPDATE candidates SET match_id = (job_id::text || '-' || candidate_id::text) WHERE match_id IS NULL OR match_id = '';
ALTER TABLE candidates ALTER COLUMN match_id SET NOT NULL;

-- 4. Set match_id as the new primary key
ALTER TABLE candidates
  ADD PRIMARY KEY (match_id);

-- 5. Keep candidate_id unique so candidate_chunks can reference it, then re-add FK
ALTER TABLE candidates ADD CONSTRAINT candidates_candidate_id_unique UNIQUE (candidate_id);
ALTER TABLE candidate_chunks
  ADD CONSTRAINT candidate_chunks_candidate_id_fkey
  FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id);

-- Add column for report (re-score) only; Candidate Results keep using ai_score.
ALTER TABLE candidates
  ADD COLUMN IF NOT EXISTS ai_report_score integer;

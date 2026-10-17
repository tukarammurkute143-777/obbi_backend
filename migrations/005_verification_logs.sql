-- Response Verifier Agent audit log. Run in the Supabase SQL editor.
-- Stores scores and issues only, never the verified content (it can contain
-- customer names and trip details).

CREATE TABLE IF NOT EXISTS verification_logs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  response_type VARCHAR(50),
  overall_score DECIMAL(3,2),
  passed BOOLEAN,
  issues JSONB DEFAULT '[]',
  corrections JSONB DEFAULT '{}',
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS verification_logs_type_idx
  ON verification_logs (response_type, created_at DESC);

-- Same posture as the other tables: RLS on, no policies, backend-only.
ALTER TABLE verification_logs ENABLE ROW LEVEL SECURITY;

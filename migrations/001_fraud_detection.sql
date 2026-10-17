-- Fraud Detection Agent columns. Run in the Supabase SQL editor.
ALTER TABLE login_attempts ADD COLUMN IF NOT EXISTS fraud_flags JSONB DEFAULT '{}';
ALTER TABLE blocked_ips ADD COLUMN IF NOT EXISTS duration_hours INTEGER;
ALTER TABLE blocked_ips ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE;

-- Email review queue + saved itineraries. Run in the Supabase SQL editor.

CREATE TABLE IF NOT EXISTS email_review_queue (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  customer_email VARCHAR(255),
  customer_name VARCHAR(255),
  email_type VARCHAR(50),
  subject TEXT,
  body TEXT,
  attachment_path TEXT,
  overall_score DECIMAL(3,2),
  failed_checks JSONB,
  status VARCHAR(20) DEFAULT 'pending',
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  reviewed_at TIMESTAMP WITH TIME ZONE,
  action_taken VARCHAR(20)
);
-- Lets approve re-create the PDF if the stored file is gone (server disk is
-- ephemeral). Not in the original spec; nullable and optional.
ALTER TABLE email_review_queue ADD COLUMN IF NOT EXISTS itinerary_id UUID;
CREATE INDEX IF NOT EXISTS email_review_queue_status_idx
  ON email_review_queue (status, created_at DESC);

CREATE TABLE IF NOT EXISTS itineraries (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  from_city VARCHAR(100),
  to_city VARCHAR(100),
  days INTEGER,
  people INTEGER,
  budget VARCHAR(20),
  trip_type VARCHAR(50),
  itinerary_data JSONB,
  pdf_path TEXT,
  downloaded BOOLEAN DEFAULT false,
  emailed BOOLEAN DEFAULT false,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS itineraries_user_idx ON itineraries (user_id, created_at DESC);

-- Same posture as the other tables: RLS on, no policies, backend uses the
-- service-role key.
ALTER TABLE email_review_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE itineraries ENABLE ROW LEVEL SECURITY;

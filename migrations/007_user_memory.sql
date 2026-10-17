-- Safar cross-session memory: one row per user. Run in the Supabase SQL editor.

CREATE TABLE IF NOT EXISTS user_memory (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES users(id) UNIQUE,
  preferred_route_from VARCHAR(100),
  preferred_route_to VARCHAR(100),
  preferred_vehicle VARCHAR(100),
  total_inquiries INTEGER DEFAULT 0,
  booking_confirmed_ever BOOLEAN DEFAULT false,
  last_inquiry_summary TEXT,
  last_inquiry_at TIMESTAMP WITH TIME ZONE,
  past_trips JSONB DEFAULT '[]',
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Same posture as the other tables: RLS on, no policies, backend-only.
ALTER TABLE user_memory ENABLE ROW LEVEL SECURITY;

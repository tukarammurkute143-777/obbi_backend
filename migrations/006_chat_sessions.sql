-- Safar chat sessions (persistent copy; the live session is in Redis).
-- Run in the Supabase SQL editor.

CREATE TABLE IF NOT EXISTS chat_sessions (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  session_id VARCHAR(255) UNIQUE NOT NULL,
  user_id UUID REFERENCES users(id),
  language VARCHAR(20) DEFAULT 'hindi',
  booking_confirmed BOOLEAN DEFAULT false,
  messages JSONB DEFAULT '[]',
  context JSONB DEFAULT '{}',
  last_intent VARCHAR(50),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user
ON chat_sessions(user_id);

-- Same posture as the other tables: RLS on, no policies, backend-only.
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;

-- Blog Writer Agent: AI-drafted blogs, published only by the owner.
-- Run in the Supabase SQL editor.

CREATE TABLE IF NOT EXISTS blogs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  title TEXT NOT NULL,
  slug VARCHAR(255) UNIQUE NOT NULL,
  meta_description TEXT,
  content TEXT NOT NULL,
  blog_type VARCHAR(50),
  target_keyword VARCHAR(255),
  word_count INTEGER,
  keyword_density DECIMAL(4,3),
  tags JSONB DEFAULT '[]',
  status VARCHAR(20) DEFAULT 'draft',  -- draft | published | rejected
  confidence_score DECIMAL(3,2),
  generated_by VARCHAR(50) DEFAULT 'ai',
  published_at TIMESTAMP WITH TIME ZONE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS blogs_status_idx ON blogs (status, published_at DESC);

-- Same posture as the other tables: RLS on, no policies. The backend (service
-- role) serves the public /api/blogs endpoints; browsers never read this
-- table directly.
ALTER TABLE blogs ENABLE ROW LEVEL SECURITY;

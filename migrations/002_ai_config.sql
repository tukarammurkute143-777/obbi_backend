-- Flexible AI provider: API keys + model registry. Run in the Supabase SQL editor.

-- API keys table. key_value holds an encrypted value ("enc:v1:..."); the API
-- never returns it. Written and read only by the backend (service role).
CREATE TABLE IF NOT EXISTS api_keys_config (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  key_name VARCHAR(100) UNIQUE NOT NULL,
  key_value TEXT NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_by VARCHAR(255)
);

-- AI models table. is_active = available to use, is_default = the model the
-- app currently runs on (at most one).
CREATE TABLE IF NOT EXISTS ai_models (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  provider VARCHAR(50) NOT NULL,  -- openai|groq|gemini|anthropic
  model_name VARCHAR(100) NOT NULL,
  display_name VARCHAR(100) NOT NULL,
  is_active BOOLEAN DEFAULT false,
  is_default BOOLEAN DEFAULT false,
  added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  added_by VARCHAR(255)
);

-- Integrity: no duplicate model, and only one default at a time.
CREATE UNIQUE INDEX IF NOT EXISTS ai_models_provider_model_key
  ON ai_models (provider, model_name);
CREATE UNIQUE INDEX IF NOT EXISTS ai_models_single_default
  ON ai_models (is_default) WHERE is_default;

-- Same posture as the other tables: RLS on with no policies, so the browser
-- (anon key) can read nothing. The backend uses the service-role key.
ALTER TABLE api_keys_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_models ENABLE ROW LEVEL SECURITY;

-- Default models
INSERT INTO ai_models (provider, model_name, display_name, is_active, is_default) VALUES
('openai', 'gpt-4o', 'GPT-4o (OpenAI)', true, true),
('openai', 'gpt-4o-mini', 'GPT-4o Mini (OpenAI)', true, false),
('groq', 'llama-3.1-70b-versatile', 'Llama 3.1 70B (Groq)', true, false),
('groq', 'mixtral-8x7b-32768', 'Mixtral 8x7B (Groq)', true, false),
('gemini', 'gemini-1.5-pro', 'Gemini 1.5 Pro (Google)', true, false),
('anthropic', 'claude-3-5-sonnet-20241022', 'Claude 3.5 Sonnet', true, false)
ON CONFLICT (provider, model_name) DO NOTHING;

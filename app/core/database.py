from supabase import create_client, Client
from app.core.config import settings

# New Supabase key format support
supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_KEY  # Use publishable key instead!
)

# Admin client for privileged operations
supabase_admin: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_KEY
)
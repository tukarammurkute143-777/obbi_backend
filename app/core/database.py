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

# Default client for all server-side queries.
#
# Every table has RLS enabled and the publishable key is denied both read and
# write (an anon insert fails with "new row violates row-level security policy",
# and selects come back empty), so backend queries must use the service-role
# client. That is the intended split: RLS protects direct browser -> Supabase
# access, while this FastAPI server is a trusted caller that does its own
# authorization in the API layer (JWT middleware + owner checks).
#
# Never hand this client, or the service key, to anything client-facing.
db: Client = supabase_admin
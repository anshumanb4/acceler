import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")

CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
CLAUDE_MAX_TOKENS = 16384
MAX_CONTENT_LENGTH = 15000

# Prefer service role key (bypasses RLS), fall back to anon key
_key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
if not _key:
    raise RuntimeError("Set SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY in .env")

supabase = create_client(SUPABASE_URL, _key)

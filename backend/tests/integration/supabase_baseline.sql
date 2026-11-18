-- Recreates, in a plain pgvector/pgvector container, the Supabase setup the migrations rely on
-- (used by the CI `migrations` job; D-052). Never run this against Supabase itself.

-- Client roles that the Data API would use; the migrations revoke their access.
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
GRANT USAGE ON SCHEMA public TO anon, authenticated;

-- Supabase installs extensions into `extensions` and puts it on the search path.
CREATE SCHEMA extensions;
ALTER DATABASE postgres SET search_path = "$user", public, extensions;

-- Supabase's default grants for objects that postgres creates in public.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON SEQUENCES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON FUNCTIONS TO anon, authenticated;

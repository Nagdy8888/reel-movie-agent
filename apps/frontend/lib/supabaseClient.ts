import { createBrowserClient } from "@supabase/ssr";

/** Browser Supabase client for auth + session. */
export const supabase = createBrowserClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
);

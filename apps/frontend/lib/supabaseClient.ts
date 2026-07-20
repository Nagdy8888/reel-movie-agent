import { createBrowserClient } from "@supabase/ssr";
import { publicEnv } from "./env";

/** Browser Supabase client for auth + session. */
export const supabase = createBrowserClient(
  publicEnv.supabaseUrl,
  publicEnv.supabaseAnonKey,
);

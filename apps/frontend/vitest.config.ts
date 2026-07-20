/** Vitest configuration for pure frontend helpers and API boundaries. */

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["lib/**/*.test.ts"],
    environment: "node",
    env: {
      NEXT_PUBLIC_API_URL: "https://api.example.test",
      NEXT_PUBLIC_SUPABASE_URL: "https://project.supabase.co",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "unit-test-anon-key",
    },
  },
});

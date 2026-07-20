/** Validated public configuration shared by browser and server modules. */

const PLACEHOLDER_PATTERN = /^(?:change-me|example|placeholder|your[-_])/i;

/** Read and validate one required public URL. */
function requirePublicUrl(name: string, value: string | undefined): string {
  const normalized = value?.trim();
  if (!normalized || PLACEHOLDER_PATTERN.test(normalized)) {
    throw new Error(`${name} must be configured with a non-placeholder URL.`);
  }

  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error(`${name} must be a valid absolute URL.`);
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`${name} must use http or https.`);
  }

  return normalized.replace(/\/+$/, "");
}

/** Read and validate one required public string. */
function requirePublicValue(name: string, value: string | undefined): string {
  const normalized = value?.trim();
  if (!normalized || PLACEHOLDER_PATTERN.test(normalized)) {
    throw new Error(`${name} must be configured with a non-placeholder value.`);
  }
  return normalized;
}

/** Fail-fast public environment consumed by the frontend. */
export const publicEnv = Object.freeze({
  apiUrl: requirePublicUrl("NEXT_PUBLIC_API_URL", process.env.NEXT_PUBLIC_API_URL),
  supabaseUrl: requirePublicUrl(
    "NEXT_PUBLIC_SUPABASE_URL",
    process.env.NEXT_PUBLIC_SUPABASE_URL,
  ),
  supabaseAnonKey: requirePublicValue(
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  ),
});

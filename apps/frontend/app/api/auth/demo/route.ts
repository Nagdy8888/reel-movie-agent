/** Server-only login endpoint for the intentionally public demo account. */

import "server-only";

import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { publicEnv } from "@/lib/env";

export const dynamic = "force-dynamic";

/** Read a required server-only credential without leaking its value. */
function requireCredential(name: "DEMO_ACCOUNT_EMAIL" | "DEMO_ACCOUNT_PASSWORD"): string {
  const value = process.env[name];
  if (!value?.trim()) throw new Error(`${name} is not configured.`);
  return value;
}

/** Create a cookie-backed session for the shared demo account. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const origin = request.headers.get("origin");
  if (origin && origin !== request.nextUrl.origin) {
    return NextResponse.json({ error: "Forbidden." }, { status: 403 });
  }

  let email: string;
  let password: string;
  try {
    email = requireCredential("DEMO_ACCOUNT_EMAIL");
    password = requireCredential("DEMO_ACCOUNT_PASSWORD");
  } catch (error) {
    console.error("Demo account configuration error.", error);
    return NextResponse.json(
      { error: "The demo account is unavailable." },
      { status: 503, headers: { "Cache-Control": "private, no-store" } },
    );
  }

  let response: NextResponse = NextResponse.json(
    { ok: true },
    { headers: { "Cache-Control": "private, no-store" } },
  );
  const supabase = createServerClient(publicEnv.supabaseUrl, publicEnv.supabaseAnonKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (cookiesToSet, headers) => {
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options);
        }
        for (const [name, value] of Object.entries(headers)) {
          response.headers.set(name, value);
        }
      },
    },
  });

  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    console.error("Demo account sign-in failed.", { code: error.code });
    response = NextResponse.json(
      { error: "The demo account is unavailable." },
      { status: 503, headers: { "Cache-Control": "private, no-store" } },
    );
  }

  return response;
}

/** Supabase PKCE callback that exchanges auth codes into cookie sessions. */

import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { publicEnv } from "@/lib/env";

/** Restrict post-auth redirects to same-origin application paths. */
function safeNextPath(value: string | null): string {
  return value?.startsWith("/") && !value.startsWith("//") ? value : "/chat";
}

/** Exchange a Supabase PKCE code and continue to the requested local route. */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const code = request.nextUrl.searchParams.get("code");
  const nextPath = safeNextPath(request.nextUrl.searchParams.get("next"));
  let response = NextResponse.redirect(new URL(nextPath, request.nextUrl.origin));

  if (!code) {
    return NextResponse.redirect(new URL("/login?error=missing_auth_code", request.url));
  }

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

  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    response = NextResponse.redirect(new URL("/login?error=auth_callback_failed", request.url));
  }
  return response;
}

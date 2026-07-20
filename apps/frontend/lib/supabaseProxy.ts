/** Supabase cookie refresh and claim-based redirects for Next.js Proxy. */

import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { publicEnv } from "./env";

/** Copy refreshed auth cookies and anti-cache headers onto a redirect response. */
function preserveSessionHeaders(source: NextResponse, target: NextResponse): NextResponse {
  for (const cookie of source.cookies.getAll()) target.cookies.set(cookie);
  for (const header of ["cache-control", "expires", "pragma"]) {
    const value = source.headers.get(header);
    if (value) target.headers.set(header, value);
  }
  return target;
}

/** Refresh the cookie session and enforce auth redirects for chat and login routes. */
export async function updateSession(request: NextRequest): Promise<NextResponse> {
  let response = NextResponse.next({ request });
  const supabase = createServerClient(publicEnv.supabaseUrl, publicEnv.supabaseAnonKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (cookiesToSet, headers) => {
        for (const { name, value } of cookiesToSet) request.cookies.set(name, value);
        response = NextResponse.next({ request });
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options);
        }
        for (const [name, value] of Object.entries(headers)) {
          response.headers.set(name, value);
        }
      },
    },
  });

  const { data, error } = await supabase.auth.getClaims();
  const isAuthenticated = !error && Boolean(data?.claims?.sub);
  const isChatRoute = request.nextUrl.pathname.startsWith("/chat");
  const isLoginRoute = request.nextUrl.pathname === "/login";
  const isPasswordRecovery = request.nextUrl.searchParams.get("reset") === "1";

  if (isChatRoute && !isAuthenticated) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.search = "";
    loginUrl.searchParams.set(
      "next",
      `${request.nextUrl.pathname}${request.nextUrl.search}`,
    );
    return preserveSessionHeaders(response, NextResponse.redirect(loginUrl));
  }

  if (isLoginRoute && isAuthenticated && !isPasswordRecovery) {
    const chatUrl = request.nextUrl.clone();
    chatUrl.pathname = "/chat";
    chatUrl.search = "";
    return preserveSessionHeaders(response, NextResponse.redirect(chatUrl));
  }

  return response;
}

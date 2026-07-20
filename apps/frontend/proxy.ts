/** Next.js 16 request guard for authenticated workspace routes. */

import { NextResponse, type NextRequest } from "next/server";
import { updateSession } from "@/lib/supabaseProxy";

/** Refresh Supabase auth and redirect before protected UI renders. */
export async function proxy(request: NextRequest): Promise<NextResponse> {
  if (
    process.env.NODE_ENV === "development" &&
    process.env.E2E_BYPASS_AUTH === "1"
  ) {
    return NextResponse.next();
  }
  return updateSession(request);
}

export const config = {
  matcher: ["/chat/:path*", "/login"],
};

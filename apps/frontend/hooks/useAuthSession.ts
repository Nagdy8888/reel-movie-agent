"use client";

/** Client-side Supabase session lifecycle for authenticated workspace features. */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { User } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabaseClient";

export interface AuthSessionState {
  user: User | null;
  accessToken: string | null;
  isLoading: boolean;
  error: string | null;
  redirectToLogin: () => void;
  signOut: () => Promise<void>;
}

/** Keep the browser session current and redirect when authentication is lost. */
export function useAuthSession(): AuthSessionState {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const redirectToLogin = useCallback(() => {
    router.replace("/login");
  }, [router]);

  useEffect(() => {
    let mounted = true;

    void supabase.auth.getSession().then(({ data: { session } }) => {
      if (!mounted) return;
      if (!session) {
        setIsLoading(false);
        redirectToLogin();
        return;
      }
      setUser(session.user);
      setAccessToken(session.access_token);
      setIsLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!mounted) return;
      if (!session) {
        setUser(null);
        setAccessToken(null);
        setIsLoading(false);
        redirectToLogin();
        return;
      }
      setUser(session.user);
      setAccessToken(session.access_token);
      setIsLoading(false);
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [redirectToLogin]);

  const signOut = useCallback(async () => {
    setError(null);
    const { error: signOutError } = await supabase.auth.signOut();
    if (signOutError) {
      setError("Could not sign out. Please try again.");
      return;
    }
    redirectToLogin();
  }, [redirectToLogin]);

  return { user, accessToken, isLoading, error, redirectToLogin, signOut };
}

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";
import { MaterialIcon } from "@/components/MaterialIcon";

type AuthView = "signin" | "signup" | "forgot" | "updatePassword";

/** Sign-in / sign-up page with Supabase auth. */
export default function LoginPage() {
  const router = useRouter();
  const [view, setView] = useState<AuthView>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const isPasswordRecovery = params.get("reset") === "1";
    queueMicrotask(() => {
      if (isPasswordRecovery) setView("updatePassword");
      if (params.has("error")) {
        setError("The authentication link is invalid or expired. Please try again.");
      }
    });

    void supabase.auth.getSession().then(({ data: { session } }) => {
      if (session && !isPasswordRecovery) router.replace("/chat");
    });
  }, [router]);

  const handleAuthSuccess = () => {
    router.replace("/chat");
  };

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error: authError } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (authError) {
      setError(authError.message);
      return;
    }
    handleAuthSuccess();
  };

  const handleSignUp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setLoading(true);
    const callbackUrl = new URL("/auth/callback", window.location.origin);
    callbackUrl.searchParams.set("next", "/chat");
    const { data, error: authError } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: { full_name: fullName },
        emailRedirectTo: callbackUrl.toString(),
      },
    });
    setLoading(false);
    if (authError) {
      setError(authError.message);
      return;
    }
    // Hosted Supabase projects require email confirmation by default — no session yet.
    if (!data.session) {
      setView("signin");
      setSuccess("Account created. Check your email to confirm, then sign in below.");
      return;
    }
    handleAuthSuccess();
  };

  const handleGoogle = async () => {
    setError(null);
    setLoading(true);
    const callbackUrl = new URL("/auth/callback", window.location.origin);
    callbackUrl.searchParams.set("next", "/chat");
    const { error: authError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: callbackUrl.toString() },
    });
    if (authError) {
      setLoading(false);
      setError(authError.message);
    }
  };

  const handlePasswordResetRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setLoading(true);
    const callbackUrl = new URL("/auth/callback", window.location.origin);
    callbackUrl.searchParams.set("next", "/login?reset=1");
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: callbackUrl.toString(),
    });
    setLoading(false);
    if (resetError) {
      setError(resetError.message);
      return;
    }
    setSuccess("Check your email for a secure password-reset link.");
  };

  const handlePasswordUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error: updateError } = await supabase.auth.updateUser({ password });
    if (updateError) {
      setLoading(false);
      setError(updateError.message);
      return;
    }
    await supabase.auth.signOut();
    window.history.replaceState({}, "", "/login");
    setPassword("");
    setView("signin");
    setSuccess("Password updated. Sign in with your new password.");
    setLoading(false);
  };

  return (
    <div className="bg-background text-on-surface antialiased min-h-screen flex selection:bg-primary/30 selection:text-primary">
      <div className="hidden lg:flex w-[60%] relative overflow-hidden bg-surface-container-lowest flex-col justify-between p-margin-desktop border-r border-outline-variant/20">
        <div className="absolute inset-0 bg-gradient-to-br from-surface-container-low via-canvas to-surface-container-lowest opacity-80" />
        <div className="absolute inset-0 bg-gradient-to-r from-background via-background/60 to-transparent" />
        <div className="absolute inset-0 bg-gradient-to-t from-background via-transparent to-background/30" />
        <div className="absolute inset-0 opacity-20 pointer-events-none">
          <svg className="absolute inset-0 w-full h-full" xmlns="http://www.w3.org/2000/svg">
            <circle cx="20%" cy="30%" className="fill-primary" r="4" style={{ filter: "drop-shadow(0 0 8px currentColor)" }} />
            <circle cx="45%" cy="45%" className="fill-primary" r="3" style={{ filter: "drop-shadow(0 0 6px currentColor)" }} />
            <circle cx="35%" cy="70%" className="fill-primary" r="5" style={{ filter: "drop-shadow(0 0 10px currentColor)" }} />
            <circle cx="70%" cy="60%" className="fill-primary" r="3" style={{ filter: "drop-shadow(0 0 6px currentColor)" }} />
            <line stroke="currentColor" className="text-outline-variant" strokeWidth="0.5" x1="20%" x2="45%" y1="30%" y2="45%" />
            <line stroke="currentColor" className="text-outline-variant" strokeWidth="0.5" x1="45%" x2="35%" y1="45%" y2="70%" />
            <line stroke="currentColor" className="text-outline-variant" strokeWidth="0.5" x1="45%" x2="70%" y1="45%" y2="60%" />
          </svg>
        </div>
        <div className="relative z-10 mt-xl">
          <h1 className="font-display-lg text-display-lg text-primary tracking-tight">Reel</h1>
        </div>
        <div className="relative z-10 max-w-lg mb-xl">
          <p className="font-headline-lg text-headline-lg text-on-surface-variant leading-tight">
            Your film knowledge companion.
          </p>
          <div className="h-0.5 w-16 bg-primary/80 mt-lg rounded-full" />
        </div>
      </div>

      <div className="w-full lg:w-[40%] flex flex-col justify-center items-center bg-surface-container-lowest p-margin-mobile lg:p-margin-desktop relative">
        <div className="lg:hidden absolute top-margin-mobile left-margin-mobile">
          <h1 className="font-display-md text-display-md text-primary tracking-tight">Reel</h1>
        </div>

        <div className="w-full max-w-[400px] relative z-10 bg-surface-container-lowest lg:bg-transparent rounded-2xl p-6 lg:p-0">
          {view === "signin" ? (
            <div className="flex flex-col gap-lg transition-opacity duration-300">
              <div className="text-center lg:text-left">
                <h2 className="font-headline-lg-mobile lg:font-headline-lg text-headline-lg-mobile lg:text-headline-lg text-on-surface mb-xs">
                  Welcome back
                </h2>
                <p className="font-body-sm text-body-sm text-on-surface-variant">
                  Sign in to access your cinematic intelligence.
                </p>
              </div>
              {success && (
                <p
                  role="status"
                  className="font-body-sm text-body-sm text-primary bg-primary-container/10 border border-primary-container/30 rounded-lg px-md py-sm"
                >
                  {success}
                </p>
              )}
              {error && (
                <p
                  role="alert"
                  className="font-body-sm text-body-sm text-error bg-error-container/20 border border-error/30 rounded-lg px-md py-sm"
                >
                  {error}
                </p>
              )}
              <form className="flex flex-col gap-md" onSubmit={handleSignIn}>
                <div className="flex flex-col gap-xs">
                  <label
                    htmlFor="signin-email"
                    className="font-label-caps text-label-caps text-on-surface-variant tracking-wider"
                  >
                    EMAIL
                  </label>
                  <input
                    id="signin-email"
                    className="bg-surface-container border border-outline-variant rounded-xl px-4 py-3 font-body-lg text-body-lg text-on-surface placeholder:text-outline-variant focus:outline-none input-glow transition-all duration-200"
                    placeholder="cinephile@example.com"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="flex flex-col gap-xs">
                  <div className="flex justify-between items-center">
                    <label
                      htmlFor="signin-password"
                      className="font-label-caps text-label-caps text-on-surface-variant tracking-wider"
                    >
                      PASSWORD
                    </label>
                    <button
                      type="button"
                      onClick={() => {
                        setView("forgot");
                        setError(null);
                        setSuccess(null);
                      }}
                      className="font-body-sm text-body-sm text-primary hover:text-primary-fixed transition-colors"
                    >
                      Forgot?
                    </button>
                  </div>
                  <div className="relative">
                    <input
                      id="signin-password"
                      className="w-full bg-surface-container border border-outline-variant rounded-xl px-4 py-3 font-body-lg text-body-lg text-on-surface placeholder:text-outline-variant focus:outline-none input-glow transition-all duration-200"
                      placeholder="••••••••"
                      type={showPassword ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      className="absolute right-4 top-1/2 -translate-y-1/2 text-outline-variant hover:text-on-surface transition-colors flex items-center justify-center"
                    >
                      <MaterialIcon name={showPassword ? "visibility" : "visibility_off"} size={20} />
                    </button>
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-primary text-on-primary font-title-md text-title-md py-3 rounded-lg mt-sm hover:bg-primary-container active:scale-[0.98] transition-all duration-200 shadow-[0_4px_14px_rgba(232,180,87,0.1)] hover:shadow-[0_6px_20px_rgba(232,180,87,0.2)] disabled:opacity-50"
                >
                  Sign in
                </button>
              </form>
              <div className="relative flex items-center py-2">
                <div className="flex-grow border-t border-outline-variant/40" />
                <span className="flex-shrink-0 px-4 font-body-sm text-body-sm text-on-surface-variant">
                  or continue with
                </span>
                <div className="flex-grow border-t border-outline-variant/40" />
              </div>
              <button
                type="button"
                onClick={() => void handleGoogle()}
                disabled={loading}
                className="w-full flex items-center justify-center gap-sm border border-outline-variant bg-transparent text-on-surface font-title-md text-title-md py-3 rounded-lg hover:bg-surface-variant/40 active:bg-surface-variant/60 transition-all duration-200"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                  <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.16v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                  <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.16C1.43 8.55 1 10.22 1 12s.43 3.45 1.16 4.93l2.48-1.92.12-.92z" fill="#FBBC05" />
                  <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.16 7.07l3.68 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
                </svg>
                Google
              </button>
              <p className="text-center font-body-sm text-body-sm text-on-surface-variant mt-sm">
                New here?{" "}
                <button
                  type="button"
                  className="text-primary hover:text-primary-fixed transition-colors font-medium"
                  onClick={() => {
                    setView("signup");
                    setError(null);
                    setSuccess(null);
                  }}
                >
                  Create an account
                </button>
              </p>
            </div>
          ) : view === "signup" ? (
            <div className="flex flex-col gap-lg transition-opacity duration-300">
              <div className="text-center lg:text-left">
                <h2 className="font-headline-lg-mobile lg:font-headline-lg text-headline-lg-mobile lg:text-headline-lg text-on-surface mb-xs">
                  Join Reel
                </h2>
                <p className="font-body-sm text-body-sm text-on-surface-variant">
                  Begin your curated cinematic journey.
                </p>
              </div>
              {success && (
                <p
                  role="status"
                  className="font-body-sm text-body-sm text-primary bg-primary-container/10 border border-primary-container/30 rounded-lg px-md py-sm"
                >
                  {success}
                </p>
              )}
              {error && (
                <p
                  role="alert"
                  className="font-body-sm text-body-sm text-error bg-error-container/20 border border-error/30 rounded-lg px-md py-sm"
                >
                  {error}
                </p>
              )}
              <form className="flex flex-col gap-md" onSubmit={handleSignUp}>
                <div className="flex flex-col gap-xs">
                  <label
                    htmlFor="signup-name"
                    className="font-label-caps text-label-caps text-on-surface-variant tracking-wider"
                  >
                    FULL NAME
                  </label>
                  <input
                    id="signup-name"
                    className="bg-surface-container border border-outline-variant rounded-xl px-4 py-3 font-body-lg text-body-lg text-on-surface placeholder:text-outline-variant focus:outline-none input-glow transition-all duration-200"
                    placeholder="Your name"
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    required
                  />
                </div>
                <div className="flex flex-col gap-xs">
                  <label
                    htmlFor="signup-email"
                    className="font-label-caps text-label-caps text-on-surface-variant tracking-wider"
                  >
                    EMAIL
                  </label>
                  <input
                    id="signup-email"
                    className="bg-surface-container border border-outline-variant rounded-xl px-4 py-3 font-body-lg text-body-lg text-on-surface placeholder:text-outline-variant focus:outline-none input-glow transition-all duration-200"
                    placeholder="cinephile@example.com"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="flex flex-col gap-xs">
                  <label
                    htmlFor="signup-password"
                    className="font-label-caps text-label-caps text-on-surface-variant tracking-wider"
                  >
                    PASSWORD
                  </label>
                  <input
                    id="signup-password"
                    className="w-full bg-surface-container border border-outline-variant rounded-xl px-4 py-3 font-body-lg text-body-lg text-on-surface placeholder:text-outline-variant focus:outline-none input-glow transition-all duration-200"
                    placeholder="Create a secure password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    minLength={8}
                    required
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-primary text-on-primary font-title-md text-title-md py-3 rounded-lg mt-sm hover:bg-primary-container active:scale-[0.98] transition-all duration-200 shadow-[0_4px_14px_rgba(232,180,87,0.1)] hover:shadow-[0_6px_20px_rgba(232,180,87,0.2)] disabled:opacity-50"
                >
                  Create account
                </button>
              </form>
              <p className="text-center font-body-sm text-body-sm text-on-surface-variant mt-sm">
                Already have an account?{" "}
                <button
                  type="button"
                  className="text-primary hover:text-primary-fixed transition-colors font-medium"
                  onClick={() => {
                    setView("signin");
                    setError(null);
                    setSuccess(null);
                  }}
                >
                  Sign in
                </button>
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-lg transition-opacity duration-300">
              <div className="text-center lg:text-left">
                <h2 className="font-headline-lg-mobile lg:font-headline-lg text-headline-lg-mobile lg:text-headline-lg text-on-surface mb-xs">
                  {view === "forgot" ? "Reset your password" : "Choose a new password"}
                </h2>
                <p className="font-body-sm text-body-sm text-on-surface-variant">
                  {view === "forgot"
                    ? "We will email you a secure recovery link."
                    : "Enter a new password for your Reel account."}
                </p>
              </div>
              {success && (
                <p
                  role="status"
                  className="font-body-sm text-body-sm text-primary bg-primary-container/10 border border-primary-container/30 rounded-lg px-md py-sm"
                >
                  {success}
                </p>
              )}
              {error && (
                <p
                  role="alert"
                  className="font-body-sm text-body-sm text-error bg-error-container/20 border border-error/30 rounded-lg px-md py-sm"
                >
                  {error}
                </p>
              )}
              <form
                className="flex flex-col gap-md"
                onSubmit={
                  view === "forgot" ? handlePasswordResetRequest : handlePasswordUpdate
                }
              >
                {view === "forgot" ? (
                  <div className="flex flex-col gap-xs">
                    <label
                      htmlFor="reset-email"
                      className="font-label-caps text-label-caps text-on-surface-variant tracking-wider"
                    >
                      EMAIL
                    </label>
                    <input
                      id="reset-email"
                      className="bg-surface-container border border-outline-variant rounded-xl px-4 py-3 font-body-lg text-body-lg text-on-surface placeholder:text-outline-variant focus:outline-none input-glow transition-all duration-200"
                      placeholder="cinephile@example.com"
                      type="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      required
                    />
                  </div>
                ) : (
                  <div className="flex flex-col gap-xs">
                    <label
                      htmlFor="new-password"
                      className="font-label-caps text-label-caps text-on-surface-variant tracking-wider"
                    >
                      NEW PASSWORD
                    </label>
                    <input
                      id="new-password"
                      className="bg-surface-container border border-outline-variant rounded-xl px-4 py-3 font-body-lg text-body-lg text-on-surface placeholder:text-outline-variant focus:outline-none input-glow transition-all duration-200"
                      placeholder="At least 8 characters"
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      minLength={8}
                      required
                    />
                  </div>
                )}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-primary text-on-primary font-title-md text-title-md py-3 rounded-lg mt-sm hover:bg-primary-container active:scale-[0.98] transition-all duration-200 disabled:opacity-50"
                >
                  {view === "forgot" ? "Send reset link" : "Update password"}
                </button>
              </form>
              {view === "forgot" && (
                <button
                  type="button"
                  className="text-primary hover:text-primary-fixed transition-colors font-medium"
                  onClick={() => {
                    setView("signin");
                    setError(null);
                    setSuccess(null);
                  }}
                >
                  Back to sign in
                </button>
              )}
            </div>
          )}
        </div>

        <div className="absolute bottom-margin-mobile lg:bottom-margin-desktop w-full flex justify-center lg:justify-end lg:pr-margin-desktop pointer-events-none">
          <div className="flex items-center gap-xs text-outline font-body-sm text-body-sm opacity-60">
            <MaterialIcon name="database" size={16} />
            <span>Powered by Supabase</span>
          </div>
        </div>
      </div>
    </div>
  );
}

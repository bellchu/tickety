"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, LockKeyhole, ShieldCheck } from "lucide-react";
import { TicketyLogo } from "@/components/layout/TicketyLogo";
import { Alert, Button } from "@/components/ui";
import { api } from "@/lib/api";

function getSafeNextPath() {
  if (typeof window === "undefined") return "/";
  const next = new URLSearchParams(window.location.search).get("next");
  if (!next || !next.startsWith("/") || next.startsWith("//")) return "/";
  return next;
}

const workspaceBenefits = [
  "Prioritize incidents, requests, and changes in one queue",
  "Keep ownership, service impact, and response targets visible",
  "Turn operational signals into clear next actions",
];

export default function LoginPage() {
  const router = useRouter();
  const [nextPath, setNextPath] = useState("/");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const [ssoProvider, setSsoProvider] = useState("");
  const [ssoLoading, setSsoLoading] = useState(false);

  useEffect(() => {
    setNextPath(getSafeNextPath());
    api
      .getSsoConfig()
      .then((config) => {
        setSsoEnabled(config.enabled);
        setSsoProvider(config.provider);
      })
      .catch(() => {
        // Password authentication remains available when SSO discovery is offline.
      });
  }, []);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      await api.login(email, password);
      router.push(nextPath);
      router.refresh();
    } catch {
      setError("We couldn’t sign you in with those details. Check your email and password, then try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleSsoLogin = () => {
    setSsoLoading(true);
    window.location.assign("/api/auth/sso/login");
  };

  return (
    <main className="min-h-screen bg-[#F4F5F7] p-3 sm:p-5 lg:p-6">
      <div className="mx-auto grid min-h-[calc(100vh-1.5rem)] w-full max-w-[1440px] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_24px_80px_rgba(15,23,42,0.12)] sm:min-h-[calc(100vh-2.5rem)] lg:grid-cols-[minmax(0,1.05fr)_minmax(440px,0.95fr)]">
        <section className="relative hidden overflow-hidden bg-[#0A0D12] px-12 py-11 text-white lg:flex lg:flex-col" aria-label="Tickety product overview">
          <div className="absolute -right-24 -top-28 h-80 w-80 rounded-full bg-blue-500/20 blur-3xl" aria-hidden="true" />
          <div className="absolute -bottom-36 left-1/4 h-96 w-96 rounded-full bg-cyan-400/10 blur-3xl" aria-hidden="true" />

          <div className="relative z-10">
            <TicketyLogo inverse className="h-10" />
          </div>

          <div className="relative z-10 my-auto max-w-xl py-16">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-300/20 bg-blue-400/10 px-3 py-1.5 text-xs font-semibold tracking-wide text-blue-100">
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-300" aria-hidden="true" />
              OPERATIONS, IN FOCUS
            </div>
            <h1 className="max-w-lg text-4xl font-semibold leading-[1.08] tracking-[-0.035em] xl:text-5xl">
              Move support work forward with confidence.
            </h1>
            <p className="mt-6 max-w-lg text-base leading-7 text-slate-300">
              Tickety gives service teams a calm, shared view of the work that needs attention now—and the context to act on it.
            </p>

            <ul className="mt-9 space-y-4" aria-label="Workspace capabilities">
              {workspaceBenefits.map((benefit) => (
                <li key={benefit} className="flex items-start gap-3 text-sm leading-6 text-slate-200">
                  <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-blue-400/15 text-cyan-200" aria-hidden="true">
                    <Check className="h-3.5 w-3.5" />
                  </span>
                  {benefit}
                </li>
              ))}
            </ul>
          </div>

          <div className="relative z-10 flex items-center gap-2 text-xs text-slate-400">
            <ShieldCheck className="h-4 w-4 text-emerald-300" aria-hidden="true" />
            Access is protected by your organization’s authentication policy.
          </div>
        </section>

        <section className="flex items-center justify-center px-6 py-10 sm:px-12 lg:px-16 xl:px-24">
          <div className="w-full max-w-md">
            <div className="mb-10 lg:hidden">
              <TicketyLogo className="h-10" />
            </div>

            <div className="mb-8">
              <p className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-semantic-primary">Secure workspace</p>
              <h2 className="text-3xl font-semibold tracking-[-0.03em] text-ink-700 sm:text-4xl">Welcome back</h2>
              <p className="mt-3 text-sm leading-6 text-ink-500">Sign in to continue to your service operations workspace.</p>
            </div>

            {ssoEnabled && (
              <>
                <Button
                  className="w-full"
                  size="lg"
                  variant="secondary"
                  onClick={handleSsoLogin}
                  pending={ssoLoading}
                  pendingLabel="Connecting…"
                  leadingIcon={<ShieldCheck className="h-4 w-4" />}
                >
                  Continue with {ssoProvider || "SSO"}
                </Button>
                <div className="my-6 flex items-center gap-4" aria-hidden="true">
                  <div className="h-px flex-1 bg-linen-400" />
                  <span className="text-xs font-medium uppercase tracking-wider text-ink-400">or use email</span>
                  <div className="h-px flex-1 bg-linen-400" />
                </div>
              </>
            )}

            <form onSubmit={handleSubmit} className="space-y-5" aria-busy={loading}>
              <div>
                <label htmlFor="email" className="mb-2 block text-sm font-semibold text-ink-600">Work email</label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="input-base min-h-11 bg-white"
                  placeholder="you@company.com"
                  autoComplete="username"
                  inputMode="email"
                  required
                  autoFocus
                />
              </div>

              <div>
                <div className="mb-2 flex items-baseline justify-between gap-4">
                  <label htmlFor="password" className="text-sm font-semibold text-ink-600">Password</label>
                  <span className="text-xs text-ink-400">Contact your administrator for access help</span>
                </div>
                <input
                  id="password"
                  name="password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="input-base min-h-11 bg-white"
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  required
                />
              </div>

              {error && (
                <Alert variant="danger" title="Sign-in failed">
                  {error}
                </Alert>
              )}

              <Button
                className="w-full"
                size="lg"
                type="submit"
                pending={loading}
                pendingLabel="Signing in…"
                trailingIcon={<ArrowRight className="h-4 w-4" />}
              >
                Sign in
              </Button>
            </form>

            <div className="mt-8 flex items-start gap-3 rounded-xl border border-linen-400 bg-linen-100 px-4 py-3 text-xs leading-5 text-ink-500">
              <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" aria-hidden="true" />
              <p>Only use credentials issued by your organization. Your session is limited to the access assigned to your account.</p>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

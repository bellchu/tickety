"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { TicketyLogo } from "@/components/layout/TicketyLogo";
import { ShieldCheck, RefreshCw, LogIn } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api.login(email, password);
      router.push("/");
      router.refresh();
    } catch {
      setError("Invalid email or password. Try alice@company.com / tickety123");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-linen-100 px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center pt-4">
          <TicketyLogo className="h-10 mx-auto" />
        </div>
        <div className="card-surface p-8 space-y-6">
          <div className="text-center space-y-1">
            <h1 className="font-serif text-2xl text-ink-700">Welcome back</h1>
            <p className="text-sm text-ink-500">Sign in to your IT support workspace</p>
          </div>
          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-ink-500">Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-base"
                placeholder="you@company.com"
                required
                autoFocus
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-ink-500">Password</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-base"
                placeholder="••••••••"
                required
              />
            </label>
            {error && <p className="text-xs text-rust-500">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-ink-700 text-white text-sm font-semibold hover:bg-ink-800 disabled:opacity-50 transition-colors"
            >
              {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
              Sign In
            </button>
          </form>
        </div>
        <div className="card-surface p-4 bg-linen-100 border-linen-300">
          <div className="flex items-start gap-2">
            <ShieldCheck className="w-4 h-4 text-moss-500 shrink-0 mt-0.5" />
            <div className="text-xs text-ink-500">
              <p className="font-medium text-ink-600 mb-0.5">Demo accounts</p>
              <p>alice@company.com · bob@company.com · carol@company.com</p>
              <p className="mt-0.5">Password: <code className="bg-linen-200 px-1 rounded">tickety123</code></p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
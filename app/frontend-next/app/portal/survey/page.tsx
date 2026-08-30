"use client";

import { useEffect, useState, type FormEvent } from "react";
import { CheckCircle2, MessageSquareHeart, ShieldCheck, Star } from "lucide-react";
import { TicketyLogo } from "@/components/layout/TicketyLogo";
import { Alert, Button, Skeleton } from "@/components/ui";
import { APIError, api } from "@/lib/api";
import { formatLocalDateTime } from "@/lib/date-time";
import type { PortalSurveyQuestion } from "@/lib/types";

type LookupState =
  | { status: "loading" }
  | { status: "ready"; survey: PortalSurveyQuestion }
  | { status: "error"; alreadySubmitted: boolean };

export default function PortalSurveyPage() {
  const [token, setToken] = useState("");
  const [lookup, setLookup] = useState<LookupState>({ status: "loading" });
  const [rating, setRating] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    let active = true;
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const capability = (fragment.get("token") || "").trim();

    // Strip the capability from the visible URL and browser history before
    // any network work. It stays only in this component's memory.
    window.history.replaceState(
      window.history.state,
      "",
      window.location.pathname + window.location.search,
    );

    if (!capability) {
      setLookup({ status: "error", alreadySubmitted: false });
      return () => { active = false; };
    }

    setToken(capability);
    void api.lookupPortalSurvey(capability).then(
      (survey) => {
        if (active) setLookup({ status: "ready", survey });
      },
      (error: unknown) => {
        if (active) {
          setToken("");
          setLookup({
            status: "error",
            alreadySubmitted: error instanceof APIError && error.status === 409,
          });
        }
      },
    );
    return () => { active = false; };
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || rating === null || submitting) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      await api.respondPortalSurvey(token, rating, comment.trim());
      setSubmitted(true);
      setToken("");
      setComment("");
    } catch (error) {
      if (error instanceof APIError && [404, 409].includes(error.status)) {
        setToken("");
        setLookup({
          status: "error",
          alreadySubmitted: error.status === 409,
        });
        setSubmitError("");
        return;
      }
      setSubmitError(
        error instanceof APIError && error.status === 409
          ? "This survey has already been submitted."
          : "Your response could not be submitted. The link may be invalid or expired.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="tickety-ambient flex min-h-screen flex-col text-ink-700">
      <header className="relative border-b border-linen-300 bg-linen-50/95 backdrop-blur-md after:absolute after:inset-x-0 after:bottom-0 after:h-[2px] after:[background:var(--brand-accent)]">
        <div className="mx-auto flex h-16 w-full max-w-5xl items-center justify-between px-4 sm:px-6">
          <TicketyLogo />
          <span className="inline-flex items-center gap-2 text-xs font-medium text-ink-500">
            <ShieldCheck className="h-4 w-4 text-semantic-success" aria-hidden="true" />
            Private feedback
          </span>
        </div>
      </header>

      <main className="relative flex flex-1 items-center justify-center overflow-hidden px-4 py-10 sm:px-6 sm:py-16">
        <div className="pointer-events-none absolute -left-32 -top-40 h-[28rem] w-[28rem] rounded-full bg-[#F97316]/10 blur-3xl" aria-hidden="true" />
        <div className="pointer-events-none absolute -right-32 bottom-[-12rem] h-[28rem] w-[28rem] rounded-full bg-[#14B8A6]/10 blur-3xl" aria-hidden="true" />

        <section className="relative w-full max-w-2xl overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-[var(--shadow-raised)]" aria-labelledby="survey-title">
          <div className="border-b border-linen-300 bg-linen-100 px-5 py-6 sm:px-8">
            <div className="grid h-11 w-11 place-items-center rounded-xl bg-[var(--color-primary-soft)] text-semantic-primary" aria-hidden="true">
              <MessageSquareHeart className="h-5 w-5" />
            </div>
            <h1 id="survey-title" className="mt-4 font-serif text-3xl tracking-[-0.025em] text-ink-700">How did we do?</h1>
            <p className="mt-2 text-sm leading-6 text-ink-500">Your feedback helps the support team improve future service.</p>
          </div>

          <div className="px-5 py-6 sm:px-8 sm:py-8" aria-live="polite">
            {lookup.status === "loading" ? (
              <div aria-label="Loading survey" aria-busy="true">
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="mt-6 h-14 w-full" />
                <Skeleton className="mt-5 h-28 w-full" />
              </div>
            ) : lookup.status === "error" ? (
              lookup.alreadySubmitted ? (
                <CompletionMessage title="Feedback already received" description="This one-time survey has already been submitted. Thank you for helping us improve." />
              ) : (
                <Alert variant="warning" title="This survey link is invalid or has expired">For privacy, we cannot confirm any ticket or recipient details. Ask your support team for a new survey link if needed.</Alert>
              )
            ) : submitted ? (
              <CompletionMessage title="Thank you for your feedback" description="Your response has been recorded. You can safely close this page." />
            ) : (
              <form onSubmit={submit}>
                <p className="text-base font-semibold leading-7 text-ink-700">{lookup.survey.question}</p>
                <p className="mt-2 text-xs text-ink-400">This one-time link expires {formatLocalDateTime(lookup.survey.expires_at, { dateStyle: "medium" }, "soon")}.</p>

                <fieldset className="mt-7">
                  <legend className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-500">Rating</legend>
                  <div className="mt-3 grid grid-cols-5 gap-2" role="group" aria-label="Satisfaction rating from 1 to 5">
                    {[1, 2, 3, 4, 5].map((value) => (
                      <button
                        key={value}
                        type="button"
                        aria-pressed={rating === value}
                        aria-label={`${value} out of 5`}
                        onClick={() => { setRating(value); setSubmitError(""); }}
                        className={`flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl border text-sm font-semibold transition-colors ${rating === value ? "border-amber-400 bg-amber-50 text-amber-700" : "border-linen-400 bg-white text-ink-500 hover:bg-linen-100"}`}
                      >
                        <Star className={`h-4 w-4 ${rating === value ? "fill-amber-400 text-amber-400" : "text-ink-300"}`} aria-hidden="true" />
                        {value}
                      </button>
                    ))}
                  </div>
                </fieldset>

                <label className="mt-6 block">
                  <span className="text-sm font-medium text-ink-700">Comment <span className="font-normal text-ink-400">(optional)</span></span>
                  <textarea
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    maxLength={2000}
                    rows={5}
                    className="input-base mt-2 resize-y"
                    placeholder="Tell us what worked well or what we could improve."
                  />
                  <span className="mt-1 block text-right text-xs tabular-nums text-ink-400">{comment.length}/2000</span>
                </label>

                {submitError && <Alert className="mt-5" variant="danger" title="Response not submitted">{submitError}</Alert>}
                <Button type="submit" className="mt-6 w-full" disabled={!token || rating === null} pending={submitting} pendingLabel="Submitting securely…">
                  Submit feedback
                </Button>
              </form>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function CompletionMessage({ title, description }: { title: string; description: string }) {
  return (
    <div className="py-6 text-center">
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-[var(--color-success-soft)] text-semantic-success" aria-hidden="true">
        <CheckCircle2 className="h-7 w-7" />
      </div>
      <h2 className="mt-5 text-xl font-semibold text-ink-700">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-ink-500">{description}</p>
    </div>
  );
}

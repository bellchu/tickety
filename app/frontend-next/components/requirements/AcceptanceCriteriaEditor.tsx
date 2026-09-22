"use client";

import { memo, useEffect, useRef } from "react";
import { Button } from "@/components/ui";
import { Field, inputStyle } from "./fields";

export const AcceptanceCriteriaEditor = memo(function AcceptanceCriteriaEditor({ criteria, issue, count, invalidIndex, onChange }: {
  criteria: string[];
  issue: string | null;
  count: number;
  invalidIndex?: number;
  onChange: (criteria: string[]) => void;
}) {
  const section = useRef<HTMLElement>(null);
  const focusIndex = useRef<number | null>(null);
  useEffect(() => {
    if (focusIndex.current === null) return;
    const inputs = section.current?.querySelectorAll("textarea");
    const target = inputs?.[Math.min(focusIndex.current, inputs.length - 1)];
    (target || section.current?.querySelector<HTMLButtonElement>("button[data-add-criterion]"))?.focus();
    focusIndex.current = null;
  }, [criteria]);

  return <>
        <section ref={section} className="space-y-3" aria-label="Acceptance criteria editor">
          <h3 className="text-sm font-medium">Acceptance criteria</h3>
          <p className="text-xs text-ink-500">Keep one observable outcome per criterion. Line breaks within a criterion stay together.</p>
          {criteria.map((criterion, index) => <div key={index} className={`rounded-lg border p-3 ${invalidIndex === index ? "border-rust-400 bg-rust-400/5" : "border-linen-400"}`}>
            <Field label={`Criterion ${index + 1}`}><textarea rows={3} aria-invalid={invalidIndex === index} aria-describedby="requirement-criteria-help" className={inputStyle} value={criterion} onChange={event => onChange(criteria.map((value, position) => position === index ? event.target.value : value))} placeholder="Given a valid request, when it is submitted, then a receipt appears within the agreed time." /></Field>
            <Button size="sm" variant="ghost" onClick={() => { focusIndex.current = index; onChange(criteria.filter((_, position) => position !== index)); }}>Remove criterion {index + 1}</Button>
          </div>)}
          <Button size="sm" variant="secondary" data-add-criterion disabled={criteria.length >= 20} onClick={() => { focusIndex.current = criteria.length; onChange([...criteria, ""]); }}>Add acceptance criterion</Button>
        </section>
        <p id="requirement-criteria-help" className={`text-xs ${issue ? "text-rust-600" : "text-ink-500"}`}>{issue || `${count} / 20 criteria · 10–1,000 characters each. You can leave this empty while drafting.`}</p>
  </>;
});

"use client";

import { memo } from "react";
import { Button } from "@/components/ui";
import { Field, inputStyle } from "./fields";

export const AcceptanceCriteriaEditor = memo(function AcceptanceCriteriaEditor({ criteria, issue, count, onChange }: {
  criteria: string[];
  issue: string | null;
  count: number;
  onChange: (criteria: string[]) => void;
}) {
  return <>
        <section className="space-y-3" aria-label="Acceptance criteria editor">
          <h3 className="text-sm font-medium">Acceptance criteria</h3>
          <p className="text-xs text-ink-500">Keep one observable outcome per criterion. Line breaks within a criterion stay together.</p>
          {criteria.map((criterion, index) => <div key={index} className="rounded-lg border border-linen-400 p-3">
            <Field label={`Criterion ${index + 1}`}><textarea rows={3} aria-describedby="requirement-criteria-help" className={inputStyle} value={criterion} onChange={event => onChange(criteria.map((value, position) => position === index ? event.target.value : value))} placeholder="Given a valid request, when it is submitted, then a receipt appears within the agreed time." /></Field>
            <Button size="sm" variant="ghost" onClick={() => onChange(criteria.filter((_, position) => position !== index))}>Remove criterion {index + 1}</Button>
          </div>)}
          <Button size="sm" variant="secondary" disabled={criteria.length >= 20} onClick={() => onChange([...criteria, ""])}>Add acceptance criterion</Button>
        </section>
        <p id="requirement-criteria-help" className={`text-xs ${issue ? "text-rust-600" : "text-ink-500"}`}>{issue || `${count} / 20 criteria · 10–1,000 characters each. You can leave this empty while drafting.`}</p>
  </>;
});

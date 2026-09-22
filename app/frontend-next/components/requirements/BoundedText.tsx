"use client";

import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";
import { requirementTextBounds } from "@/lib/requirement-text";

type Bounds = { value: string; maxLength: number; minLength?: number };
function validation(value: string, maximum: number, minimum: number) {
  const { valid } = requirementTextBounds(value, maximum, minimum);
  const message = valid ? "" : value.includes("\0") ? "Remove unsupported control characters."
    : `Use ${minimum.toLocaleString()}–${maximum.toLocaleString()} characters after trimming spaces.`;
  return {
    "aria-invalid": Boolean(value) && !valid,
    ref: (node: HTMLInputElement | HTMLTextAreaElement | null) => { node?.setCustomValidity(message); },
  };
}

/** Native form validation with API character bounds, without truncating pasted text. */
export function RequirementInput({ value, maxLength, minLength, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "value"> & Bounds) {
  return <input {...props} value={value} {...validation(value, maxLength, minLength ?? (props.required ? 1 : 0))} />;
}

export function RequirementTextarea({ value, maxLength, minLength, ...props }: Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value"> & Bounds) {
  return <textarea {...props} value={value} {...validation(value, maxLength, minLength ?? (props.required ? 1 : 0))} />;
}

"use client";

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { LoaderCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive";
export type ButtonSize = "sm" | "md" | "lg";

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "border-transparent bg-semantic-primary text-white shadow-sm hover:bg-semantic-primary-hover",
  secondary:
    "border-linen-500 bg-linen-50 text-ink-700 shadow-sm hover:border-ink-400 hover:bg-linen-200",
  ghost:
    "border-transparent bg-transparent text-ink-500 hover:bg-linen-300 hover:text-ink-700",
  destructive:
    "border-transparent bg-semantic-danger text-white shadow-sm hover:bg-[var(--color-danger-hover)]",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "min-h-8 px-3 text-xs",
  md: "min-h-10 px-4 text-sm",
  lg: "min-h-11 px-5 text-sm",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  pending?: boolean;
  pendingLabel?: string;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    pending = false,
    pendingLabel = "Working",
    leadingIcon,
    trailingIcon,
    className,
    children,
    disabled,
    type = "button",
    ...props
  },
  ref
) {
  const isDisabled = disabled || pending;

  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      aria-disabled={isDisabled || undefined}
      aria-busy={pending || undefined}
      className={cn(
        "relative inline-flex items-center justify-center gap-2 rounded-lg border font-semibold leading-none",
        "transition-[background-color,border-color,color,box-shadow,transform] duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-linen-50",
        "active:translate-y-px disabled:pointer-events-none disabled:opacity-45 disabled:shadow-none disabled:transform-none",
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    >
      {pending ? (
        <LoaderCircle className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
      ) : (
        leadingIcon && <span className="shrink-0" aria-hidden="true">{leadingIcon}</span>
      )}
      <span>{pending ? pendingLabel : children}</span>
      {!pending && trailingIcon && (
        <span className="shrink-0" aria-hidden="true">{trailingIcon}</span>
      )}
    </button>
  );
});

export interface IconButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label"> {
  "aria-label": string;
  icon: ReactNode;
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  pending?: boolean;
}

const iconSizeClasses = {
  sm: "h-8 w-8",
  md: "h-10 w-10",
  lg: "h-11 w-11",
};

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton(
    {
      icon,
      variant = "ghost",
      size = "md",
      pending = false,
      disabled,
      className,
      type = "button",
      ...props
    },
    ref
  ) {
    const isDisabled = disabled || pending;

    return (
      <button
        ref={ref}
        type={type}
        disabled={isDisabled}
        aria-disabled={isDisabled || undefined}
        aria-busy={pending || undefined}
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-lg border transition-colors duration-150",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-linen-50",
          "disabled:pointer-events-none disabled:opacity-45",
          variantClasses[variant],
          iconSizeClasses[size],
          className
        )}
        {...props}
      >
        {pending ? (
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <span aria-hidden="true">{icon}</span>
        )}
      </button>
    );
  }
);

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { Button, type ButtonSize, type ButtonVariant } from "@/components/ui/Button";
import { api, queryClient } from "@/lib/api";

export function LogoutButton({
  className,
  errorClassName = "text-semantic-danger",
  onNavigate,
  size = "md",
  variant = "secondary",
}: {
  className?: string;
  errorClassName?: string;
  onNavigate?: () => void;
  size?: ButtonSize;
  variant?: ButtonVariant;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  const handleLogout = async () => {
    setPending(true);
    setError("");

    try {
      await api.logout();
      // Logout is a user-isolation boundary. Remove every cached response
      // before navigating so the next session cannot see prior user data.
      queryClient.clear();
      onNavigate?.();
      router.replace("/login");
      router.refresh();
    } catch {
      setError("Sign out failed. Please try again.");
      setPending(false);
    }
  };

  return (
    <div>
      <Button
        type="button"
        variant={variant}
        size={size}
        pending={pending}
        pendingLabel="Signing out…"
        leadingIcon={<LogOut className="h-4 w-4" />}
        className={className}
        onClick={() => void handleLogout()}
      >
        Sign out
      </Button>
      {error && (
        <p role="alert" className={`mt-1.5 px-1 text-xs ${errorClassName}`}>
          {error}
        </p>
      )}
    </div>
  );
}

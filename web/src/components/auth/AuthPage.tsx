"use client";

import { useRouter } from "next/navigation";

import { AuthForm } from "./AuthForm";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  return (
    <AuthForm
      mode={mode}
      onSuccess={() => {
        if (mode === "login") router.push("/account");
      }}
    />
  );
}

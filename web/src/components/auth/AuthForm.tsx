"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { MIN_PASSWORD_LENGTH, submitAuth } from "@/lib/auth/client";

interface Props {
  mode: "login" | "register";
  /** Called after a successful sign-in (login) or registration. */
  onSuccess: () => void;
}

export function AuthForm({ mode, onSuccess }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    const result = await submitAuth(mode, email, password);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    if (!isLogin) setNotice("Account ready. You can sign in now.");
    onSuccess();
  }

  return (
    <form onSubmit={onSubmit} className="flex max-w-sm flex-col gap-4" noValidate>
      <h1 className="text-2xl font-bold text-navy dark:text-white">
        {isLogin ? "Sign in" : "Create an account"}
      </h1>
      <label className="flex flex-col gap-1 text-sm">
        Email
        <input
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded border border-slate-300 px-3 py-2 text-base dark:bg-slate-900"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Password
        <input
          type="password"
          name="password"
          autoComplete={isLogin ? "current-password" : "new-password"}
          required
          minLength={isLogin ? undefined : MIN_PASSWORD_LENGTH}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded border border-slate-300 px-3 py-2 text-base dark:bg-slate-900"
        />
      </label>
      {!isLogin && (
        <p className="text-xs text-slate-500">At least {MIN_PASSWORD_LENGTH} characters.</p>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm text-emerald-700">
          {notice}
        </p>
      )}
      <button
        type="submit"
        disabled={busy}
        className="rounded bg-blue-600 px-4 py-2 font-medium text-white disabled:opacity-60"
      >
        {busy ? "Please wait…" : isLogin ? "Sign in" : "Create account"}
      </button>
      <p className="text-sm">
        {isLogin ? (
          <Link href="/register" className="text-blue-600 underline">
            Create an account
          </Link>
        ) : (
          <Link href="/login" className="text-blue-600 underline">
            Already have an account? Sign in
          </Link>
        )}
      </p>
    </form>
  );
}

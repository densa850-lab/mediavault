"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchCurrentUser, signOut, type CurrentUser } from "@/lib/auth/client";

type State =
  | { kind: "loading" }
  | { kind: "signed-in"; user: CurrentUser }
  | { kind: "signed-out"; warning?: string }
  | { kind: "error"; message: string };

export function AccountPanel() {
  const [state, setState] = useState<State>({ kind: "loading" });

  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    fetchCurrentUser()
      .then((user) => {
        if (active) setState(user ? { kind: "signed-in", user } : { kind: "signed-out" });
      })
      .catch((e: Error) => active && setState({ kind: "error", message: e.message }));
    return () => {
      active = false;
    };
  }, [attempt]);

  function retry() {
    setState({ kind: "loading" });
    setAttempt((n) => n + 1);
  }

  async function onSignOut() {
    const result = await signOut();
    setState(result.confirmed ? { kind: "signed-out" } : { kind: "signed-out", warning: result.message });
  }

  switch (state.kind) {
    case "loading":
      return <p>Checking your session…</p>;
    case "error":
      return (
        <div className="flex flex-col items-start gap-2">
          <p role="alert">{state.message}</p>
          <button type="button" onClick={retry} className="rounded border border-slate-300 px-4 py-2">
            Try again
          </button>
        </div>
      );
    case "signed-out":
      return (
        <div className="flex flex-col gap-2">
          <p>You are signed out.</p>
          {state.warning ? <p role="alert">{state.warning}</p> : null}
          <Link href="/login" className="text-blue-600 underline">
            Sign in
          </Link>
        </div>
      );
    case "signed-in":
      return (
        <div className="flex flex-col items-start gap-3">
          <h1 className="text-2xl font-bold text-navy dark:text-white">Your account</h1>
          <p>
            Signed in as <strong>{state.user.email}</strong>
          </p>
          <button
            type="button"
            onClick={onSignOut}
            className="rounded border border-slate-300 px-4 py-2"
          >
            Sign out
          </button>
        </div>
      );
  }
}

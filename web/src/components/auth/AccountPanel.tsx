"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchCurrentUser, signOut, type CurrentUser } from "@/lib/auth/client";

type State =
  | { kind: "loading" }
  | { kind: "signed-in"; user: CurrentUser }
  | { kind: "signed-out" }
  | { kind: "error"; message: string };

export function AccountPanel() {
  const [state, setState] = useState<State>({ kind: "loading" });

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
  }, []);

  async function onSignOut() {
    await signOut().catch(() => undefined);
    setState({ kind: "signed-out" });
  }

  switch (state.kind) {
    case "loading":
      return <p>Checking your session…</p>;
    case "error":
      return <p role="alert">{state.message}</p>;
    case "signed-out":
      return (
        <div className="flex flex-col gap-2">
          <p>You are signed out.</p>
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

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountPanel } from "@/components/auth/AccountPanel";
import { AuthForm } from "@/components/auth/AuthForm";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

afterEach(() => vi.unstubAllGlobals());

function fill(email: string, password: string) {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
}

describe("AuthForm", () => {
  it("signs in through the website's own route and calls onSuccess", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const onSuccess = vi.fn();
    render(<AuthForm mode="login" onSuccess={onSuccess} />);
    fill("a@example.com", "correct-horse-battery");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/login");
    expect(init.credentials).toBe("same-origin");
  });

  it("shows the generic error on bad credentials", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Invalid email or password." }), { status: 401 }),
      ),
    );
    const onSuccess = vi.fn();
    render(<AuthForm mode="login" onSuccess={onSuccess} />);
    fill("a@example.com", "wrong-password-1");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("enforces the 12-character minimum before calling the server on register", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<AuthForm mode="register" onSuccess={vi.fn()} />);
    fill("a@example.com", "short");
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least 12 characters");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows a rate-limit message on 429", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "x" }), { status: 429 })),
    );
    render(<AuthForm mode="login" onSuccess={vi.fn()} />);
    fill("a@example.com", "correct-horse-battery");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts");
  });
});

describe("AccountPanel", () => {
  it("shows the signed-in user and signs out", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "u1", email: "a@example.com" })))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountPanel />);
    expect(screen.getByText(/Checking your session/)).toBeInTheDocument();
    expect(await screen.findByText("a@example.com")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByText("You are signed out.")).toBeInTheDocument();
    expect(fetchMock.mock.calls[1][0]).toBe("/api/auth/logout");
  });

  it("shows signed out on 401", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    render(<AccountPanel />);
    expect(await screen.findByText("You are signed out.")).toBeInTheDocument();
  });
});

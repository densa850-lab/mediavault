import type { Metadata } from "next";

import { AuthPage } from "@/components/auth/AuthPage";

export const metadata: Metadata = { title: "Create an account · MediaVault" };

export default function RegisterPage() {
  return <AuthPage mode="register" />;
}

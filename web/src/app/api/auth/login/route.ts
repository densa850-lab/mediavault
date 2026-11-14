import { handleLogin } from "@/lib/auth/bff";

export async function POST(req: Request): Promise<Response> {
  return handleLogin(req);
}

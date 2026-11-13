import { handleRegister } from "@/lib/auth/bff";

export async function POST(req: Request): Promise<Response> {
  return handleRegister(req);
}

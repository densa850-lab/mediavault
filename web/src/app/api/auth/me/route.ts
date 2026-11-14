import { handleMe } from "@/lib/auth/bff";

export async function GET(req: Request): Promise<Response> {
  return handleMe(req);
}

/** RFC 6750 bearer shape check. Guest validity stays on the FastAPI side. */

const MIN_TOKEN_LENGTH = 20;
const MAX_TOKEN_LENGTH = 200;

export type ParsedBearer = { ok: true; token: string } | { ok: false };

export function parseBearer(header: string | null): ParsedBearer {
  if (!header) return { ok: false };
  const match = /^Bearer\s+(\S+)\s*$/i.exec(header);
  if (!match) return { ok: false };
  const token = match[1] ?? "";
  if (!bearerShapeOk(token)) return { ok: false };
  return { ok: true, token };
}

export function bearerShapeOk(token: string): boolean {
  return token.length >= MIN_TOKEN_LENGTH && token.length <= MAX_TOKEN_LENGTH && !/\s/.test(token);
}

export function unauthorizedResponse(): Response {
  return new Response(
    JSON.stringify({
      code: "unauthorized",
      message: "Bearer token is missing or invalid.",
    }),
    {
      status: 401,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        "www-authenticate": 'Bearer realm="researchmind-mcp"',
        "x-content-type-options": "nosniff",
      },
    },
  );
}

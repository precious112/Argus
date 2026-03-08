import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = ["/login", "/register", "/forgot-password", "/reset-password", "/verify-email", "/accept-invite"];
const PUBLIC_PREFIXES = ["/_next", "/favicon.ico", "/favicon.png", "/argus-logo.png", "/login/callback"];

/**
 * Decode a JWT payload without signature verification.
 * The payload is just base64-encoded (not encrypted), so no secret needed.
 * Returns null if the token is malformed.
 */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(payload));
  } catch {
    return null;
  }
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths
  if (
    PUBLIC_PATHS.includes(pathname) ||
    PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))
  ) {
    return NextResponse.next();
  }

  // Check for auth cookie
  const token = request.cookies.get("argus_token");
  if (!token?.value) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  // Validate JWT is not expired (full signature validation happens on the backend)
  const payload = decodeJwtPayload(token.value);
  if (!payload || (typeof payload.exp === "number" && payload.exp * 1000 < Date.now())) {
    const loginUrl = new URL("/login", request.url);
    const response = NextResponse.redirect(loginUrl);
    response.cookies.delete("argus_token");
    return response;
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

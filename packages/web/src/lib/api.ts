/**
 * Authenticated fetch wrapper.
 * Adds `credentials: "include"` to every request so the httpOnly
 * `argus_token` cookie is sent automatically.
 * On 401 responses, redirects to /login.
 */
export async function apiFetch(
  input: string | URL | Request,
  init?: RequestInit,
): Promise<Response> {
  const res = await fetch(input, {
    ...init,
    credentials: "include",
  });

  if (res.status === 401 && typeof window !== "undefined") {
    window.location.href = "/login";
  }

  return res;
}

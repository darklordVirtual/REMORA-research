// Client-side helper for the operator access token that gates the
// control-plane server functions (issue #55). The token is entered by the
// operator and kept in localStorage; it is sent with each control-plane call
// and checked server-side against REMORA_APP_ACCESS_TOKEN. An empty token
// makes the server refuse the call (fail closed) — the public demo does not
// expose the control plane anonymously.

const STORAGE_KEY = "remora_operator_token";

export function getOperatorToken(): string {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem(STORAGE_KEY)?.trim() ?? "";
}

export function setOperatorToken(token: string): void {
  if (typeof localStorage === "undefined") return;
  if (token.trim()) localStorage.setItem(STORAGE_KEY, token.trim());
  else localStorage.removeItem(STORAGE_KEY);
}

import { createServerFn } from "@tanstack/react-start";

/**
 * Calls Cloudflare's /user/tokens/verify endpoint to confirm the configured
 * CLOUDFLARE_API_TOKEN is live and has the expected status. Used by the
 * Cascade UI to render a health pill so users can see the REMORA AI gateway
 * to Cloudflare Workers AI is reachable before they fire a query.
 */
export const verifyCloudflareToken = createServerFn({ method: "GET" }).handler(async () => {
  const token = process.env.CLOUDFLARE_API_TOKEN;
  if (!token) {
    return { ok: false, status: "missing_token", message: "CLOUDFLARE_API_TOKEN not set" };
  }
  try {
    const res = await fetch("https://api.cloudflare.com/client/v4/user/tokens/verify", {
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    });
    const json = (await res.json()) as {
      success?: boolean;
      result?: { id?: string; status?: string; expires_on?: string | null };
      errors?: Array<{ message?: string }>;
    };
    if (!res.ok || !json.success) {
      return {
        ok: false,
        status: "invalid",
        message: json.errors?.[0]?.message ?? `HTTP ${res.status}`,
      };
    }
    return {
      ok: true,
      status: json.result?.status ?? "active",
      tokenId: json.result?.id,
      expiresOn: json.result?.expires_on ?? null,
      message: "Token verified",
    };
  } catch (err) {
    return {
      ok: false,
      status: "error",
      message: err instanceof Error ? err.message : "Unknown error",
    };
  }
});

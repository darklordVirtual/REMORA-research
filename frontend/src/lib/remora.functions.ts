// Backend-for-frontend wrapping authenticated REMORA Agent Control endpoints.
// CONTROL_SECRET never leaves the server.
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { REMORA_URLS, type AuditRow, type ExecuteResponse, type ToolName } from "./remora";
import { assertAppAccess } from "./app-access.server";

// Every control-plane-facing function requires an operator access token
// (issue #55). access_token is validated shape then checked server-side.
const accessTokenField = { access_token: z.string().min(1).max(512) };

function controlAuth(): HeadersInit {
  const secret = process.env.REMORA_CONTROL_SECRET;
  if (!secret) throw new Error("REMORA_CONTROL_SECRET is not configured");
  return {
    "content-type": "application/json",
    authorization: `Bearer ${secret}`,
  };
}

async function passthrough<T>(res: Response): Promise<T> {
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 300)}`);
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`Invalid JSON from REMORA: ${text.slice(0, 200)}`);
  }
}

export const createSession = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      ...accessTokenField,
      user_id: z.string().min(1).max(128),
      user_label: z.string().min(1).max(128).optional(),
    }),
  )
  .handler(async ({ data }) => {
    assertAppAccess(data.access_token);
    const { access_token: _t, ...body } = data;
    const res = await fetch(`${REMORA_URLS.agentControl}/sessions`, {
      method: "POST",
      headers: controlAuth(),
      body: JSON.stringify(body),
    });
    return passthrough<{ session_id: string; status: string }>(res);
  });

export const endSession = createServerFn({ method: "POST" })
  .inputValidator(z.object({ ...accessTokenField, session_id: z.string().uuid() }))
  .handler(async ({ data }) => {
    assertAppAccess(data.access_token);
    const res = await fetch(
      `${REMORA_URLS.agentControl}/sessions/${encodeURIComponent(data.session_id)}`,
      { method: "DELETE", headers: controlAuth() },
    );
    return passthrough<{ session_id: string; status: string }>(res);
  });

const executeInput = z.object({
  ...accessTokenField,
  tool: z.enum(["remora_verify_claim", "dce_search_law", "store_artifact", "audit_decision"]),
  input: z.record(z.string(), z.unknown()),
  session_id: z.string().uuid(),
  user_id: z.string().min(1).max(128),
});

export const executeTool = createServerFn({ method: "POST" })
  .inputValidator(executeInput)
  .handler(async ({ data }) => {
    assertAppAccess(data.access_token);
    const { access_token: _t, ...body } = data;
    const res = await fetch(`${REMORA_URLS.agentControl}/execute`, {
      method: "POST",
      headers: controlAuth(),
      body: JSON.stringify(body),
    });
    return passthrough<ExecuteResponse>(res);
  });

export const getAudit = createServerFn({ method: "GET" })
  .inputValidator(
    z.object({
      ...accessTokenField,
      session_id: z.string().uuid().optional(),
      limit: z.number().int().min(1).max(200).default(50),
      offset: z.number().int().min(0).default(0),
    }),
  )
  .handler(async ({ data }) => {
    assertAppAccess(data.access_token);
    const params = new URLSearchParams();
    if (data.session_id) params.set("session_id", data.session_id);
    params.set("limit", String(data.limit));
    params.set("offset", String(data.offset));
    const res = await fetch(`${REMORA_URLS.agentControl}/audit?${params.toString()}`, {
      headers: controlAuth(),
    });
    return passthrough<{ rows: AuditRow[]; count: number }>(res);
  });

export type { ExecuteResponse, AuditRow, ToolName };

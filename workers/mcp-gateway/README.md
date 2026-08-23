# remora-mcp-gateway

MCP tool calls routed through the REMORA execution path. The agent sees
ordinary tools; nothing changes until REMORA has decided it may.

Full documentation: [`docs/integrations/mcp-gateway.md`](../../docs/integrations/mcp-gateway.md).
Design and measurements: [DOC-319](../../docs/design/cloudflare-mcp-gateway-v1.md).

## Layout

| File | What it is |
| --- | --- |
| `src/index.ts` | Worker entrypoint, container binding, proposal store |
| `src/mcp.ts` | MCP protocol and the decision handling, as a pure function |
| `src/remora.ts` | The execution client — the only holder of the API credential |
| `src/tools.ts` | The MCP tool surface. Shape only; authority lives server-side |
| `wrangler.toml` | Production: container binding, `basic`, always on |
| `wrangler.dev.toml` | Development: no container, points at a local REMORA |

## Develop

```sh
docker compose -f ../../deploy/ot-pilot/docker-compose.yml up -d postgres api
npm install
npx wrangler dev --config wrangler.dev.toml --port 8791
```

```sh
claude mcp add --scope local --transport http remora-gateway http://127.0.0.1:8791/mcp
```

## Verify

```sh
npm test          # 16 protocol and governance tests
npm run type-check
```

`src/mcp.ts` is written as a pure function of (request, dependencies) so the
protocol and the governance behaviour can be tested without a Worker runtime,
a container, or a network.

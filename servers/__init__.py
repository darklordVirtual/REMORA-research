# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA server entry points.

- ``servers.api`` — governance REST API (``uvicorn servers.api:app`` /
  ``remora serve``); needs the ``api`` extra.
- ``servers.execution_api`` — /v1/execution enforcement path.
- ``servers.mcp_remora`` — MCP server exposing REMORA as assistant tools.
- ``servers.tool_registry_research`` — the research tool registry for
  ``REMORA_TOOL_REGISTRY_MODULE``.

A real package (not PEP-420) so the built wheel ships it — REM-045: the
distribution must fulfil the documented ``remora serve`` contract.
"""

# ADR-0015: The MCP server can be reached by a real MCP client

**Status:** Accepted

## Context
ADR-0011 aligned the server with the 2026-07-28 Model Context Protocol specification by modelling
its shapes as Python dictionaries. That tested the authorisation logic and nothing else. No MCP
client could connect, so nobody could watch a real client be refused, and nothing showed that the
shapes matched what a client sends.

The official `mcp` Python SDK, at 2.3.0, implements that revision: no session, cache hints on
tool lists, and a result type that asks the client for input and expects the same call again with
the answers.

## Decision
* `adjudication/mcp_server/wire.py` puts the SDK's server in front of `AdjudicationMCPServer`. It
  translates and decides nothing. Every rule stays in `server.py`, where the existing tests are.
* The tool list goes out with `ttlMs` and `cacheScope: private`, as before.
* A denied call is returned as a tool result marked as an error, carrying the code and reason, so
  an agent can read it and react.
* An irreversible call returns the SDK's input-required result holding one form request. The
  message names the officer who must confirm, the audience and the call's fingerprint. The client
  answers with the signed token (ADR-0013) and the SDK repeats the call.
* The caller's identity never comes from the request. `build_wire_server` takes a function that
  returns the delegation context for a request.
* `python -m adjudication.mcp_server` serves one officer over standard input and output, named in
  the environment by whoever configures the client. With no identity provider key configured it
  cannot verify any confirmation, so `issue_permit` never runs.
* The SDK is an optional extra. The core package still installs without it.

## Consequences
* Seven tests drive the server through `mcp.Client`. They cover the protocol version, the private
  filtered list, a denial, a confirmed permit, a token the agent signed for itself, a declined
  confirmation, a replayed token, and the standard input and output entry point started as a real
  subprocess.
* The first run through a real client passed, which is the evidence that the dictionary shapes in
  `server.py` were faithful to the specification.
* A desktop assistant or any other MCP client can now be pointed at the server and shown the
  refusal.

## Open questions
* Over HTTP, the delegation context has to come from a verified access token. The SDK has the
  pieces for that; this repository does not use them.
* The client supplies the confirmation through a form field. A real deployment would send the
  officer to the identity provider's own approval page, which the specification supports as a URL
  request, so the token never passes through the agent's hands as typed text.
* The tool argument schemas in `wire.py` are written by hand next to the registry. They can drift
  from the handlers.

"""Run the approval service against a real sign-in service.

    OIDC_ISSUER=http://localhost:8089/realms/council python -m adjudication.identity

OIDC_AUDIENCE is the audience this service expects in an officer's access
token (default `adjudication-approval`). APPROVAL_PORT is where it listens
(default 8090). The signing key is made at start-up and lives only in this
process: restart the service and the old confirmations stop verifying, which
within their five-minute life is what a restart should mean.
"""
from __future__ import annotations

import contextlib
import os
import sys

from adjudication.agents.officer import RESUME_AUDIENCE
from adjudication.identity.approval import ApprovalService, serve
from adjudication.identity.oidc import OidcVerifier


def main() -> int:
    issuer = os.getenv("OIDC_ISSUER", "").strip()
    if not issuer:
        print("OIDC_ISSUER is not set: refusing to approve anything for nobody", file=sys.stderr)
        return 2
    verifier = OidcVerifier.discover(issuer, os.getenv("OIDC_AUDIENCE", "adjudication-approval"))
    service = ApprovalService(
        verifier, audiences=frozenset({RESUME_AUDIENCE, "adjudication-mcp"}),
        on_approval=lambda who, aud, tool: print(f"approved: {who} {tool} for {aud}", flush=True))
    port = int(os.getenv("APPROVAL_PORT", "8090"))
    httpd = serve(service, port=port)
    print(f"approval service on http://127.0.0.1:{port}, officers sign in at {issuer}", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The approval service: the one place that can sign an officer's confirmation.

Until now a function in this repository stood in for it (ADR-0013). This is the
service itself. It does two things.

1. It checks who is asking, against the council's real sign-in service. The
   caller presents an access token; `OidcVerifier` checks the token's signature
   against the keys that service publishes, and that it was issued for this
   service, is in date and carries the `officer` role.
2. It signs a confirmation for exactly the call the officer was shown, with a
   key only this process holds, and publishes the matching public key so the
   permit server and the case graph can check it (`JwksKeys`).

The agent never holds the officer's access token. The officer's own browser or
command-line client signs in and calls this service. What the agent's side
carries afterwards is the confirmation, which approves one call for five
minutes and nothing else.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec

from adjudication.identity.jwks import jwk_from_ec_key
from adjudication.identity.oidc import OidcVerifier, SignInRejected
from adjudication.mcp_server.confirmation import issue_confirmation
from adjudication.runtime.jws import new_key

MAX_BODY = 64 * 1024


class NotAnOfficer(Exception):
    """Signed in, but without the role that may approve."""


@dataclass
class ApprovalService:
    verifier: OidcVerifier
    # Servers a confirmation may be addressed to. One for another audience is
    # never signed, so this service cannot be used to approve calls elsewhere.
    audiences: frozenset[str]
    key: ec.EllipticCurvePrivateKey = field(default_factory=new_key)
    kid: str = "approval-1"
    required_role: str = "officer"
    wall_clock: Callable[[], float] = time.time
    # called with (officer, audience, tool) for each confirmation signed
    on_approval: Callable[[str, str, str], None] = lambda *_: None

    def jwks(self) -> dict[str, Any]:
        return {"keys": [jwk_from_ec_key(self.key.public_key(), self.kid)]}

    def confirm(self, access_token: str, *, audience: str, tool: str,
                arguments: dict[str, Any]) -> tuple[str, str]:
        """Returns (officer id, confirmation). Raises SignInRejected, NotAnOfficer or ValueError."""
        now = self.wall_clock()
        officer = self.verifier.verify(access_token, now=now)
        if self.required_role not in officer.roles:
            raise NotAnOfficer(officer.officer_id)
        if audience not in self.audiences:
            raise ValueError("unknown audience")
        if not isinstance(tool, str) or not tool or not isinstance(arguments, dict):
            raise ValueError("a confirmation approves one tool call with its arguments")
        # The officer named in the token is always the one who signed in. The
        # request has no field for it, so nobody can ask on another's behalf.
        token = issue_confirmation(self.key, self.kid, officer=officer.officer_id,
                                   audience=audience, tool=tool, arguments=arguments, now=now)
        self.on_approval(officer.officer_id, audience, tool)
        return officer.officer_id, token


def handler_for(service: ApprovalService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/.well-known/jwks.json":
                self._send(200, service.jwks())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            self._send(*self._confirm())

        def _confirm(self) -> tuple[int, dict[str, Any]]:
            if self.path != "/confirmations":
                return 404, {"error": "not found"}
            scheme, _, token = self.headers.get("Authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not token:
                return 401, {"error": "sign in first"}
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise ValueError
                body = json.loads(self.rfile.read(length))
                audience, tool, arguments = body["audience"], body["tool"], body["arguments"]
            except (ValueError, KeyError, TypeError):
                return 400, {"error": "expected audience, tool and arguments"}
            try:
                officer, confirmation = service.confirm(token.strip(), audience=audience,
                                                        tool=tool, arguments=arguments)
            except SignInRejected as e:
                return 401, {"error": e.reason}
            except NotAnOfficer:
                return 403, {"error": "signed in, but not as an officer"}
            except ValueError as e:
                return 400, {"error": str(e)}
            return 200, {"officer_id": officer, "confirmation": confirmation}

        def log_message(self, *_args: Any) -> None:  # the service logs approvals itself
            pass

    return Handler


def serve(service: ApprovalService, host: str = "127.0.0.1", port: int = 8090) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), handler_for(service))

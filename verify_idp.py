"""One referred case decided through a real sign-in service. Needs `make idp`.

Three programs take part, as they would in a council:

  Keycloak            signs officers in and publishes its public keys
  approval service    checks the sign-in, signs the officer's confirmation
  the case graph      learns the approval service's key from its URL

Nothing is shared by hand between them: no key file, no copied secret.

The officer signs in here with a password sent straight to Keycloak. That is
for a script only. A person signs in at Keycloak's own page in a browser, and
no other program ever sees the password.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from langgraph.types import Command

from adjudication.agents.graph import build_graph
from adjudication.agents.officer import RESUME_AUDIENCE, RESUME_TOOL, resume_call
from adjudication.data.corpus import CORPUS
from adjudication.identity.jwks import JwksKeys
from adjudication.runtime.audit import AuditLog

ISSUER = os.getenv("OIDC_ISSUER", "http://localhost:8089/realms/council")
APPROVAL = "http://127.0.0.1:8090"
CASE = "C-2209"
REASON = "height of 5.1 m exceeds the 4 m limit"


def sign_in(username: str, password: str) -> str:
    body = urllib.parse.urlencode({"grant_type": "password", "client_id": "officer-desk",
                                   "username": username, "password": password}).encode()
    with urllib.request.urlopen(ISSUER + "/protocol/openid-connect/token", body, timeout=10) as r:
        return json.loads(r.read())["access_token"]


def ask(token: str | None, decision: str, rationale: str | None) -> tuple[int, dict]:
    req = urllib.request.Request(
        APPROVAL + "/confirmations", method="POST",
        data=json.dumps({"audience": RESUME_AUDIENCE, "tool": RESUME_TOOL,
                         "arguments": resume_call(CASE, decision, rationale)}).encode(),
        headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return ok


def main() -> int:
    try:
        urllib.request.urlopen(ISSUER + "/.well-known/openid-configuration", timeout=5)
    except OSError:
        print(f"no sign-in service at {ISSUER}. Start one with `make idp`.", file=sys.stderr)
        return 2

    service = subprocess.Popen([sys.executable, "-m", "adjudication.identity"],
                               env={**os.environ, "OIDC_ISSUER": ISSUER})
    try:
        keys = JwksKeys(APPROVAL + "/.well-known/jwks.json")
        for _ in range(50):
            time.sleep(0.2)
            try:
                urllib.request.urlopen(APPROVAL + "/.well-known/jwks.json", timeout=2)
                break
            except OSError:
                continue

        audit = AuditLog()
        graph = build_graph(CORPUS, audit, now=dt.datetime.now(dt.UTC), officer_keys=keys)
        cfg = {"configurable": {"thread_id": CASE}}
        res = graph.invoke({"case_id": CASE, "risk_tier": "STANDARD", "trace": [], "guard_events": [],
                            "narrative": "Rear extension. Setback 0.6 m. Height 5.1 m. Coverage 62%."},
                           cfg)
        results = [check("the case is referred to an officer", "__interrupt__" in res)]

        status, body = ask(None, "REFUSE", REASON)
        results.append(check("no sign-in, no confirmation", status == 401, body.get("error", "")))

        status, body = ask(sign_in("clerk-3", "demo-only-clerk"), "REFUSE", REASON)
        results.append(check("a signed-in clerk is not an officer", status == 403,
                             body.get("error", "")))

        status, body = ask(sign_in("off-014", "demo-only-officer"), "REFUSE", REASON)
        results.append(check("officer off-014 signs in and approves", status == 200,
                             f"confirmed as {body.get('officer_id')}"))
        reply = {"officer_id": "off-014", "decision": "REFUSE", "rationale": REASON,
                 "confirmation": body.get("confirmation", "")}

        for label, forged in [
            ("the decision cannot be changed to GRANT", {**reply, "decision": "GRANT"}),
            ("the reason cannot be changed", {**reply, "rationale": "applicant was rude"}),
            ("another officer's name cannot be put on it", {**reply, "officer_id": "off-008"}),
        ]:
            try:
                graph.invoke(Command(resume=forged), cfg)
                results.append(check(label, False, "it was accepted"))
            except Exception as e:  # the reply is refused inside LangGraph's validation
                results.append(check(label, "confirm" in str(e), str(e).splitlines()[-1][:70]))

        out = graph.invoke(Command(resume=reply), cfg)
        last = audit.for_case(CASE)[-1]
        results.append(check("the genuine reply decides the case",
                             out.get("decision") == "REFUSE" and last.actor == "officer:off-014",
                             f"{out.get('decision')}, logged as {last.actor}"))
    finally:
        service.terminate()
        service.wait(timeout=5)

    print(f"\n{sum(results)} of {len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

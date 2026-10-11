# ADR-0013: An irreversible action needs a signed, single-use confirmation bound to the call

**Status:** Accepted. Closes the first open question of ADR-0011.

## Context
ADR-0011 made an irreversible tool stop and ask for a confirmation from the officer the agent acts
for. The confirmation was a field the client sent back:
`{"confirmed": true, "confirmedBy": "off-7"}`. The client is the agent's half of the connection,
so the agent could write that field itself and issue a permit with no officer involved.

Two smaller gaps sat beside it. Spent confirmations were held in a Python set and forgotten on
restart. And a confirmation was keyed by tool, case and officer, so nothing tied it to the other
arguments of the call.

The 2026-07-28 MCP authorisation work points the same way for access tokens: bind the token to
who presents it and check the scope at the moment of the call. A confirmation needs the same
treatment, applied to one action instead of to a session.

## Decision
A confirmation is a compact JWS (RFC 7515) signed with ES256 by the identity provider after the
officer approves the action there. The server accepts it only when all of these hold:

* the signature verifies against an identity provider key the server already trusts, named by
  `kid`;
* `alg` is ES256 and `typ` is `adjudication-confirmation+jwt`. Both are fixed by the server, not
  read from the token;
* `aud` is this server;
* `sub` is the officer named in the delegation context of the call;
* `call` equals the SHA-256 of the tool name and arguments in RFC 8785 canonical form;
* `exp - iat` is at most 300 seconds, `iat` is not in the future, and `exp` has not passed,
  allowing 30 seconds of clock skew;
* `jti` has not been spent. Spent ids are stored in SQLite until the token would have expired.

The id is spent only after every other check passes. A token sent to the wrong call by mistake can
still be sent to the right one.

With no trusted key configured, no irreversible call can be confirmed (ADR-0007).

The input request now carries `audience` and `call`, so the identity provider knows exactly what
it is asking the officer to approve.

## Consequences
* `tests/test_confirmation.py` has 26 tests. Each sends a token wrong in one way: forged key,
  unknown key, other officer, other server, other case, other tool, expired, issued in the future,
  too long-lived, carried to another officer's call, `alg: none`, `alg: HS256`, a correctly signed
  token of another type, and malformed input. Replay is tested within one server and across a
  restart that shares the database file.
* Each guard was switched off in turn to check that a test fails. The algorithm and type check
  survived at first, because the forged-header tests failed on the signature before reaching it.
  `test_another_token_from_the_same_provider_is_not_a_confirmation` now covers it.
* The ES256 code shared with the agent card moved to `adjudication/runtime/jws.py`, so both use
  the same conversion between DER and the raw form JWS carries.
* The old field-based confirmation is refused. `test_unsigned_confirmation_field_no_longer_counts`
  keeps it that way.

## Open questions
* The identity provider is simulated by `issue_confirmation`. A real one must issue tokens of this
  type, publish its public key and show the officer which call they are approving. That needs the
  identity team.
* A stolen token can be used by anyone until it is spent or expires, inside five minutes and for
  one call only. Binding it to the client's key, as DPoP does for access tokens, would close that.
  It needs the client to hold a key, which this model does not have.

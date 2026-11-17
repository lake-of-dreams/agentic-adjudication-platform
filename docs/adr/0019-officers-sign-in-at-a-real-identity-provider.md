# ADR-0019: Officers sign in at a real sign-in service, and an approval service signs for them

**Status:** Accepted

## Context
Confirmations were signed by a function in this repository, with a key the tests made (ADR-0013,
ADR-0017). Every check on the token was real. The claim underneath it, that officer off-014 had
signed in and approved, was not: nothing signed anyone in.

A council already has a sign-in service. Most speak OpenID Connect (OIDC): after sign-in they
issue an access token saying who the person is and which roles they hold, signed with a key whose
public half they publish. Such a service will not issue this project's confirmation token, which is
bound to one tool call. Asking an identity team to add a custom token type to their product is how
a design stays on paper.

## Decision
* A small **approval service** sits between the two. An officer's own client presents the access
  token from sign-in. The service checks it against the sign-in service's published keys, requires
  the `officer` role, and signs a confirmation for exactly the call it was sent.
* The officer named in the confirmation is the one named in the access token. The request has no
  field for it.
* The sign-in check fixes what it accepts: the issuer and audience it was configured with, an
  algorithm that matches the kind of key published, an access token and not an ID token. The key
  set's address comes from the issuer's discovery document, never from a token.
* The approval service publishes its own public key as a key set. The case graph and the permit
  server take a key source in place of a fixed dictionary. `JwksKeys` follows a published key set:
  an unknown key id triggers one refetch, refetches are at least 30 seconds apart, and keys are
  dropped if the signer has been unreachable for a day.
* The agent never holds the officer's access token. It carries the confirmation, which approves one
  call for five minutes.
* `make idp` runs Keycloak 26.8.2 in Docker with one officer and one clerk. `make idp-check` decides
  a referred case through it.

## Consequences
* 23 tests against a local sign-in service that publishes the same two documents a real one does.
  They cover a wrong issuer, audience or date, an ID token, a token with no algorithm, a token
  keyed with the public key, another service's key, a discovery document for a different issuer,
  key rotation on both sides, an unreachable signer, a clerk, and a request with no sign-in.
* Against Keycloak, eight checks passed. Three programs ran as separate processes and shared no key
  or secret by hand. A clerk who signed in was refused. The officer's confirmation decided the
  case, and the same confirmation with the decision, the reason or the officer's name changed did not.
* Keycloak signs with RS256 by default. The sign-in check accepts RS256 and ES256, each only with a
  published key of the matching kind. Confirmations stay ES256.
* The package still installs with no new dependency. The key fetch and both services use the
  standard library.

## Open questions
* The approval service has no screen. It signs what the officer's client sends, so a client that
  shows the officer one call and sends another is trusted. A page served by the approval service
  itself, showing the case, the decision and the reason before signing, closes that.
* The check script signs in with a password sent to Keycloak directly. A person must sign in at
  Keycloak's own page, with the authorization code flow, so no other program sees the password.
* The approval service's signing key is made at start-up and held in memory. Production needs a
  managed key and a rotation plan; `JwksKeys` already follows a rotation.
* Role names and the claim that carries the officer's id are Keycloak's. Another sign-in service
  will name them differently, and the mapping is configuration that has been tried with one product.

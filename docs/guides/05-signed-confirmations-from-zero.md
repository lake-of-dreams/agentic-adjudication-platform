# Guide 5. Signed confirmations from zero

## How to read this guide

**Who it is for.** Engineers who are new to signed tokens and to agents that act on someone's
behalf. You should be able to read Python. You do not need to know what a JSON Web Signature is,
what an identity provider does, or how an elliptic-curve key works. Each is explained when it first
appears.

**What you will know at the end.** Why an AI agent must not be able to approve its own
irreversible actions, and how this repository makes that impossible. You will be able to read a
confirmation token by hand, say what each of its fields is for, and name the attack each check on
the server stops. You will also know how the tests prove that each check is really there.

**How it is organised.**

1. Part 1 explains the problem: an agent that can say "yes" on an officer's behalf.
2. Part 2 explains the building blocks: keys, signatures and tokens.
3. Part 3 takes a confirmation token apart, field by field.
4. Part 4 walks through one confirmation from request to permit.
5. Part 5 goes through the seven checks the server makes, and the attack each one stops.
6. Part 6 explains why spent tokens are kept in a database.
7. Part 7 shows how the tests prove every check is needed, including the one that was not tested.
8. Part 8 lists the design principles.
9. Part 9 lists what is unresolved.

A glossary at the end defines every term.

You can read it front to back like a short book. Each part builds on the one before it.

## The idea in one paragraph

Some actions cannot be undone, such as issuing a building permit. This system lets an AI agent
prepare such an action, but it must not carry it out unless the human officer responsible agrees.
The first version asked the agent's side to pass back a note saying "the officer agreed". The
agent could write that note itself. Now the officer's agreement comes from a separate sign-in
service, which seals it so that nobody else can make or change it. The seal names the officer, the
exact action, and a five-minute window, and it works once. The agent can deliver the sealed note
but can never write one.

## A note on accuracy

The code described here is in `adjudication/mcp_server/confirmation.py`,
`adjudication/mcp_server/server.py` and `adjudication/runtime/jws.py`. The tests are in
`tests/test_confirmation.py`. Every behaviour described has a test, and the test names are given.

The token format follows JSON Web Signature (RFC 7515) and borrows the claim names of JSON Web
Token (RFC 7519). The idea of binding a token to one exact call follows the direction of the
Model Context Protocol's 2026-07-28 authorisation work, which tightened how access tokens are tied
to the client and the moment of use.

Simplified for teaching: the identity provider is simulated by a function in the same repository,
and the "officer approves on a screen" step is not built. Part 9 says what a real deployment needs.

This is a reference design, not a production security component. It has not been reviewed by a
security team.

## The running example

Ms Priya Nair applied to build a garden studio at 14 Orchard Row, Millbrook. Her case is C1. The
system has assessed it and found every criterion met. An AI agent, `agent-1`, works for officer
`off-7`, who is accountable for the decision. The agent now wants to call the tool `issue_permit`
for case C1.

Issuing a permit cannot be undone. Once the applicant holds it, builders are booked and money is
spent. So the call must wait for off-7's agreement.

The times, names and identifiers are invented. The checks and their results are real output from
the code.

---

## Part 1. The problem: an agent that can say "yes" for someone else

An agent acts for a person, so whatever it can say, it can say in that person's name. If the agent
can also say "and the person agreed", the person's agreement is no longer a control.

### 1.1 Acting on someone's behalf

When off-7 asks the agent to work on case C1, the agent's calls carry off-7's identity and limits.
The server that runs the tools checks every call against off-7's role and against the cases off-7
may touch. Guide 1 and Part 5 of the README describe those checks. This is called acting on behalf
of someone.

Acting on behalf of someone is safe for reading a case file. It is not enough for an action that
cannot be undone. For that, the server asks the person to confirm, in the moment, that they want
this exact action taken.

### 1.2 The first version

The first version of the confirmation worked like this.

1. The agent called `issue_permit` for case C1.
2. The server answered "input required: confirmation from off-7".
3. The agent's side sent the call again with `{"confirmed": true, "confirmedBy": "off-7"}`.
4. The server checked that `confirmedBy` was off-7 and issued the permit.

Notice who sends the message in step 3. It is the agent's side of the connection: the agent, or
the software it runs in. Nothing in that message comes from off-7. The agent can type those words
itself, and the server cannot tell the difference.

This is a case of a control that the controlled party can satisfy. It looks like a check, it is
tested, and it stops nothing.

### 1.3 What a real confirmation needs

A confirmation that means something needs three properties.

| Property | Plain meaning | In the running example |
|---|---|---|
| Unforgeable | Only someone other than the agent can produce it | Only the council's sign-in service can make one |
| Specific | It approves one exact action, not "anything for a while" | It approves `issue_permit` for case C1, nothing else |
| Single use | Using it once uses it up | Sending it a second time issues nothing |

Part 2 introduces the tools that give these properties.

## Part 2. Keys, signatures and tokens

A signed token is a short piece of text that proves who wrote it and that nobody changed it. This
part builds that idea from the ground up.

### 2.1 A key pair

Imagine a padlock that comes with two different keys. One key can only lock it. The other can only
unlock it. You keep the locking key secret and hand out copies of the unlocking key to anyone.
Anyone can then check that a box was locked by you, but only you can lock one.

In cryptography this is a **key pair**. The **private key** signs, and is kept secret. The
**public key** checks signatures, and can be shared freely. The method this repository uses is
called **ES256**: elliptic-curve signatures on the P-256 curve, with the SHA-256 hash. The name
matters only so you can recognise it. What matters is the property: holding the public key lets you
check, never sign.

**Example.** The council's sign-in service generates a key pair. It keeps the private key. It
gives the public key to the permit server, under the name `idp-1`. When a token arrives signed with
the private key, the server checks it with `idp-1` and knows the sign-in service made it. The agent
has only seen the public key, so it cannot make a token that passes.

### 2.2 Why not a shared secret

There is a simpler kind of signing in which signer and checker share one secret, called **HMAC**.
It is fast and common. It has one fatal property here: anyone who can check a signature can also
make one, because checking and signing use the same secret. A permit server holding the HMAC secret
could mint its own confirmations. So could anyone who stole the secret from it.

With a key pair, the permit server holds only the public key. Even if an attacker stole everything
on the permit server, they could not forge a confirmation. The README's Part 6 makes the same
argument for the agent card.

### 2.3 The identity provider

An **identity provider** is the service that signs people in and vouches for who they are. Most
organisations already run one. When you sign in to work systems with one password and get a code
on your phone, that is an identity provider at work.

Here, the identity provider has one extra job. When the agent wants an irreversible action, the
officer is shown the action and approves it there. The identity provider then signs a token saying
so. Because the officer approves on a screen the agent does not control, the agent cannot approve
on the officer's behalf.

### 2.4 A token

A **token** is a short piece of signed data that says who someone is and what they approved. The
format used here is a **JSON Web Signature (JWS)** in its compact form: three parts separated by
dots.

```
eyJhbGciOiJFUzI1NiIsInR5cCI6ImFkanVkaWNhdGlvbi1jb25maXJtYXRpb24rand0Iiwia2lkIjoiaWRwLTEifQ
.eyJzdWIiOiJvZmYtNyIsImF1ZCI6ImFkanVkaWNhdGlvbi1tY3AiLC...
.Mx3k...
```

*Figure 1. A token's three parts. The first two are ordinary JSON, encoded so they survive being
sent as text. The third is the signature over the first two.*

1. The **header** says how the token was signed and with which key.
2. The **payload** says what the token claims. Each item in it is called a **claim**.
3. The **signature** is made by the private key over the header and payload together.

The encoding is **base64url**, a way of writing bytes as letters, digits, `-` and `_`. It is not
encryption. Anyone can decode the header and payload and read them. A token is signed, not secret.

## Part 3. A confirmation token, field by field

Decoded, the token for Ms Nair's permit looks like this.

```
header:  {"alg": "ES256", "typ": "adjudication-confirmation+jwt", "kid": "idp-1"}

payload: {"sub":  "off-7",
          "aud":  "adjudication-mcp",
          "iat":  1800000000,
          "exp":  1800000300,
          "jti":  "4f1c9e0b...",
          "call": "q3Jf...Zk"}
```

*Figure 2. The decoded confirmation. Look at `call`: it is what ties the approval to one exact
action.*

| Field | Plain meaning | In the running example |
|---|---|---|
| `alg` | The signing method | ES256 |
| `typ` | What kind of token this is | A confirmation, not a sign-in token |
| `kid` | Which public key checks it | The sign-in service's key, `idp-1` |
| `sub` | Who confirmed: the subject | Officer off-7 |
| `aud` | Which server it is for: the audience | The permit server, `adjudication-mcp` |
| `iat` | When it was issued, in seconds since 1970 | 10:00:00 |
| `exp` | When it stops being valid | 10:05:00, five minutes later |
| `jti` | A unique id for this one token | A random value, used to spot reuse |
| `call` | A fingerprint of the exact call approved | `issue_permit` with `{"case_id": "C1"}` |

### 3.1 The fingerprint of a call

The `call` field is a **hash**: a short, fixed-length fingerprint computed from some data. Change
one character of the data and the fingerprint changes completely. You cannot work backwards from
the fingerprint to the data, and you cannot find different data with the same fingerprint.

The data hashed here is the tool name and its arguments:

```
{"tool": "issue_permit", "arguments": {"case_id": "C1"}}
```

Before hashing, that object is written in its **canonical form**, defined by RFC 8785. JSON allows
the same object to be written in many ways: keys in any order, spaces or none. The canonical form
picks exactly one, so the same call always gives the same bytes and the same fingerprint. Without
it, a client writing `{"arguments": ..., "tool": ...}` would produce a different fingerprint for
the same call, and confirmations would fail at random.

**Example.** The fingerprint of `issue_permit` for C1 is one value. The fingerprint of
`issue_permit` for C2 is a completely different value. A token carrying the first cannot approve
the second, because the server computes the fingerprint of the call in front of it and compares.

## Part 4. One confirmation, step by step

This is the whole journey of Ms Nair's permit, in order. Each step names who acts.

1. The agent calls `issue_permit` with `{"case_id": "C1"}` on behalf of off-7.
2. The server runs the three registry checks: off-7 has the officer role, may take irreversible
   actions, and may touch case C1. Any failure ends the call here.
3. The server sees the tool is irreversible and answers "input required". The request names off-7,
   the audience `adjudication-mcp`, and the fingerprint of the call.
4. The agent's side passes that request to the council's identity provider.
5. The identity provider shows off-7 the action: issue a permit for case C1.
6. Off-7 approves at 10:00:00.
7. The identity provider signs a token with `sub` off-7, the audience and fingerprint from step 3,
   a fresh `jti`, and `exp` at 10:05:00.
8. The agent's side sends the call again at 10:00:04, with the token attached.
9. The server runs the seven checks in Part 5. All pass.
10. The server records the token's `jti` as spent.
11. The server issues the permit and records that off-7 authorised it.

Notice the order of steps 2 and 3. The server checks whether the call is allowed at all before it
asks anyone to confirm. Asking for confirmation of a call that would be refused anyway would tell
the caller that the tool exists. `test_unauthorised_call_is_denied_before_any_confirmation` holds
that order.

## Part 5. The seven checks, and what each one stops

The server accepts a token only if every check below passes. Each row names the attack the check
stops. The tests in `tests/test_confirmation.py` send a token wrong in exactly that one way and
confirm the permit is not issued.

| Check | Plain meaning | Attack it stops | Test case |
|---|---|---|---|
| 1. Signature | The token was signed by a key the server trusts | The agent signs its own token with a key it made | `key: new_key()` gives "bad signature" |
| 1b. Known key | The `kid` names a trusted key | A token signed by some other service | `kid: idp-9` gives "does not trust" |
| 2. Type and algorithm | It is a confirmation, signed with ES256 | A genuine sign-in token from the same provider reused as approval | `test_another_token_from_the_same_provider_is_not_a_confirmation` |
| 3. Audience | It was issued for this server | A confirmation for the billing server replayed here | `audience: billing-mcp` |
| 4. The call | Its fingerprint matches this exact call | Approval for case C2 used on case C1, or for one tool used on another | `arguments: C2`, `tool: request_information` |
| 5. The officer | `sub` is the officer this call acts for | Off-8's approval carried into off-7's call | `officer: agent-1`, call made for `off-8` |
| 6. Freshness | Issued no later than now, expires soon, lives at most five minutes | An old approval saved and used next week | expired, future, and `lifetime_s: 86400` |
| 7. Not used | Its `jti` has not been seen before | The same approval used to issue the permit twice | `test_same_token_cannot_run_twice` |

### 5.1 Why the algorithm is fixed by the server

A token's header says which algorithm signed it. A careless verifier reads that field and uses
whatever it says. Two well-known attacks follow. One sets `alg` to `none`, meaning "not signed",
and some libraries accept it. The other sets `alg` to HMAC and signs with the server's public key
as if it were a shared secret. The server, told to use HMAC, checks with that same public key, and
the forgery passes.

This server never asks the token which algorithm to use. It requires ES256 and the confirmation
type, and refuses anything else before checking the signature. The tests send `alg: none` and
`alg: HS256` and both are refused.

### 5.2 Why the lifetime is capped at five minutes

An officer approves something they are looking at, and the action runs seconds later. Five minutes
covers a slow network and a distracted officer. A token valid for a day is not a confirmation. It
is a standing permission that anyone holding it can use. The server refuses any token whose `exp`
is more than 300 seconds after its `iat`, even if the identity provider signed it that way.

Clocks on two machines rarely agree exactly, so the server allows 30 seconds of difference either
way. This is called **clock skew**.

**Example.** The token was issued at 10:00:00 and expires at 10:05:00. The server's clock reads
10:05:20 when the token arrives. That is past `exp`, but within the 30-second allowance, so it is
accepted. At 10:05:31 it is refused as expired.

### 5.3 Why the check order matters for the id

The `jti` is recorded as spent only after every other check has passed. If the agent first sends
the token with the wrong case by mistake, that attempt fails on the fingerprint, and the token is
still unspent. It can then be sent with the right case and work.

**Example.** At 10:00:02 the agent sends the token with `{"case_id": "C2"}`. Check 4 fails: the
token approves C1. The `jti` is not recorded. At 10:00:04 the agent sends it with
`{"case_id": "C1"}`. All checks pass and the permit is issued. `test_a_refused_token_is_not_spent`
holds this.

If the order were reversed, any mistaken attempt would burn the officer's approval and they would
have to approve again. Worse, an attacker who saw the token could burn it on purpose by sending it
to the wrong call first.

### 5.4 When nothing is configured

If the server has no trusted identity provider key configured, no irreversible call can ever be
confirmed. This is called **failing closed**: when in doubt, refuse. The opposite, failing open,
would mean a missing configuration silently turns the control off.
`test_no_trusted_key_means_nothing_irreversible_runs` holds it.

## Part 6. Why spent tokens live in a database

The server must remember every `jti` it has accepted, at least until that token would have expired.
Otherwise the same token could be sent twice.

### 6.1 The first version forgot on restart

The first version kept spent confirmations in a Python set, which lives in memory. When the server
restarted, for a deployment or a crash, the set was empty. Any token issued in the last five
minutes could be sent again and would be accepted.

### 6.2 The fix

Spent ids are now kept in SQLite, a database that lives in a single file and needs no server. The
table has two columns: the id and when its token expires. The id column is the **primary key**,
which means the database itself refuses a second row with the same id. That refusal is how the
server knows a token was used before.

Each time an id is claimed, rows for tokens that expired more than 30 seconds ago are deleted.
Those tokens would fail the freshness check anyway, so remembering them serves no purpose.

**Example.** At 10:00:04 the server records the token's id. At 10:01:00 the server restarts. At
10:01:10 the agent sends the same token again. The new process opens the same file, finds the id,
and refuses with "already used". `test_replay_is_refused_after_a_restart` does exactly this with
two server objects sharing one file.

### 6.3 What this does not cover

One SQLite file serves one machine. If several copies of the server run behind a load balancer,
each with its own file, a token spent on one copy is unknown to the others. That needs a shared
store, such as the same database the checkpoints move to (see Guide 7, Part 6).

## Part 7. Proving each check is needed

A test suite can pass while testing nothing. A check that is never reached by any failing input
looks covered and is not. This repository checks its tests the same way it checks its release gate
(README Part 8.2): by breaking the code on purpose and confirming a test fails.

### 7.1 Mutation testing, by hand

Each check in `verify_confirmation` was switched off in turn, by replacing its condition with
`False`, and the whole suite was run.

| Check switched off | Did a test fail? | Which |
|---|---|---|
| The call fingerprint | Yes | `test_a_refused_token_is_not_spent` and the C2 case |
| The officer (`sub`) | Yes | `test_every_refusal_is_recorded_with_its_reason` |
| The single-use store | Yes | `test_replay_is_refused_after_a_restart` |
| The five-minute cap | Yes | the `lifetime_s: 86400` case |
| The algorithm and type | **No, at first** | none |

### 7.2 The check that nothing tested

The algorithm and type check survived. Every test that sent a bad header also failed on the
signature, because changing the header changes what the signature covers. The signature check
caught them first, so the algorithm check was never the reason for a refusal.

The case that only the type check stops is a token that is correctly signed, by the trusted key,
with the right claims, but is the wrong kind of token. An identity provider issues many kinds:
sign-in tokens, access tokens, refresh tokens. If one of those carried matching claims, nothing
else would stop it.

`test_another_token_from_the_same_provider_is_not_a_confirmation` builds exactly that: a token
signed by the real key with `typ: JWT`. With the type check switched off, it passes and the permit
is issued. With the check on, it is refused. The check is now proven necessary.

Notice what this shows. The algorithm check was correct code all along. It was simply untested,
and untested code can be deleted by the next person who tidies up without anything failing.

## Part 8. Design principles

**1. The party a control constrains must not be able to satisfy it.** A confirmation the agent can
write is no confirmation. It must come from somewhere the agent cannot reach.

**2. Approve an action, not a session.** The token names the exact tool and arguments. Approval to
issue a permit for C1 says nothing about C2.

**3. Short-lived and single-use.** Five minutes and one use. A stolen token is worth one action in
one window.

**4. The verifier decides how to verify.** The algorithm and token type are fixed in the server,
never read from the token.

**5. Check everything before spending anything.** The id is recorded only after every other check
passes, so a mistaken call does not burn a valid approval.

**6. Fail closed on missing configuration.** No trusted key means nothing irreversible runs.

**7. Every check has a test that fails without it.** Proven by switching each one off.

## Part 9. What is unresolved

1. **The identity provider is simulated.** `issue_confirmation` plays its part. A real deployment
   needs the council's identity team to issue tokens of this type, publish the public key, and
   build the screen where the officer sees the call being approved.
2. **Showing the officer what they approve.** The token carries a fingerprint, which a person cannot
   read. The identity provider must show the tool and arguments in plain words, and must compute
   the fingerprint from exactly what it showed. Otherwise an agent could show one action and get
   another approved.
3. **A stolen token works for its five minutes.** Anyone holding it can use it once. Tying the
   token to a key the client holds, as the DPoP standard does for access tokens, would close this.
   It needs the client to hold a key, which this model does not have.
4. **One machine's memory of spent tokens.** Several server copies need a shared store (Part 6.3).
5. **Key rotation.** The server trusts keys by `kid`. Rotating the identity provider's key means
   adding the new key before the old one stops being used, then removing the old one. Who does that,
   and how often, is not decided.

## Glossary

| Term | Plain meaning | Explained in |
|---|---|---|
| Acting on behalf of | An agent making calls with a person's identity and limits | Part 1.1 |
| `aud` (audience) | The claim naming which server a token is for | Part 3 |
| base64url | A way of writing bytes as letters, digits, `-` and `_`; encoding, not encryption | Part 2.4 |
| Canonical form | One agreed way of writing a JSON object, so its bytes are always the same | Part 3.1 |
| Claim | One item of information in a token's payload | Part 2.4 |
| Clock skew | The difference between two machines' clocks; 30 seconds is allowed here | Part 5.2 |
| ES256 | Elliptic-curve signing on P-256 with SHA-256; sign with a private key, check with a public one | Part 2.1 |
| `exp` | The claim saying when a token stops being valid | Part 3 |
| Fail closed | Refusing when in doubt, including when configuration is missing | Part 5.4 |
| Fingerprint of a call | The hash of a tool name and its arguments, in canonical form | Part 3.1 |
| Hash | A short, fixed-length fingerprint of some data that changes completely if the data changes | Part 3.1 |
| HMAC | Signing with a secret shared by signer and checker, so any checker can also sign | Part 2.2 |
| `iat` | The claim saying when a token was issued | Part 3 |
| Identity provider | The service that signs people in and vouches for who they are | Part 2.3 |
| Irreversible action | An action that cannot be undone once taken, such as issuing a permit | Part 1.1 |
| `jti` | A unique id for one token, used to spot reuse | Part 3 |
| JWS (JSON Web Signature) | A standard format for signed data: header, payload and signature | Part 2.4 |
| Key pair | A private key that signs and a public key that checks | Part 2.1 |
| `kid` | The header field naming which key checks the signature | Part 3 |
| Mutation testing | Breaking the code on purpose to confirm a test fails | Part 7.1 |
| Primary key | A database column that may not hold the same value twice | Part 6.2 |
| Private key | The secret half of a key pair, used to sign | Part 2.1 |
| Public key | The shareable half of a key pair, used to check signatures | Part 2.1 |
| Single use | A token that is recorded as spent the first time it is accepted | Part 6 |
| SQLite | A database that lives in a single file and needs no server | Part 6.2 |
| `sub` (subject) | The claim naming who the token is about; here, who confirmed | Part 3 |
| Token | A short piece of signed data saying who someone is and what they approved | Part 2.4 |
| `typ` | The header field saying what kind of token this is | Part 3, Part 5.1 |

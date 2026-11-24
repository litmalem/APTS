# Stage 6.4 — GSS execution attestation

Execution authorization now verifies the sealed Stage 6.2 evaluation and the
Stage 6.1 request, then derives eight checks from authoritative repository state:
SCOPE, ROE, POLICY, RISK, EXPIRY, REVOCATION, TARGET, TECHNIQUE.

Scope/policy identity, emergency state, target/action restrictions, historical
decision hash/revocation, source RoE, and explicit technique allowlist must agree.
Caller local checks, risk flags, and approval claims cannot grant permission.
Attestation is inserted before hashing the decision and included in audit/outbox.
Invalid binding is rejected before authorization writes. Generic CTI and Stage 2
requests retain the historical implementation; no SQL schema change is needed.

The baseline replacements are app/governance_service.py and app/main.py.
A companion module, 32 tests, protocol health metadata, and Windows acceptance
harness are added. All 58 GSS tests pass; production MySQL and Windows deployment
remain subject to the acceptance gate on the destination host.

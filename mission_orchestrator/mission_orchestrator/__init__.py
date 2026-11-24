"""APTS Global Mission Orchestrator - through Stage 3.9.2.

Stage 3.9.1 froze the canonical cross-stage E2E Mission scenario and acceptance
contract after Stage 3.1-3.8 closure. Stage 3.9.2 executes and verifies the first
frozen segment: canonical Mission intake through CREATED -> PIP_BOUND ->
PLANNING using only the already-owned intake and lifecycle command surfaces.

The Stage 3.9.2 runtime addition is a read-only qualification contract/verifier.
It introduces no new Governance, routing, delegation, dispatch, execution,
planner, target-actuation, external-I/O, telemetry, persistence, or database
migration authority. The qualified PLANNING head is the handoff to Stage 3.9.3.
"""

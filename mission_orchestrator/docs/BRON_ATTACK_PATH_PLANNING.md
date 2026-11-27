# BRON-style Stage 5.5 planning

Stage 5.5 now projects the sealed Stage 5.4 VulnDesk `attack_chain` into a
content-addressed knowledge snapshot and traverses its actual catalog relations.
Catalog traversal is an association query, not a causal exploitation sequence.
Each route compiles to the existing hypothesis validation action. Techniques and
CAPEC entries never supply actions, shell commands, payloads, or tool parameters.

## Implementation

- `bron_graph_contract.py`: v1 snapshot schema, typed nodes, relationship/status
  vocabulary, deterministic IDs, boundary-contract seals, limits, replay verifier.
- `bron_graph_repository.py`: immutable snapshot adapter over the existing sealed
  Stage 5.5 JSON output. Reads return copies; malformed snapshots are rejected.
- `bron_graph_service.py`: offline Stage 5.4 chain projection, exact Stage 5.3
  observed-asset binding, direction-preserving catalog edges, bounded bidirectional
  traversal, completeness and pruning reports.
- `symbolic_planner.py`: v4 planner adds registry-hash-bound `validation`
  capability references and source path references to existing actions. It
  preserves preconditions, effects, cost, impact, confidence, evidence, feedback,
  unknown beliefs and action masks. Legacy primitive/synthesis callers retain
  their previous STRIPS models with explicit unavailable-graph provenance.
- `attack_path_planning.py`: v2 agent contract, candidates, aggregate graph and
  output. Routes replace the four generic nodes when catalog relations exist;
  otherwise the generic candidate is explicitly marked as legacy fallback.
  Output verification replays snapshots, traversal, action compilation, symbolic
  search, aggregate graph and ranking bindings.
- `attack_path_workspace.py`: the existing revision view compiles the same sealed
  enumeration asset snapshot. The planner schema participates in its cache key.
- `exploitation.py`: Stage 5.6 reads the validation requirement from verified v2
  action models, while continuing to read legacy initial-access node provenance.
- `tests/test_bron_graph_planning.py`: offline acceptance coverage including real
  repository round trips and Stage 5.6 handoff, tampering, legacy reads, masks,
  pruning, missing mappings and deterministic replay.
- Stage 6.1/6.2 acceptance fixtures clone SQLite seeds using the backup API,
  including committed WAL pages. Copying only the database file lost recent
  handoff state once larger graph records changed automatic checkpoint timing.

## Data and provenance

`capec.sql` is a MariaDB dump containing `capec_attack_mappings`,
`capec_cwe_mappings` and source/version metadata. It is not a Stage 5.5 ingest
script. VulnDesk's `mapping_source_services.py` imports source datasets; its
`AttackMappingService._map_by_capec` joins active CWE/CAPEC and CAPEC/ATT&CK
mapping rows. Stage 5.4 already consumes those through its existing loopback
adapter and seals the result. Stage 5.5 performs no fetch and does not import the
dump or query a live VulnDesk database. The current runtime import state was not
inspected or modified.

The adapter translates legacy `ATTACK` nodes to `TECHNIQUE`. It retains the
direction of every supplied link and marks each catalog edge non-causal. A
technique/tactic association is added only when the source link actually names
a tactic. Taxonomy IDs and permitted source type pairs are checked.

Each source node/edge carries its catalog, record reference, content-pinned
snapshot, available versions and freshness status. Legacy chains often have
unknown upstream versions; these produce `PARTIAL` enrichment. Freshness remains
`UNKNOWN` where source timestamps are unavailable; a content hash does not imply
that intelligence is recent.

The observed asset must match the hypothesis's asset ID, target, mission/task IDs
and exact `enumerated_asset_sha256`. Supporting references must belong to that
asset. Service, endpoint/method and product-version facts come only from this
sealed asset. An observed endpoint on the same asset does not prove that any
catalog weakness applies to it: candidate endpoint applicability stays unknown.
No `RUNS_CPE`, service-to-endpoint, parameter, role, or auth-context relationship
is inferred from co-occurrence or text similarity. Missing facts stay absent.

The schema recognizes AUTHORITATIVE, RELATED, PARTIAL, HEURISTIC, OBSERVED,
UNKNOWN and CONFLICTING statuses. Catalog mapping levels retain source strength;
target applicability and validation belief remain UNKNOWN. Conflicting feedback
continues to mask symbolic actions. Neither a mapping level nor a capability
registry reference grants execution permission.

## Output shape

Illustrative fields, with content-derived IDs abbreviated:

```json
{
  "schema_version": "apts-stage5.5-attack-path-planning-output-v2",
  "knowledge_graph_schema_version": "apts-bron-knowledge-graph-v1",
  "knowledge_graph_snapshot_id": "brongs-run-…",
  "graph_enrichment_status": "PARTIAL",
  "knowledge_graph_snapshots": [{
    "snapshot": {"knowledge_graph_snapshot_id": "brongs-…"},
    "routes": [{"source_path_id": "bron-path-…", "node_ids": [], "edge_ids": []}],
    "pruning": {"expansions": 6, "pruned": 0}
  }],
  "candidate_pruning": {"generated": 1, "selected": 1, "pruned": 0},
  "candidate_paths": [{
    "source_path_id": "bron-path-…",
    "stage_sequence": [],
    "applicability": {"status": "UNKNOWN", "endpoint_binding": "UNKNOWN"},
    "action_model": {
      "capability_ref": {"capability_id": "validation", "canonical_sha256": "…"},
      "source_path_refs": ["bron-path-…"],
      "belief": "UNKNOWN"
    }
  }]
}
```

Actual records include full nodes, directed edges, source snapshots, evidence,
existing ranking details, validation models, predecessor hashes and integrity
seals. Scores retain their existing meaning as validation priority, never exploit
success probability. A trained ranker may reorder candidates only.

## Limits and compatibility

Per hypothesis: at most 128 source links, 320 projected nodes/edges, 32 observed
services/endpoints/versions per category, 6 catalog hops, fan-out 8, 256 search
expansions and 8 routes. All selection uses stable sorting. Source, observation,
traversal and final candidate pruning are reported separately. Stage 5.5's
existing 500-hypothesis symbolic bound and maximum 100 selected paths remain.

Missing enrichment is fail-open with `UNAVAILABLE` and an explicit fallback
reason. Incomplete valid relations yield `PARTIAL`. Malformed supplied chains,
snapshots, assets, routes or actions fail closed. COMPLETE means the supplied
taxonomy chain and versions are complete within these bounds, not that the
global catalog or target applicability is complete.

Agent contract, path, graph and output schemas/hash domains are explicitly v2;
the symbolic plan is v4. Request, ranking, provenance and evidence-bundle shapes
remain unchanged. Verifiers retain v1 path/graph/output reads. No SQL storage
layout changes or migration-level increment are needed: the existing JSON
columns persist the new sealed records atomically. Existing stored runs keep
their IDs and remain readable; new orchestration/workspace snapshots use the
new versions. Downstream canonical contract hashes naturally change with the
versioned predecessor; no runtime records are rewritten.

All planning remains projection-only: no external network I/O, target actuation,
authorization minting, tool invocation or execution request. Existing governance
and Stage 6 gateway authority are unchanged.

## Coverage limits

Only mappings preserved in the supplied Stage 5.4 chain are traversed; this is
not a query over the entire BRON catalog. That chain already applies its own
fan-out pruning and may omit original row IDs, per-edge timestamps, independent
mapping confidences or source versions. The planner preserves available source
references and records missing freshness instead of inventing metadata. Future
coverage expansion should enrich the upstream sealed chain contract first.
There is no calibrated exploit-success model and no new graph visualization UI;
graph context is exposed through the existing API/revision records.

## Verification

Run the offline graph acceptance with:

```powershell
python -B -m pytest -q -p no:cacheprovider tests/test_bron_graph_planning.py
```

`STAGE5_5_ACCEPTANCE.ps1` declares the v2 schemas and includes the graph acceptance
tests. Its live-service preflights were not invoked because implementation must
not modify runtime stores. The historical hard-coded inventory in that gate
predates the current checkout. A full `python -B -m pytest -q` attempt stopped
during collection with 41 CTI/governance import errors (`cti_services` modules
and `app.*` packages); this is not a full-suite pass.

Additional checks completed during implementation:

- Focused Stage 5.5, symbolic, ranking, CTI and Stage 5.6 regressions: 113 passed.
- Repeated focused regression after verifier strengthening: 85 passed.
- Final standalone graph acceptance after root-binding changes: 21 passed.
- Existing Stage 7.2 primitive, Stage 7.3x BAC synthesis and Stage 7.5x mission
  tests: 17 passed.
- Broad Stage 3.9.10 / Stage 4 / Stage 5 / Stage 6.1–6.3 attempt: 821 passed,
  9 failed, 13 setup errors before the WAL fixture correction. An isolated
  original-code comparison reproduced the Stage 3 authorization setup error and
  recon missing-table failure. Windows denies the existing hard-link tests.
- Stage 6.1 canonical requests, Stage 6.2 authorization and Stage 6.3 gateway
  rerun after the WAL fixture correction: 293 passed, 2 failed. Both remaining
  failures are `os.link` calls rejected by the Windows sandbox (`WinError 5`);
  no production authority checks were relaxed to accommodate them.
- All eight changed Python modules parsed successfully; `git diff --check`
  found no whitespace errors.

"""P1 adapter: genuine VulnDesk CTI PIP -> Pentest Stage 4.2 PIP.

This adapts an authenticated-by-endpoint CTI *data artifact*, not its authority.
Never creates an execution decision, infers an executable path, or invokes a
Pentest agent. Authority must already exist in authoritative GSS records.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone

from .errors import MissionTaskDelegationGuardRejected as Guard
from .task_routing import CtiSubsystemClient
from pentest_subsystem.pip_contract import PIP_SCHEMA_VERSION, seal_pip_artifact, normalize_pip_artifact

MAX_CTI_PIP_AGE_SECONDS = 3600  # local consumer freshness bound; CTI has no expiry field
GOOD_READINESS = frozenset({'VALIDATION_READY', 'ACTIONABLE'})
RECON_BOOTSTRAP_READINESS = 'PARTIAL'
RECON_BOOTSTRAP_GATE_IDS = frozenset({'QG-H1', 'QG-H2', 'QG-H3', 'QG-H4', 'QG-H5',
                                      'QG-H6', 'QG-H7', 'QG-H8', 'QG-H9', 'QG-H10'})


def _utc(value):
    if not isinstance(value, str):
        raise Guard('CTI PIP created_at must be an authoritative timestamp')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise Guard('CTI PIP created_at is malformed') from exc
    if dt.tzinfo is None:
        raise Guard('CTI PIP created_at must include timezone')
    return dt.astimezone(timezone.utc)


def _z(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _hash_source_artifact(artifact):
    """Same canonical material as VulnDesk PipAssemblyValidationService._hash_material."""
    material = copy.deepcopy(artifact)
    material.pop('integrity', None)
    if isinstance(material.get('quality'), dict):
        for key in ('validation_results', 'readiness', 'hard_gate_passed'):
            material['quality'].pop(key, None)
    raw = json.dumps(material, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _scope_target_declared(mission_binding, target):
    """Only explicit, exact CTI mission target declarations are accepted."""
    value = target['target_value']
    candidates = []
    for field in ('target_url', 'target_urls'):
        v = mission_binding.get(field)
        if isinstance(v, str):
            candidates.append(v)
        if isinstance(v, list):
            candidates.extend(x for x in v if isinstance(x, str))
    for field in ('scope', 'asset_scope'):
        scope = mission_binding.get(field)
        if isinstance(scope, dict):
            for key in ('target_url', 'target_urls', 'targets'):
                v = scope.get(key)
                if isinstance(v, str):
                    candidates.append(v)
                if isinstance(v, list):
                    for x in v:
                        if isinstance(x, str):
                            candidates.append(x)
                        elif isinstance(x, dict):
                            candidates.extend(x[k] for k in ('target_value', 'target_url') if isinstance(x.get(k), str))
        elif isinstance(scope, list):
            for x in scope:
                if isinstance(x, str):
                    candidates.append(x)
                elif isinstance(x, dict):
                    candidates.extend(x[k] for k in ('target_value', 'target_url') if isinstance(x.get(k), str))
    return value in candidates


def _source_confidence(intelligence):
    """Conservative minimum of explicitly provided CTI confidence evidence."""
    values = []
    for items in intelligence.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in ('confidence', 'path_confidence'):
                v = item.get(field)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1:
                    values.append(float(v))
    if not values:
        raise Guard('CTI PIP has no explicit numeric confidence; cannot derive Pentest PIP confidence')
    return min(values)


def _is_declaration_only_bootstrap(artifact, target):
    """Return true only for the empty-evidence Mission initialization package.

    This exception is deliberately narrower than general PARTIAL readiness:
    it cannot carry observations, confidence, or CTI claims whose age would
    need a freshness decision.
    """
    if not isinstance(artifact, dict):
        return False
    intelligence = artifact.get('intelligence')
    assumptions = artifact.get('assumptions_and_gaps')
    if not isinstance(intelligence, dict) or not intelligence or not isinstance(assumptions, list) or not assumptions:
        return False
    if any(not isinstance(item, dict) for item in assumptions):
        return False
    declared = False
    for item in assumptions:
        if item.get('source') != 'MISSION_SCOPE_BOOTSTRAP_V1':
            continue
        characteristics = item.get('mission_characteristics')
        digest = item.get('mission_characteristics_sha256')
        if (not isinstance(characteristics, dict) or not isinstance(digest, str)
                or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            continue
        raw = json.dumps(characteristics, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        if (hashlib.sha256(raw.encode('utf-8')).hexdigest() == digest
                and _scope_target_declared({'scope': characteristics.get('scope')}, target)):
            declared = True
            break
    if not declared:
        return False
    # VulnDesk stores assumptions_and_gaps beside (not inside) intelligence.
    # Recognize only its known evidence collections and require each to be empty.
    known_collections = {
        'normalized_objects', 'provenance_records', 'asset_profiles',
        'cpe_resolution_claims', 'vulnerability_correlations', 'attack_mappings',
        'attack_paths', 'threat_contexts', 'risk_priorities',
    }
    return (set(intelligence).issubset(known_collections)
            and all(isinstance(values, list) and not values for values in intelligence.values()))


def _validate_recon_bootstrap(source, artifact, *, mission_id, target, issued, now,
                              declaration_only=False):
    """Narrow P1.1 eligibility for non-executing reconnaissance task materialization.

    This is NOT a new CTI readiness or GSS authorization, and never authorizes
    scanning, exploitation, dispatch or a target action. Requires the CTI
    quality gates plus an exact observed profile or a declaration-only Mission
    bootstrap containing no CTI claims.
    """
    checks = source['validation_results']
    gate_ids = [item.get('gate_id') for item in checks]
    if (len(gate_ids) != len(RECON_BOOTSTRAP_GATE_IDS) or
            set(gate_ids) != RECON_BOOTSTRAP_GATE_IDS or
            any(item.get('passed') is not True for item in checks)):
        raise Guard('RECON_BOOTSTRAP requires all ten distinct CTI hard quality gates')
    if source.get('published_readiness') != 'PARTIAL':
        raise Guard('RECON_BOOTSTRAP requires consistent published CTI PARTIAL readiness')
    if target.get('environment') != 'LAB' or target.get('target_type') != 'URL':
        raise Guard('RECON_BOOTSTRAP is restricted to URL targets explicitly designated LAB')
    intel = artifact['intelligence']
    # A bootstrap package supplies an asset context, not vulnerability claims or
    # attack paths inferred without reconnaissance evidence.
    if any(intel.get(name) for name in ('vulnerability_correlations', 'risk_priorities', 'attack_paths')):
        raise Guard('RECON_BOOTSTRAP may not carry actionable vulnerability claims or attack paths')
    profiles = intel.get('asset_profiles', [])
    if not isinstance(profiles, list):
        raise Guard('CTI asset profiles must be a list')
    if not profiles and not declaration_only:
        raise Guard('RECON_BOOTSTRAP requires an observed CTI asset profile or declaration-only Mission bootstrap')
    matching = []
    for profile in profiles:
        if not isinstance(profile, dict):
            raise Guard('CTI asset profile is malformed')
        observed = profile.get('observed_attributes')
        # Exact URL binding: never infer scope from a hostname, fuzzy URL or
        # an unrelated profile. A verification label alone is insufficient.
        if (isinstance(observed, dict) and observed.get('target_url') == target['target_value']
                and profile.get('mission_id') == mission_id):
            if (not isinstance(profile.get('asset_id'), str) or not profile['asset_id'].strip()
                    or profile.get('verification_status') not in ('OBSERVED', 'VERIFIED')
                    or not isinstance(profile.get('evidence_refs'), list)
                    or not profile['evidence_refs']
                    or not all(isinstance(ref, str) and ref.strip() for ref in profile['evidence_refs'])):
                raise Guard('Matching CTI asset profile lacks observed provenance or verification')
            confidence = profile.get('confidence')
            if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                    or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                raise Guard('Matching CTI asset profile requires explicit numeric confidence')
            observed_at = _utc(profile.get('observed_at'))
            if not (issued - timedelta(seconds=MAX_CTI_PIP_AGE_SECONDS)
                    <= observed_at <= now):
                raise Guard('Matching CTI asset observation is stale or in the future')
            matching.append(profile)
    if not matching and not declaration_only:
        raise Guard('RECON_BOOTSTRAP lacks an observed CTI asset profile matching exact Pentest URL')
    return {
        'mode': 'RECON_BOOTSTRAP',
        'source_readiness': 'PARTIAL',
        'evidence_basis': 'MISSION_DECLARATION_ONLY' if declaration_only else 'OBSERVED_CTI_ASSET_PROFILE',
        'quality_gate_ids': sorted(RECON_BOOTSTRAP_GATE_IDS),
        'matched_asset_profile_ids': [str(p['asset_profile_id']) for p in matching if p.get('asset_profile_id')],
        'action_classes': ['TARGET_RECON'],
        'execution_authorized': False,
        'target_actuation': False,
    }


def _verify_cti_pip(source, *, pip_id, mission_id, target, now):
    if not isinstance(source, dict) or source.get('pip_id') != pip_id or source.get('mission_id') != mission_id:
        raise Guard('CTI PIP identity does not match requested Mission')
    readiness = source.get('readiness')
    if readiness not in GOOD_READINESS | {RECON_BOOTSTRAP_READINESS} or source.get('immutable') is not True:
        raise Guard('CTI PIP must be immutable and supported for intelligence or recon bootstrap')
    artifact = source.get('artifact')
    if not isinstance(artifact, dict):
        raise Guard('CTI PIP artifact is missing')
    binding = artifact.get('mission_binding')
    if not isinstance(binding, dict) or binding.get('mission_id') != mission_id or not _scope_target_declared(binding, target):
        raise Guard('CTI PIP mission binding does not explicitly contain exact Pentest target')
    if (artifact.get('pip_id') != pip_id or artifact.get('revision') != source.get('revision')
            or artifact.get('semantics', {}).get('execution_authorized') is not False
            or artifact.get('semantics', {}).get('execution_command') is not False):
        raise Guard('CTI PIP artifact identity or non-execution semantics invalid')
    quality = artifact.get('quality')
    checks = source.get('validation_results')
    if (not isinstance(quality, dict) or quality.get('hard_gate_passed') is not True
            or quality.get('readiness') != readiness
            or not isinstance(checks, list) or not checks
            or not all(isinstance(r, dict) and r.get('passed') is True for r in checks)
            or quality.get('validation_results') != checks):
        raise Guard('CTI PIP current quality gates are missing or failed')
    sha = artifact.get('integrity', {}).get('sha256')
    if (not isinstance(sha, str) or len(sha) != 64 or sha != source.get('canonical_sha256')
            or sha != _hash_source_artifact(artifact)):
        raise Guard('CTI PIP artifact SHA-256 integrity mismatch')
    issued = _utc(artifact.get('created_at'))
    intel = artifact.get('intelligence')
    if not isinstance(intel, dict) or not intel:
        raise Guard('CTI PIP intelligence is empty')
    declaration_only = (readiness == RECON_BOOTSTRAP_READINESS
                        and _is_declaration_only_bootstrap(artifact, target))
    expiry = issued + timedelta(seconds=MAX_CTI_PIP_AGE_SECONDS)
    if issued > now or (now >= expiry and not declaration_only):
        raise Guard('CTI PIP is stale or timestamp is in the future (local 1h freshness policy)')
    bootstrap = None
    if readiness == RECON_BOOTSTRAP_READINESS:
        bootstrap = _validate_recon_bootstrap(
            source, artifact, mission_id=mission_id, target=target, issued=issued, now=now,
            declaration_only=declaration_only)
    # Declaration-only bootstrap has no time-sensitive CTI observations. The
    # derived Pentest PIP is issued now and gets its own bounded consumer TTL;
    # its provenance still points to the exact immutable source artifact.
    consumer_issued = now if declaration_only else issued
    consumer_expiry = consumer_issued + timedelta(seconds=MAX_CTI_PIP_AGE_SECONDS)
    confidence = 0.0 if declaration_only else _source_confidence(intel)
    return artifact, consumer_issued, consumer_expiry, confidence, bootstrap


def derive_stage43_inputs(service, received, reference, *, cti_client=None, now=None):
    """Fetch existing CTI PIP and existing GSS decision; fail closed on gaps.

    Reference schema: {pip_id, policy_decision_id}. No caller-provided
    PIP, target, confidence, hash, or execution_authorized claims accepted.
    """
    if (not isinstance(reference, dict) or set(reference) != {'pip_id', 'policy_decision_id'}
            or not all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}', v)
                       for v in reference.values())):
        raise Guard('stage43_cti requires only pip_id and policy_decision_id')
    env = received['envelope']
    identity, work = env['identity'], env['work_context']
    mission_id = identity['mission_id']
    targets = work['scope'].get('targets')
    if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], dict):
        raise Guard('Stage 4.3 CTI adapter requires exactly one canonical Mission target')
    target = targets[0]
    client = cti_client if cti_client is not None else CtiSubsystemClient()
    source = client.get_pip(reference['pip_id'])
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    artifact, issued, expiry, confidence, bootstrap = _verify_cti_pip(
        source, pip_id=reference['pip_id'], mission_id=mission_id, target=target, now=now)
    # The accepted recipient must be a recon task. Bootstrap never applies to
    # enumeration, exploitation, post-exploitation, or other capabilities.
    if bootstrap is not None:
        recipient = env.get('recipient', {})
        if (recipient.get('subsystem_id') != 'PENTEST'
                or recipient.get('capability_id') != 'pentest.recon'):
            raise Guard('RECON_BOOTSTRAP requires the original PENTEST pentest.recon handoff')
    snapshot = service.governance_client.mission_correlation_snapshot(mission_id)
    if snapshot.get('mission_id') != mission_id or snapshot.get('authority') != 'aptsGSS':
        raise Guard('Authoritative GSS correlation snapshot unavailable')
    decisions = [d for d in snapshot.get('policy_decisions', []) if d.get('decision_id') == reference['policy_decision_id']]
    if len(decisions) != 1 or decisions[0].get('decision') != 'ALLOW':
        raise Guard('Explicit TARGET_RECON policy decision must exist and be ALLOW')
    decision = decisions[0]
    requests = [r for r in snapshot.get('authorization_requests', []) if r.get('request_id') == decision.get('request_id')]
    if len(requests) != 1 or requests[0].get('action_class') != 'TARGET_RECON':
        raise Guard('Policy decision must refer to actual TARGET_RECON request')
    binding = service.repository.get_current_governance_binding(mission_id)['binding']['governance_authority']
    if (decision.get('scope_contract_id') != binding['governance_scope_contract_id']
            or decision.get('scope_version') != binding['governance_scope_version']):
        raise Guard('Execution decision scope differs from current Mission governance binding')
    req = requests[0]
    if (req.get('subject_component') != 'PENTEST-SUB01' or req.get('mission_id') != mission_id
            or req.get('resource_type') != target.get('target_type') or req.get('resource_value') != target.get('target_value')):
        raise Guard('Execution decision subject or target mismatch')
    pentest_id = 'pentest-handoff-' + hashlib.sha256(received['handoff_id'].encode()).hexdigest()[:32]
    # Namespaced identity is preserved, while content is an exact copy of CTI
    # intelligence. The consumer TTL is explicit and independent of CTI validity.
    intelligence = {'cti_intelligence': copy.deepcopy(artifact['intelligence']),
                    'validation_objectives': copy.deepcopy(artifact.get('validation_objectives') or []),
                    'assumptions_and_gaps': copy.deepcopy(artifact.get('assumptions_and_gaps') or []),
                    'source_integrity_sha256': source['canonical_sha256']}
    if bootstrap is not None:
        intelligence['consumer_eligibility'] = bootstrap
    pip = seal_pip_artifact({
        'schema_version': PIP_SCHEMA_VERSION, 'pip_id': source['pip_id'],
        'pip_version': str(source['revision']), 'mission_id': mission_id,
        'pentest_id': pentest_id, 'task_id': identity['planned_task_id'],
        'source_cti': {'source_type': 'CTI', 'source_system': 'VULNDESK_CTI',
                       'artifact_id': source['pip_id'], 'artifact_version': str(source['revision']),
                       'artifact_sha256': source['canonical_sha256']},
        'issued_at': _z(issued), 'expires_at': _z(expiry), 'scope': copy.deepcopy(work['scope']),
        'confidence': confidence,
        'provenance': {'producer': 'VULNDESK_CTI', 'source_refs': [source['pip_id']],
                       'collection_method': 'CTI_PIP_VERIFIED_BRIDGE'},
        'intelligence': intelligence,
    })
    normalize_pip_artifact(pip, now=now)
    return {'pip': pip, 'target': copy.deepcopy(target),
            'authorization_reference': {'policy_decision_id': decision['decision_id'],
                                        'policy_decision_hash': decision['decision_hash'],
                                        'policy_version': decision['policy_version'],
                                        'execution_authorized': True}}

"""Deterministic bootstrap, using declared Mission context and committed scope only."""
from .pip_initialization import history, bind, build_pip
from .canonical import sha256_hex
from .errors import MissionValidationError


def initialization_inputs(envelope, scope):
    mission = envelope['mission']
    characteristics = {key: mission.get(key) for key in
                       ('mission_kind', 'objective', 'success_criteria', 'budgets', 'required_subsystems')}
    characteristics['scope'] = scope['contract']['scope']
    characteristics['roe'] = scope['contract']['roe']
    characteristics['constraints'] = scope['contract']['constraints']
    return {'assumptions_and_gaps': [
        {'description': 'Declared Mission context; not an observed technology or vulnerability.',
         'source': 'MISSION_SCOPE_BOOTSTRAP_V1', 'mission_characteristics': characteristics,
         'mission_characteristics_sha256': sha256_hex(characteristics)},
        {'description': 'Target observations, CPE and vulnerability evidence are not yet available; '
                        'reconnaissance and CTI enrichment remain required within approved scope.'}
    ]}


def initialize(service, mission_id):
    state = service.repository.get_state(mission_id)
    if state is None:
        service.get_mission(mission_id)  # authoritative not-found error
    if state['state'] != 'CREATED':
        return {'status': 'unchanged', 'state': state['state'], 'execution_authorized': False}
    envelope = history(service.repository, mission_id)[-1]
    from .gss_scope_sync import synchronize
    scope = synchronize(service, mission_id)
    binding = envelope['bindings']['pip']
    key = 'auto-pip-' + sha256_hex({'mission_id': mission_id, 'scope': scope['canonical_sha256']})[:48]
    if not binding.get('pip_id'):
        result = build_pip(service, mission_id, initialization_inputs(envelope, scope))
        pip = result.get('pip') or {}
        if not pip.get('pip_id') or not pip.get('revision'):
            raise MissionValidationError('CTI bootstrap did not publish a PIP')
        bind(service, mission_id, {
            'pip_id': pip['pip_id'], 'pip_version': str(pip['revision']),
            'expected_envelope_version': envelope['identity']['envelope_version'],
            'idempotency_key': key, 'actor': 'mission-auto-pip',
            'reason': 'Deterministic Mission characteristics bootstrap v1'})
    # Recheck GSS before activation; a revoked/revised source must not activate a stale PIP.
    from .gss_scope_sync import KEY, fetch
    synced = scope['contract'].get('metadata', {}).get(KEY)
    if synced:
        if sha256_hex(fetch(service, mission_id)) != synced['source_snapshot_sha256']:
            raise MissionValidationError('GSS source changed after PIP build; activation blocked')
        from .pip_initialization import validate_pip
        current_binding = history(service.repository, mission_id)[-1]['bindings']['pip']
        validate_pip(service.cti_client.get_pip(current_binding['pip_id']), mission_id,
                     current_binding, scope)
    # Resume here after a crash between durable binding and lifecycle activation.
    state = service.repository.get_state(mission_id)
    vector = service.get_mission_version_vector(mission_id)
    result = service.execute_mission_lifecycle_command(mission_id, {
        'command_id': key, 'idempotency_key': key, 'command': 'BIND_PIP',
        'expected_version_sha256': vector['version_sha256'],
        'expected_state_version': state['state_version'], 'actor': 'mission-auto-pip',
        'reason_code': 'ACTIVATE_PIP', 'reason': 'Verified CTI bootstrap from Mission characteristics',
        'evidence_refs': ['mission-scope:' + scope['snapshot_id']],
        'metadata': {'bootstrap_policy': 'MISSION_SCOPE_BOOTSTRAP_V1'}})
    return {'status': 'completed', 'state': service.repository.get_state(mission_id)['state'],
            'execution_authorized': False, 'lifecycle': result}


def sweep(service):
    """Recover existing missions and transient failures without operator clicks."""
    from .errors import MissionContractError
    import logging
    ids, offset = [], 0
    while True:
        page = service.list_missions(state='CREATED', limit=100, offset=offset)
        ids.extend(row['mission_id'] for row in page['missions'])
        offset += len(page['missions'])
        if offset >= page['mission_count'] or not page['missions']:
            break
    for mid in ids:
        try:
            service.initialize_mission_pip_automatically(mid)
        except MissionContractError as exc:
            logging.getLogger(__name__).warning('Automatic PIP deferred for %s: %s', mid, exc)
        except Exception:
            logging.getLogger(__name__).exception('Automatic PIP failed for %s', mid)
    # PIP binding is a prerequisite, not the end of autonomous initialization.
    # Planning has its own durable artifacts and guarded lifecycle transition;
    # its worker is replay-safe and does not authorize or execute Pentest work.
    from .mission_planning_automation import sweep as planning_sweep
    planning_sweep(service)
    # APTS_AUTONOMOUS_ROUTING_HANDOFF_V1
    from .mission_routing_handoff_automation import sweep as routing_handoff_sweep
    routing_handoff_sweep(service)
    # Independent opt-in state activation and WPT preparation. Both use the
    # authoritative repositories; neither can mint Stage 6 execution authority.
    from .mission_running_automation import sweep as running_sweep
    running_sweep(service)
    # APTS_AUTONOMOUS_TASK_DRIVE_V1 (opt-in). RUNNING -> tasks -> CLEANING_UP -> COMPLETED.
    from .mission_task_drive_automation import sweep as task_drive_sweep
    task_drive_sweep(service)
    from .mission_wpt_preparation import sweep as wpt_preparation_sweep
    wpt_preparation_sweep(service)
    from .mission_wpt_recon_delivery import sweep as wpt_recon_delivery_sweep
    wpt_recon_delivery_sweep(service)
    # APTS_AUTONOMOUS_CTI_ENUMERATION_DELIVERY_V1. Opt-in, fail-closed, idempotent.
    # Builds and submits the governed Stage-5.3 enumeration run once a Recon run is
    # COMPLETED with SEALED CTI. Mints no authority and performs no target I/O.
    from .mission_cti_enumeration_delivery import sweep as cti_enumeration_delivery_sweep
    cti_enumeration_delivery_sweep(service)
    from .mission_enumeration_wpt_delivery import sweep as enumeration_wpt_delivery_sweep
    enumeration_wpt_delivery_sweep(service)
    # APTS_AUTONOMOUS_CTI_HYPOTHESIS_CORRELATION. Enumeration -> Vulnerability
    # Hypothesis (Stage 5.4). Modeling only; no target I/O, no Stage 6, no finding.
    from .mission_cti_hypothesis_correlation import sweep as cti_hypothesis_correlation_sweep
    cti_hypothesis_correlation_sweep(service)


def start_worker(service):
    import threading
    import logging
    stopped = threading.Event()
    def run():
        while not stopped.is_set():
            try:
                sweep(service)
            except Exception:
                logging.getLogger(__name__).exception('Automatic PIP recovery sweep failed')
            stopped.wait(30)
    threading.Thread(target=run, name='mission-auto-pip', daemon=True).start()
    return stopped

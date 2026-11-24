"""Isolated regression comparison; never changes installed source or live data."""
import inspect
import sys
import textwrap
from pathlib import Path
ROOT = Path('D:/APTS/mission_orchestrator')
sys.path.insert(0, str(ROOT))
from execution_subsystem.runtime_service import ExecutionRuntimeService
import execution_subsystem.runtime_service as runtime_module
import pytest

source = textwrap.dedent(inspect.getsource(ExecutionRuntimeService._supervise))
source = source.replace('probe_started = time.monotonic()', 'probe_started = current_time')
source = source.replace('last_probe = probe_started', 'last_probe = current_time')
namespace = dict(vars(runtime_module))
exec(compile(source, '<baseline-probe-timeout>', 'exec'), namespace)
ExecutionRuntimeService._supervise = namespace['_supervise']
raise SystemExit(pytest.main([
    str(ROOT / 'tests/test_stage6_8_runtime_completion_fence.py') + '::test_supervisor_held_before_probe_cannot_revalidate_after_terminal[vep_ctx]',
    '-q', '--tb=short', '-p', 'no:cacheprovider',
    '--basetemp=D:/APTS/test-tmp-wpt-vep-baseline-20261109']))

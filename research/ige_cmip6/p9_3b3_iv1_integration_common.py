"""Frozen IV1 integration contract, paths and pre-unblinding gates."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_iv1_admission import admission_report, source_plan
from p9_3b3_iv1_preflight import ROOT, guard
from p9_3b3_cd1_run import write_new


CONTRACT = Path(__file__).with_name('p9_3b3_iv1_integration_contract.json')
CONTRACT_SHA = 'dc2e06d04c4a1e750ab4d8b1bdb3803d4896c0d67ef87dfc6b778968b3bc8915'
OBSERVATION_BUDGET = 640*1024**2


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integration_guard():
    if sha(CONTRACT) != CONTRACT_SHA:
        raise ValueError('IV1_INTEGRATION_CONTRACT_CHANGED')
    contract = json.loads(CONTRACT.read_text())
    for name, expected in contract['protected_sha256'].items():
        if sha(ROOT/name) != expected:
            raise ValueError('IV1_INTEGRATION_PROTECTED_FILE_CHANGED_'+name)
    subprocess.run(['git', 'merge-base', '--is-ancestor', contract['parent_commit'], 'HEAD'],
                   cwd=ROOT, check=True, capture_output=True)
    return guard(), contract


def execution_plan(protocol, contract):
    old = source_plan(protocol)
    controls = contract['raw_surface_control_hours']
    old['native_source_hours'] = sorted(set(old['native_source_hours'])
        - set(old['source_control_hours']) | set(controls))
    old['source_control_hours'] = controls
    old['control_amendment'] = contract['control_amendment']
    if len(old['native_source_hours']) != 676:
        raise ValueError('IV1_INTEGRATION_NATIVE_HOUR_CENSUS')
    return old


def require_time_admission():
    audit = admission_report()
    time = audit['time_admission']
    if not time['all_parameter_time_operators_admitted'] or any(
        row['status'] != 'ADMITTED' or row['operator'] != 'CURRENT_VALUE_AT_EXACT_UTC_NODE'
        for country in time['countries'].values() for row in country.values()):
        raise SourceBlocked('IV1_PARAMETER_TIME_OPERATORS_NOT_ALL_ADMITTED_NO_NETWORK_OR_UNBLINDING')
    return audit


def member_path(root, name):
    pure = PurePosixPath(name)
    if pure.is_absolute() or '..' in pure.parts or '\\' in name or str(pure) != name:
        raise ValueError('IV1_UNSAFE_SEAL_MEMBER_PATH')
    path = Path(root)/name
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != Path(root).parent):
        raise ValueError('IV1_SYMLINK_IN_SEALED_INPUTS')
    return path


def read_members(root, manifest):
    result = {}
    for name, digest in manifest.items():
        path = member_path(root, name)
        if len(digest) != 64 or sha(path) != digest:
            raise ValueError('IV1_SEALED_MEMBER_CHANGED_'+name)
        result[name] = path
    return result


def code_pins():
    folder = Path(__file__).parent
    return {p.name: sha(p) for p in sorted(folder.glob('p9_3b3_iv1_integration*.py'))} | {
        CONTRACT.name: sha(CONTRACT),
        'p9_3b3_iv1_integration_AT_response_schema_20261024.json':
            sha(folder/'p9_3b3_iv1_integration_AT_response_schema_20261024.json')}


def fresh_directory(path):
    path = Path(path)
    if path.exists():
        raise FileExistsError('IV1_OUTPUT_EXISTS_NO_OVERWRITE')
    path.mkdir(parents=True)
    return path

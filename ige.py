#!/usr/bin/env python3
"""Install, check and run the existing IGE research application (Python 3.12)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import venv

ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.venv' / 'ige'
PACKAGE = ROOT / 'packaging' / 'ige'
MARKER = ENV / 'ige-managed-environment.json'


def environment_python(directory=ENV):
    return directory / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def child_environment():
    env = os.environ.copy()
    for name in ('PYTHONPATH', 'PYTHONHOME'):
        env.pop(name, None)
    env.update(PYTHONNOUSERSITE='1', PYTHONUTF8='1', OPENBLAS_NUM_THREADS='1',
               OMP_NUM_THREADS='1', STREAMLIT_BROWSER_GATHER_USAGE_STATS='false',
               PIP_DISABLE_PIP_VERSION_CHECK='1')
    return env


def locked_versions():
    result = {}
    for name in ('bootstrap.lock', 'requirements.lock'):
        for line in (PACKAGE / name).read_text(encoding='utf-8').splitlines():
            match = re.match(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)', line)
            if match:
                key, value = match.groups()
                key = key.lower().replace('_', '-')
                if key in result and result[key] != value:
                    raise ValueError('Conflicting dependency lock: ' + key)
                result[key] = value
    return result


def verify_baseline():
    manifest = json.loads((PACKAGE / 'baseline.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files_sha256'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Required application/source file missing: ' + name)
        if sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen application/source file changed: ' + name)
    return manifest


def doctor():
    if sys.version_info[:2] != (3, 12):
        raise ValueError('Use Python 3.12. On Windows: py -3.12 ige.py setup')
    expected = locked_versions()
    installed = {d.metadata['Name'].lower().replace('_', '-'): d.version
                 for d in metadata.distributions()}
    wrong = {k: {'expected': v, 'installed': installed.get(k)}
             for k, v in expected.items() if installed.get(k) != v}
    unexpected = sorted(set(installed) - set(expected))
    if wrong or unexpected:
        raise ValueError('Environment differs from lock. Run setup in the dedicated environment. '
                         + json.dumps({'versions': wrong, 'unexpected_packages': unexpected}))
    subprocess.run([sys.executable, '-m', 'pip', 'check'], cwd=ROOT, env=child_environment(), check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    baseline = verify_baseline()
    return {'status': 'PASS', 'python': sys.version.split()[0], 'platform': sys.platform,
            'locked_packages': len(expected), 'verified_baseline_files': len(baseline['files_sha256']),
            'baseline_commit': baseline['commit'], 'scientific_methods_changed': False,
            'production_ready': False, 'new_weather_requests': 0}


def setup():
    if sys.version_info[:2] != (3, 12):
        raise ValueError('Setup requires Python 3.12. Use python3.12, or py -3.12 on Windows.')
    python = environment_python()
    if ENV.exists() and not MARKER.is_file():
        raise ValueError(str(ENV) + ' already exists without an IGE marker. Move it aside; setup never deletes an environment.')
    if not ENV.exists():
        print('Creating the dedicated environment: ' + str(ENV), flush=True)
        venv.EnvBuilder(with_pip=True).create(ENV)
        MARKER.write_text(json.dumps({'schema': 'IGE_I2_MANAGED_ENVIRONMENT_v1', 'Python': '3.12'}) + '\n', encoding='utf-8')
    if not python.is_file():
        raise ValueError('Incomplete environment at ' + str(ENV) + '; move it aside and run setup again.')
    subprocess.run([str(python), '-m', 'pip', 'install', '--require-hashes', '--no-deps',
                    '--only-binary=:all:', '-r', str(PACKAGE / 'bootstrap.lock')],
                   cwd=ROOT, env=child_environment(), check=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--require-hashes', '--no-deps',
                    '--no-build-isolation', '--only-binary=:all:', '--no-binary=psychrolib',
                    '-r', str(PACKAGE / 'requirements.lock')], cwd=ROOT, env=child_environment(), check=True)
    subprocess.run([str(python), str(ROOT / 'ige.py'), 'doctor'], cwd=ROOT, env=child_environment(), check=True)
    print('\nSetup complete. Start: python ige.py run\nCheck and export examples: python ige.py check', flush=True)


def streamlit_command(port=8501):
    return [sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'tools/climate_analyzer/app.py'),
            '--server.address=127.0.0.1', '--server.port=' + str(port), '--server.headless=true',
            '--browser.gatherUsageStats=false']


def default_output(command):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return ROOT / '.epw_climate_analyzer' / 'ige-runs' / (command + '-' + stamp + '-' + uuid.uuid4().hex[:6])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('setup', help='Create a dedicated environment and install the hashed dependency lock.')
    commands.add_parser('doctor', help='Check dependency versions, pip consistency and frozen inputs.')
    run = commands.add_parser('run', help='Start the existing application at http://127.0.0.1:8501.')
    run.add_argument('--port', type=int, default=8501)
    for command in ('examples', 'check'):
        p = commands.add_parser(command, help=('Export all four examples without weather network access.' if command == 'examples'
                                               else 'Run combined regressions, export four examples and check the actual server.'))
        p.add_argument('--out', type=Path, help='A new output directory; existing results are never overwritten.')
    args = parser.parse_args(argv)
    if args.command == 'setup':
        setup()
        return 0
    if Path(sys.prefix).resolve() != ENV.resolve():
        python = environment_python()
        if not python.is_file() or not MARKER.is_file():
            raise ValueError('Install first: python ige.py setup (Python 3.12).')
        command_args = list(argv) if argv is not None else sys.argv[1:]
        return subprocess.call([str(python), str(ROOT / 'ige.py'), *command_args], cwd=ROOT, env=child_environment())
    result = doctor()
    if args.command == 'doctor':
        print(json.dumps(result, indent=2))
        return 0
    if args.command == 'run':
        if not 1024 <= args.port <= 65535:
            raise ValueError('Choose a port between 1024 and 65535.')
        print('Open http://127.0.0.1:' + str(args.port) + ' and select Generate climate.', flush=True)
        return subprocess.call(streamlit_command(args.port), cwd=ROOT, env=child_environment())
    output = args.out.expanduser().resolve() if args.out else default_output(args.command)
    return subprocess.call([sys.executable, str(PACKAGE / 'verify.py'), args.command, '--out', str(output)],
                           cwd=ROOT, env=child_environment())


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('IGE: ' + str(error), file=sys.stderr)
        raise SystemExit(2)

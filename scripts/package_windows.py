"""Build a source-bound portable ZIP from already-tested native Windows binaries.

This developer packaging step requires Git and Python; the resulting demo does not.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def package(node, console, build_receipt, output):
    if output.exists():
        raise FileExistsError('use a new package path; existing deliveries are retained')
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    if any('\\' in name for name in names):
        raise ValueError('non-portable source path contains a backslash; normalize evidence paths first')
    files = {f'project/{name}': (ROOT / name).read_bytes() for name in names if name}
    receipt = json.loads(build_receipt.read_text(encoding='utf-8-sig'))
    production = {name.removeprefix('project/'): sha(data) for name, data in files.items()
                  if (name.endswith('.go') and not name.endswith('_test.go')) or name == 'project/go.mod'
                  or name.startswith('project/cmd/dashboard/static/')}
    if receipt.get('source_production_sha256') != production:
        raise ValueError('native build production source set/digests differ')
    for name, path in [('raft-node.exe', node), ('raft-console.exe', console)]:
        if receipt.get('binary_sha256', {}).get(name) != sha(path.read_bytes()):
            raise ValueError(f'untested executable differs from native build receipt: {name}')
    files['project/raft-node.exe'] = node.read_bytes()
    files['project/raft-console.exe'] = console.read_bytes()
    files['Start-Terminals.cmd'] = b'@echo off\r\nsetlocal\r\nset "runDir=%~1"\r\nif not defined runDir set "runDir=%~dp0runs\\classroom"\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0project\\scripts\\start.ps1" -UsePrebuilt -RunDir "%runDir%"\r\nset "result=%errorlevel%"\r\npause\r\nexit /b %result%\r\n'
    files['Start-Console.cmd'] = b'@echo off\r\ncd /d "%~dp0project" || exit /b 1\r\nraft-console.exe -node-bin ".\\raft-node.exe" -source-dir "." -data-root "..\\runs\\console" -allow-control\r\npause\r\n'
    files['Run-Experiments.cmd'] = b'@echo off\r\ncall "%~dp0project\\Run-Experiments.cmd"\r\n'
    files['README-START.txt'] = files['project/docs/quick-start-zh.md']
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    manifest = {'source_commit': commit, 'source_dirty': bool(status), 'target': 'Windows 11 x64',
                'native_build_production_sha256': production,
                'binaries': {name: sha(data) for name, data in files.items() if name.endswith('.exe')},
                'demo_dependencies': 'Windows PowerShell 5.1 and Edge/Chrome; no Go/Python/Node.js',
                'experiment_dependencies': 'Go >=1.26.3 and Python >=3.12 on PATH',
                'manual_terminal_close': 'NOT RUN; deferred by user',
                'native_race': 'NOT RUN; C compiler unavailable'}
    files['native-build-receipt.json'] = (json.dumps(receipt, ensure_ascii=False, indent=2)+'\n').encode()
    files['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode()
    files['SHA256SUMS.txt'] = ''.join(f'{sha(data)}  {name}\n' for name, data in sorted(files.items())).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            z.writestr(name, data)
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None:
            raise RuntimeError('package CRC verification failed')
    digest = sha(output.read_bytes())
    output.with_suffix('.sha256').write_text(f'{digest}  {output.name}\n', encoding='ascii')
    print(json.dumps({'file': str(output), 'sha256': digest, 'entries': len(files), 'bytes': output.stat().st_size}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--node', type=Path, required=True)
    p.add_argument('--console', type=Path, required=True)
    p.add_argument('--build-receipt', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    package(a.node, a.console, a.build_receipt, a.output)

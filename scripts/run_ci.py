"""Explicit test inventory: new tests must be classified, never silently omitted."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
BASE=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('group',choices=['unit','gui','frontend','inventory'])
    args=parser.parse_args()
    manifest=json.loads((BASE/'tests/ci_manifest.json').read_text())
    listed=[n for group in manifest.values() for n in group]
    actual={p.name for p in (BASE/'tests').glob('test_*.py')}
    if len(listed)!=len(set(listed)) or set(listed)!=actual:
        raise RuntimeError(f'Test inventory mismatch: unclassified={actual-set(listed)}, missing={set(listed)-actual}')
    print('Manual coverage (not claimed by CI):',json.dumps(manifest['manual']),flush=True)
    if args.group=='inventory':return
    output=BASE/'diagnostics/ci';output.mkdir(parents=True,exist_ok=True)
    report=[]
    try:
        for name in manifest[args.group]:
            if args.group!='gui':
                count=unittest.defaultTestLoader.discover(str(BASE/'tests'),pattern=name).countTestCases()
                if count==0:raise RuntimeError('Zero tests discovered: '+name)
            command=([sys.executable,str(BASE/'tests'/name)] if args.group=='gui' else
                     [sys.executable,'-m','unittest','discover','-s','tests','-p',name])
            began=time.monotonic()
            result=subprocess.run(command,cwd=BASE,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
            print(result.stdout+result.stderr,flush=True)
            report.append(dict(test=name,seconds=time.monotonic()-began,exit_code=result.returncode))
            if result.returncode:raise RuntimeError('Failed: '+name)
    finally:
        (output/(args.group+'-results.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
if __name__=='__main__':main()

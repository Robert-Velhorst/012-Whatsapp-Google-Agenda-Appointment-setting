"""Run the documented local commands with the owned SQLite library."""
from __future__ import annotations
import json,os,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COMMANDS={
 'test':['-m','pytest','-q','--basetemp=.pytest-run'],
 'run':['run.py'],
 'worker':['-m','scheduler.cli','worker'],
 'doctor':['-m','scheduler.cli','doctor'],
 'migrate':['-m','scheduler.cli','migrate'],
}

def main():
 if len(sys.argv)!=2 or sys.argv[1] not in COMMANDS:
  raise SystemExit('Choose test, run, worker, doctor, or migrate')
 metadata=json.loads((ROOT/'.runtime/sqlite-runtime.json').read_text(encoding='utf-8'))
 environment=os.environ.copy()
 if sys.platform.startswith('linux'):
  library=Path(metadata['library_directory']).resolve()
  if (ROOT/'.runtime').resolve() not in library.parents:
   raise SystemExit('Prepared SQLite library is outside the owned runtime directory')
  environment['LD_LIBRARY_PATH']=str(library)+(os.pathsep+environment['LD_LIBRARY_PATH'] if environment.get('LD_LIBRARY_PATH') else '')
 executable=ROOT/'.venv'/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
 result=subprocess.run([str(executable),*COMMANDS[sys.argv[1]]],cwd=ROOT,env=environment,check=False)
 raise SystemExit(result.returncode)

if __name__=='__main__':main()

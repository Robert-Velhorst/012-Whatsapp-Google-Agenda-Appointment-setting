from __future__ import annotations
import json,os,secrets,subprocess,time,uuid
from pathlib import Path

owner='agenda-fixture-'+uuid.uuid4().hex
volume=owner+'-data'
env={**os.environ,'ADMIN_API_TOKEN':secrets.token_hex(32),'FLASK_SECRET_KEY':secrets.token_hex(32)}
def docker(*args):
 return subprocess.check_output(['docker',*args],text=True,encoding='utf-8',env=env,timeout=120).strip()
probe=r'''
import json,os,urllib.request,urllib.error
url='http://127.0.0.1:5000'
with urllib.request.urlopen(url+'/api/health') as response:
 health=json.load(response)
 assert health['ok'] and health['service']=='agenda-relay'
 assert health['runtime']['python']=='3.15.1' and health['runtime']['sqlite']=='3.54.1'
with urllib.request.urlopen(url+'/login') as response:
 assert response.status==200 and b'Agenda Relay' in response.read()
 assert response.headers['X-Content-Type-Options']=='nosniff'
try:
 urllib.request.urlopen(url+'/api/operator/readiness')
 raise AssertionError('Missing token was accepted')
except urllib.error.HTTPError as error: assert error.code==401
request=urllib.request.Request(url+'/api/operator/readiness',headers={'Authorization':'Bearer '+os.environ['ADMIN_API_TOKEN']})
with urllib.request.urlopen(request) as response: assert response.status==200
print(json.dumps({'python':health['runtime']['python'],'sqlite':health['runtime']['sqlite'],'unauthorizedDenied':True,'loginIdentity':True,'authenticatedReadinessEndpoint':True}))
'''
compile(probe,'<owned-fixture>','exec')
container=None;created_volume=False
report={'network':'none','syntheticOnly':True,'providerRequests':0,'liveProvidersVerified':False}
try:
 docker('volume','create','--label','agenda.fixture='+owner,volume);created_volume=True
 container=docker('run','--detach','--name',owner,'--label','agenda.fixture='+owner,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--tmpfs','/tmp:rw,size=64m','--mount','type=volume,source='+volume+',target=/app/data','--env','APP_ENV=development','--env','AUTOMATION_PAUSED=true','--env','AUTO_SEND_SUGGESTIONS=false','--env','AUTO_BOOK_CONFIRMED=false','--env','ADMIN_API_TOKEN','--env','FLASK_SECRET_KEY','agenda-relay:test')
 for _ in range(60):
  try:
   docker('exec',container,'python','-c',"import urllib.request;urllib.request.urlopen('http://127.0.0.1:5000/api/health',timeout=2)")
   break
  except subprocess.CalledProcessError:time.sleep(0.5)
 else:raise RuntimeError('Owned synthetic image did not become healthy')
 report.update(json.loads(docker('exec',container,'python','-c',probe)))
 worker=docker('exec',container,'python','-m','scheduler.cli','worker','--once')
 report['pausedWorkerOneShotCompleted']=True
 report['outcome']='passed'
finally:
 if container:
  state=json.loads(docker('inspect',container))[0]
  assert state['Id']==container and state['Config']['Labels']['agenda.fixture']==owner and state['Config']['User']=='agenda'
  assert all((m['Type']=='volume' and m['Name']==volume) or m['Type']=='tmpfs' for m in state['Mounts'])
  docker('rm','--force',container)
 if created_volume:
  state=json.loads(docker('volume','inspect',volume))[0]
  assert state['Name']==volume and state['Labels']['agenda.fixture']==owner
  docker('volume','rm',volume)
 report['ownedFixturesRemoved']=True
 Path('artifacts').mkdir(exist_ok=True)
 Path('artifacts/container-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))

#!/usr/bin/env python3
"""Exercise actual optional archive preflight and before-bootstrap failure ordering."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib,json,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unixnu import kernel
from unixnu.util import Error

with tempfile.TemporaryDirectory(prefix='archive-preflight-') as directory:
 root=Path(directory);(root/'scripts').mkdir();(root/'logs').mkdir()
 cache=root/'original';cache.write_bytes(b'actual CLI-selected cache')
 boardcache=root/'other';boardcache.write_bytes(b'board-selected cache')
 digest=hashlib.sha256(cache.read_bytes()).hexdigest()
 spec={'tool':'kits/NativePrelink/emit_prelink.py','roots':['good'], 'kernelcache':str(boardcache),
       'kernelcache_sha256':digest,'archive_preflight':['check.py']}
 (root/'scripts/check.py').write_text('not executed by this host fixture\n')
 (root/'scripts/build-xnu-4k-baseline.sh').write_text('not executed\n')
 ctx=SimpleNamespace(tree=root,logs=root/'logs',jobs=4,board={'kernel':{'prelink':spec}},
  need_config=lambda:{'XNU_BUILD_ARCHIVES':True},option=lambda *args:cache)
 # No hook/default and archives-off do not even resolve an input or modify env.
 for enabled,hooks in [(True,[]),(False,['check.py'])]:
  ctx.need_config=lambda:{'XNU_BUILD_ARCHIVES':enabled};spec['archive_preflight']=hooks;env={}
  with patch.object(kernel,'prelink_cache',side_effect=AssertionError('default path touched cache')):
   kernel.archive_preflight(ctx,env)
  assert not env
 spec['archive_preflight']=['check.py'];ctx.need_config=lambda:{'XNU_BUILD_ARCHIVES':True}
 calls=[]
 def guard(command,**kwargs):
  calls.append(command)
  env=kwargs['env'];assert json.loads(env['UNIXNU_PRELINK_SPEC'])==spec
  assert Path(env['UNIXNU_PRELINK_KERNELCACHE'])==cache
  assert env['A04BR3_WIFI']=='1' and kwargs['cwd']==root
 with patch.object(kernel,'run',guard):kernel.archive_preflight(ctx,{'A04BR3_WIFI':'1'})
 assert calls==[['python3',root/'scripts/check.py']]
 # Complete real build entry must stop on guard failure before a bootstrap command.
 calls=[]
 def refuse(command,**kwargs):
  calls.append(command);assert command==['python3',root/'scripts/check.py'];raise Error('fixture duplicate family')
 with patch.object(kernel,'tool'),patch.object(kernel,'run',refuse),patch.dict(kernel.os.environ,{'A04BR3_WIFI':'1'}):
  try:kernel.build(ctx,{})
  except Error as error:assert 'duplicate family' in str(error)
  else:raise AssertionError('preflight refusal ignored')
 assert len(calls)==1
 cache.write_bytes(b'changed')
 with patch.object(kernel,'run',side_effect=AssertionError('ran guard on wrong hash')):
  try:kernel.archive_preflight(ctx,{})
  except Error as error:assert 'sha256' in str(error)
  else:raise AssertionError('cache mismatch accepted')
 # Prelink itself uses exactly the same resolver, not the stale board path.
 assert 'cache = prelink_cache(ctx, spec)' in __import__('inspect').getsource(kernel.prelink)
print('PASS actual optional archive guard: default no-op, CLI-selected/hash-checked inputs, environment propagation, failure before bootstrap/compile, shared prelink resolver; no SDK/hardware')

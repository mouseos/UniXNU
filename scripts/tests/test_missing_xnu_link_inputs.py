#!/usr/bin/env python3
"""An interrupted incremental build must not send missing objects to nm."""
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unixnu.kernel import missing_link_inputs
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp); d=root/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837';d.mkdir(parents=True)
 assert missing_link_inputs(root)==[]
 a=root/'present.o';a.write_bytes(b'object');b=root/'KernelConfigTables.cpo'
 (d/'link.filelist').write_text(str(a)+'\n'+str(b)+'\nrelative.o\n\n')
 assert missing_link_inputs(root)==[str(b),str(root/'relative.o')]
 b.write_bytes(b'object');(root/'relative.o').write_bytes(b'object')
 assert missing_link_inputs(root)==[]
print('PASS missing XNU link input detection and recovery precondition')

# Exercise the actual orchestration: records can survive an interrupted build,
# but archive generation must wait for the missing object to be regenerated.
from unittest.mock import patch
import unixnu.kernel as kernel
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp); obj=root/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'; record=obj/'osfmk/DEVELOPMENT/startup.o.json'; record.parent.mkdir(parents=True);record.write_text('{}')
 missing=obj/'iokit/DEVELOPMENT/KernelConfigTables.cpo';missing.parent.mkdir(parents=True)
 (obj/'link.filelist').write_text(str(missing)+'\n')
 (root/'scripts').mkdir();(root/'scripts/build-xnu-4k-baseline.sh').write_text('')
 class Ctx:
  tree=root; logs=root; jobs=1; board={'kernel':{}}
  def need_config(self): return {}
 ctx=Ctx();calls=[]
 def run_fake(command,**kwargs):
  calls.append('bootstrap' if kwargs['env'].get('XNU_BOOTSTRAP')=='1' else 'build')
  if calls[-1]=='bootstrap': missing.write_bytes(b'object')
 def archives_fake(ctx,env):
  assert missing.is_file();calls.append('archives')
 with patch.object(kernel,'tool'),patch.object(kernel,'version_env',return_value={}),patch.object(kernel,'run',side_effect=run_fake),patch.object(kernel,'build_archives',side_effect=archives_fake):
  kernel.build(ctx,{})
 assert calls==['bootstrap','archives','build'],calls
print('PASS actual build ordering: bootstrap regenerates missing object before archives')

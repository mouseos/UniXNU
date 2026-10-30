#!/usr/bin/env python3
"""Test the checked-in XNU patch and default-off/opt-in hook contract."""
import os
from pathlib import Path
import subprocess
import tempfile
import sys
from types import SimpleNamespace
root=Path(__file__).resolve().parents[2]
patch=root/'patches/xnu/zzzz-cpu-thread-switch-observer.patch'
makepatch=root/'patches/xnu/zzzz-cpu-thread-switch-observer-make.patch'
text=patch.read_text()
assert '+#if defined(XNU_ARMCPU_SWITCH_OBSERVER) && XNU_ARMCPU_SWITCH_OBSERVER' in text
lines=[line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++')]
code='\n'.join(lines)
assert 'get_preemption_level() <= 0' in code and 'thread->c_switch' in code
make=makepatch.read_text()
assert 'sched_prim.o_CFLAGS_ADD += -DXNU_ARMCPU_SWITCH_OBSERVER=$(XNU_ARMCPU_SWITCH_OBSERVER)' in make
build=(root/'scripts/build-xnu-4k-baseline.sh').read_text()
for token in ('${XNU_ARMCPU_SWITCH_OBSERVER:-0}', '.armcpu-switch-observer-mode', 'osfmk/DEVELOPMENT/sched_prim.o', 'XNU_ARMCPU_SWITCH_OBSERVER=$SWITCH_OBSERVER'):
 assert token in build
sys.path.insert(0, str(root/'scripts'))
from unixnu.config import parse_config
from unixnu.kernel import xnu_env
conf=parse_config('CONFIG_XNU_ARMCPU_SWITCH_OBSERVER=y\nCONFIG_XNU_ARMCPU_BUSY_CONTROL=y\n')
ctx=SimpleNamespace(need_config=lambda:conf,tree=root)
env=xnu_env(ctx)
assert env['XNU_ARMCPU_SWITCH_OBSERVER']=='1' and env['XNU_ARMCPU_BUSY_CONTROL']=='1'
assert not xnu_env(SimpleNamespace(need_config=lambda:{},tree=root))
prefix='''#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\nstruct thread { uint32_t c_switch; }; typedef struct thread *thread_t;\n#define THREAD_NULL NULL\nstatic struct thread t; static thread_t current=&t; static int level;\nstatic int get_preemption_level(void){return level;}\nstatic thread_t current_thread(void){return current;}\n'''
main='''\nint main(void){uint32_t out=7;level=0; if(unixnu_current_thread_switches(&out)||out!=7)return 1; level=1;if(unixnu_current_thread_switches(NULL))return 2;current=NULL;if(unixnu_current_thread_switches(&out))return 3;current=&t;t.c_switch=0xffffffffu;if(!unixnu_current_thread_switches(&out)||out!=0xffffffffu)return 4;t.c_switch++;if(!unixnu_current_thread_switches(&out)||out!=0)return 5;return 0;}\n'''
with tempfile.TemporaryDirectory() as d:
 d=Path(d);src=d/'hook.c';exe=d/'hook';obj=d/'off.o'
 src.write_text(prefix+code+main)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-DXNU_ARMCPU_SWITCH_OBSERVER=1',str(src),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
 src.write_text(prefix+code)
 subprocess.run(['cc','-std=c11','-Wno-unused-function','-Wno-unused-variable','-c',str(src),'-o',str(obj)],check=True)
 assert 'unixnu_current_thread_switches' not in subprocess.check_output(['nm',str(obj)],text=True)
 feed=os.environ.get('XNU_SWITCH_TEST_SOURCE')
 if feed:
  feed=Path(feed);(d/'osfmk/kern').mkdir(parents=True);(d/'makedefs').mkdir()
  (d/'osfmk/kern/sched_prim.c').write_bytes((feed/'osfmk/kern/sched_prim.c').read_bytes())
  (d/'makedefs/MakeInc.rule').write_bytes((feed/'makedefs/MakeInc.rule').read_bytes())
  for p in (root/'patches/xnu/zz-p31-irq-pc-make.patch',root/'patches/xnu/zzzz-cpu-idle-epoch-make.patch',makepatch,patch):
   subprocess.run(['patch','--batch','-p1','-i',str(p)],cwd=d,check=True,stdout=subprocess.DEVNULL)
print('PASS switch hook: opt-in, preemption guard, values, default-off symbol and patch application when source supplied')

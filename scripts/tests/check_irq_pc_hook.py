#!/usr/bin/env python3
"""Check the canonical timer patch against the pinned XNU and compile both modes."""
from pathlib import Path
import argparse
import subprocess
import os
import tempfile

root=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--xnu-source',type=Path,required=True);a=p.parse_args()
source=a.xnu_source.resolve()
patch=root/'patches/xnu/zz-p31-irq-pc-stats.patch'
subprocess.run(['git','-C',str(source),'apply','--check',str(patch)],check=True)
text=patch.read_text()
assert 'XNU_IRQ_PC_STATS' in text and 'native_irq_pc_sample(user_mode ? 0 : VM_KERNEL_UNSLIDE(pc), user_mode)' in text
harness=r'''
#include <stdint.h>
static unsigned hits;
static void observed(uint64_t p,unsigned u){(void)p;(void)u;++hits;}
#define VM_KERNEL_UNSLIDE(p) ((p)-0x1000)
#if XNU_IRQ_PC_STATS
static void (*native_irq_pc_sample)(uint64_t,unsigned)=observed;
#endif
static void sample(uint64_t pc,unsigned user_mode){
#if XNU_IRQ_PC_STATS
 if (native_irq_pc_sample) {
  native_irq_pc_sample(user_mode ? 0 : VM_KERNEL_UNSLIDE(pc), user_mode);
 }
#endif
 (void)pc;(void)user_mode;
}
int main(void){sample(0x3000,0);return hits != XNU_IRQ_PC_STATS;}
'''
with tempfile.TemporaryDirectory(prefix='irq-pc-hook-') as tmp:
 c=Path(tmp)/'test.c';b=Path(tmp)/'test';c.write_text(harness)
 for mode in (0,1):
  subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function',
                  f'-DXNU_IRQ_PC_STATS={mode}',str(c),'-o',str(b)],check=True)
  subprocess.run([str(b)],check=True)
print('PASS: pinned timer patch applies; enabled and disabled hook fixtures')

# XNU's per-target variable must preserve its own += additions and must not
# affect another target. Exercise the actual GNU make expansion shape.
with tempfile.TemporaryDirectory(prefix='irq-pc-make-') as tmp:
    m=Path(tmp)/'Makefile'
    m.write_text('rtclock.o_CFLAGS_ADD += -DOTHER_FLAG=1\nall: rtclock.o other.o\nrtclock.o other.o:\n\t@printf "%s:%s\\n" "$@" "$($@_CFLAGS_ADD)"\n')
    env={**os.environ,'rtclock.o_CFLAGS_ADD':'-DXNU_IRQ_PC_STATS=1'}
    lines=subprocess.check_output(['make','-f',str(m)],text=True,env=env).splitlines()
    assert lines == ['rtclock.o:-DXNU_IRQ_PC_STATS=1 -DOTHER_FLAG=1','other.o:'], lines
print('PASS: per-object make flag preserves target additions and excludes unrelated object')

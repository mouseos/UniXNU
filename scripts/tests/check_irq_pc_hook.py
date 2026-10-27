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
subprocess.run(['git','-C',str(source),'apply','--check',str(root/'patches/xnu/zz-p31-irq-pc-make.patch')],check=True)
text=patch.read_text()
assert 'native_irq_correlation_sample(user_mode ? pc : VM_KERNEL_UNSLIDE(pc), user_mode)' in text
assert 'XNU_IRQ_PC_STATS' in text and 'native_irq_pc_sample(user_mode ? 0 : VM_KERNEL_UNSLIDE(pc), user_mode)' in text
assert 'native_live_pc_sample(user_mode ? pc : VM_KERNEL_UNSLIDE(pc),' in text
assert 'user_mode ? get_saved_state_lr(regs) : 0, user_mode' in text
harness=r'''
#include <stdint.h>
static unsigned hits, correlated;
static uint64_t last_pc; static unsigned last_user;
static void observed(uint64_t p,unsigned u){(void)p;(void)u;++hits;}
static void pair(uint64_t p,unsigned u){++correlated;last_pc=p;last_user=u;}
#define VM_KERNEL_UNSLIDE(p) ((p)-0x1000)
#if XNU_IRQ_PC_STATS
static void (*native_irq_pc_sample)(uint64_t,unsigned)=observed;
static void (*native_irq_correlation_sample)(uint64_t,unsigned)=pair;
#endif
static void sample(uint64_t pc,unsigned user_mode){
#if XNU_IRQ_PC_STATS
 if (native_irq_pc_sample) {
  native_irq_pc_sample(user_mode ? 0 : VM_KERNEL_UNSLIDE(pc), user_mode);
 }
 if (native_irq_correlation_sample) native_irq_correlation_sample(user_mode ? pc : VM_KERNEL_UNSLIDE(pc), user_mode);
#endif
 (void)pc;(void)user_mode;
}
int main(void){sample(0x3000,0);sample(0x4500,1);return hits != 2*XNU_IRQ_PC_STATS || correlated != 2*XNU_IRQ_PC_STATS || (XNU_IRQ_PC_STATS && (last_pc != 0x4500 || last_user != 1));}
'''
with tempfile.TemporaryDirectory(prefix='irq-pc-hook-') as tmp:
 c=Path(tmp)/'test.c';b=Path(tmp)/'test';c.write_text(harness)
 for mode in (0,1):
  subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function',
                  f'-DXNU_IRQ_PC_STATS={mode}',str(c),'-o',str(b)],check=True)
  subprocess.run([str(b)],check=True)
print('PASS: pinned timer patch applies; enabled and disabled hook fixtures')

# Compile the actual added timer block with stub observers, not a rewritten
# approximation. Check both modes, kernel unsliding, user LR and missing hooks.
added=[line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++')]
start=added.index('#if defined(XNU_IRQ_PC_STATS) && XNU_IRQ_PC_STATS', added.index('int native_irq_pc_hook_compiled(void) { return NATIVE_IRQ_PC_MODE; }'))
depth=0
for end in range(start,len(added)):
 line=added[end]
 if line.startswith('#if'): depth+=1
 if line.startswith('#endif'):
  depth-=1
  if depth==0: break
block='\n'.join(added[start:end+1])
source=r"""
#include <stdint.h>
#include <assert.h>
#define VM_KERNEL_UNSLIDE(p) ((p)-0x1000)
#define get_saved_state_lr(p) (*(p))
static unsigned old_count,corr_count,live_count;
static uint64_t old_pc,corr_pc,live_pc,live_lr;
static unsigned old_mode,corr_mode,live_mode;
#if XNU_IRQ_PC_STATS
static void old(uint64_t p,unsigned u){old_count++;old_pc=p;old_mode=u;}
static void corr(uint64_t p,unsigned u){corr_count++;corr_pc=p;corr_mode=u;}
static void live(uint64_t p,uint64_t l,unsigned u){live_count++;live_pc=p;live_lr=l;live_mode=u;}
static void (*native_irq_pc_sample)(uint64_t,unsigned)=old;
static void (*native_irq_correlation_sample)(uint64_t,unsigned)=corr;
static void (*native_live_pc_sample)(uint64_t,uint64_t,unsigned)=live;
#endif
static void sample(uint64_t pc,unsigned user_mode,uint64_t *regs){
"""+block+r"""
 (void)pc;(void)user_mode;(void)regs;
}
int main(void){
 uint64_t lr=0x9988;sample(0x3200,0,&lr);
 if (XNU_IRQ_PC_STATS){
  assert(old_count==1 && old_pc==0x2200 && old_mode==0);
  assert(corr_count==1 && corr_pc==0x2200 && corr_mode==0);
  assert(live_count==1 && live_pc==0x2200 && live_lr==0 && live_mode==0);
 }
 sample(0x4500,1,&lr);
 if (XNU_IRQ_PC_STATS){
  assert(old_count==2 && old_pc==0 && old_mode==1);
  assert(corr_count==2 && corr_pc==0x4500 && corr_mode==1);
  assert(live_count==2 && live_pc==0x4500 && live_lr==lr && live_mode==1);
#if XNU_IRQ_PC_STATS
  native_irq_pc_sample=0;native_irq_correlation_sample=0;native_live_pc_sample=0;
  sample(0x5000,1,&lr);
  assert(old_count==2 && corr_count==2 && live_count==2);
#endif
 } else assert(!old_count && !corr_count && !live_count);
 return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='irq-pc-actual-') as tmp:
 c=Path(tmp)/'test.c'; b=Path(tmp)/'test';c.write_text(source)
 for mode in (0,1):
  subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',
                  f'-DXNU_IRQ_PC_STATS={mode}','-D__arm64__=1',str(c),'-o',str(b)],check=True)
  subprocess.run([str(b)],check=True)
print('PASS: actual timer block preserves all three observers, modes and optional hooks')

# Simulate XNU's recursive make through a POSIX shell that drops environment
# names containing dots. The legal-name mode must reach the child, where the
# per-object rule preserves other additions and excludes unrelated objects.
with tempfile.TemporaryDirectory(prefix='irq-pc-make-') as tmp:
    m=Path(tmp)/'Makefile'
    m.write_text('rtclock.o_CFLAGS_ADD += -DOTHER_FLAG=1\n'
                 'ifneq ($(XNU_IRQ_PC_STATS),)\n'
                 'override rtclock.o_CFLAGS_ADD += -DXNU_IRQ_PC_STATS=$(XNU_IRQ_PC_STATS)\n'
                 'endif\nall:\n\t@$(MAKE) -f $(firstword $(MAKEFILE_LIST)) child;\n'
                 'child: rtclock.o other.o\nrtclock.o other.o:\n'
                 '\t@printf "%s:%s\\n" "$@" "$($@_CFLAGS_ADD)"\n')
    for mode in ('0','1'):
        env={**os.environ,'XNU_IRQ_PC_STATS':mode}
        output=subprocess.check_output(['make','--no-print-directory','-f',str(m)],text=True,env=env).splitlines()
        assert output == [f'rtclock.o:-DOTHER_FLAG=1 -DXNU_IRQ_PC_STATS={mode}','other.o:'], output
    env={**os.environ,'XNU_IRQ_PC_STATS':'1'}
    output=subprocess.check_output(['make','--no-print-directory','-f',str(m),'rtclock.o_CFLAGS_ADD=-DCALLER=1'],text=True,env=env).splitlines()
    assert output == ['rtclock.o:-DCALLER=1 -DXNU_IRQ_PC_STATS=1','other.o:'], output
print('PASS: IRQ mode survives shell and recursive make, preserves other per-object flags')

# Use the actual added declarations, including the capability function, with
# the XNU missing-prototype warning enabled for the Apple ARM64 target.
lines=[line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++')]
start=lines.index('#if defined(XNU_IRQ_PC_STATS) && XNU_IRQ_PC_STATS')
end=lines.index('int native_irq_pc_hook_compiled(void) { return NATIVE_IRQ_PC_MODE; }',start)
declarations='typedef unsigned long long uint64_t;\n'+'\n'.join(lines[start:end+1])+'\n'
for mode in (0,1):
 subprocess.run(['clang','-target','arm64-apple-darwin','-ffreestanding',
                 '-fsyntax-only','-Wmissing-prototypes','-Werror',
                 f'-DXNU_IRQ_PC_STATS={mode}','-x','c','-'],input=declarations,text=True,check=True)
 with tempfile.TemporaryDirectory() as tmp:
  source=Path(tmp)/'mode.c'; binary=Path(tmp)/'mode'
  source.write_text(declarations.replace('__attribute__((weak_import))','')+'int main(void) { return native_irq_pc_hook_compiled() != '+str(mode)+'; }\n')
  subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',f'-DXNU_IRQ_PC_STATS={mode}',str(source),'-o',str(binary)],check=True)
  subprocess.run([str(binary)],check=True)
print('PASS: timer hook declarations satisfy missing-prototype warning')

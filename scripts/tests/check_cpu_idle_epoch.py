#!/usr/bin/env python3
"""Exercise the actual injected epoch code with host CPU/idle stubs."""
from pathlib import Path
import subprocess, tempfile
root=Path(__file__).resolve().parents[2]
patch=(root/'patches/xnu/zzzz-cpu-idle-epoch.patch').read_text()
added='\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
start=added.index('#if defined(XNU_ARMCPU_IDLE_EPOCH)')
end=added.index('#endif',start)+len('#endif')
implementation=added[start:end]
assert 'unixnu_idle_epoch_transition(true)' in added and 'unixnu_idle_epoch_transition(false)' in added
assert patch.index('unixnu_idle_epoch_transition(true)') < patch.index('Check for, and act on, a WFE recommendation.')
assert patch.index('unixnu_idle_epoch_transition(false)') < patch.index('__builtin_arm_wsr("DAIFClr"')
makepatch=(root/'patches/xnu/zzzz-cpu-idle-epoch-make.patch').read_text()
assert 'machine_routines.o_CFLAGS_ADD += -DXNU_ARMCPU_IDLE_EPOCH=$(XNU_ARMCPU_IDLE_EPOCH)' in makepatch
build=(root/'scripts/build-xnu-4k-baseline.sh').read_text()
assert '${XNU_ARMCPU_IDLE_EPOCH:-0}' in build and '.armcpu-idle-epoch-mode' in build
stub='''#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#define MAX_CPUS 4
struct cpu { void *cpu_id; short cpu_number; } cpus[4]={{0,0},{0,1},{0,2},{0,3}}, bad={0,4}, negative={0,-1};
static struct cpu *current=&cpus[0];
static bool force_cas_failure=false;
#define __atomic_compare_exchange_n(p,e,d,w,s,f) (force_cas_failure ? false : __atomic_compare_exchange_n(p,e,d,w,s,f))
static struct cpu *getCpuDatap(void){return current;}
'''
main='''
int main(void) {
 assert(unixnu_idle_epoch_current(current->cpu_number)==0);assert(unixnu_idle_epoch_current(1)==UINT64_MAX);unixnu_idle_epoch_transition(true);assert(unixnu_idle_epoch_current(current->cpu_number)==1);
 current=&cpus[1];assert(unixnu_idle_epoch_current(current->cpu_number)==0);unixnu_idle_epoch_transition(true);unixnu_idle_epoch_transition(false);assert(unixnu_idle_epoch_current(current->cpu_number)==2);
 current=&cpus[0];unixnu_idle_epoch_transition(false);assert(unixnu_idle_epoch_current(current->cpu_number)==2);
 unixnu_idle_epoch_transition(false);assert(unixnu_idle_epoch_current(current->cpu_number)==UINT64_MAX);unixnu_idle_epoch_transition(true);assert(unixnu_idle_epoch_current(current->cpu_number)==UINT64_MAX);
 current=&cpus[2];unixnu_idle_epoch_transition(true);unixnu_idle_epoch_transition(true);assert(unixnu_idle_epoch_current(current->cpu_number)==UINT64_MAX);
 unixnu_idle_epoch[2]=0;force_cas_failure=true;unixnu_idle_epoch_transition(true);assert(unixnu_idle_epoch_current(2)==UINT64_MAX);force_cas_failure=false;unixnu_idle_epoch_transition(false);assert(unixnu_idle_epoch_current(2)==UINT64_MAX);
 current=&cpus[3];unixnu_idle_epoch[3]=UINT64_MAX-3;unixnu_idle_epoch_transition(true);unixnu_idle_epoch_transition(false);assert(unixnu_idle_epoch_current(3)==UINT64_MAX-1);unixnu_idle_epoch_transition(true);assert(unixnu_idle_epoch_current(current->cpu_number)==UINT64_MAX);
 current=&bad;assert(unixnu_idle_epoch_current(4)==UINT64_MAX);unixnu_idle_epoch_transition(true);
 current=&negative;assert(unixnu_idle_epoch_current(0)==UINT64_MAX);unixnu_idle_epoch_transition(true);
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='idle-epoch-test-') as tmp:
 p=Path(tmp);src=p/'test.c';exe=p/'test';src.write_text(stub+implementation+main)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all','-DXNU_ARMCPU_IDLE_EPOCH=1',str(src),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
 # The feature's code and externally visible function are absent when disabled.
 off=p/'off.c';off.write_text('#include <stdint.h>\n#include <stdbool.h>\n'+implementation+'\nint main(void){return 0;}\n')
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-DXNU_ARMCPU_IDLE_EPOCH=0',str(off),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('PASS actual idle epoch code: CPU isolation, paired transitions, poison and default off')

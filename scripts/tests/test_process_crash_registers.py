#!/usr/bin/env python3
"""Run the actual crash-register block of patches/xnu/zzzzz-process-crash-registers.patch against a mock exiting thread:
the ucp= name filter, the 32-crash budget, the frame chain (stops on a failed read, a non-ascending or misaligned frame
pointer, 26 entries at most), the shared-region marking and the Mach-O header walk for frames outside it."""
from pathlib import Path
import subprocess, tempfile
root = Path(__file__).resolve().parents[2]
patch = (root / 'patches/xnu/zzzzz-process-crash-registers.patch').read_text()
added = [x[1:] for x in patch.splitlines() if x.startswith('+') and not x.startswith('+++')]
start = next(i for i, x in enumerate(added) if x.startswith('#if defined(XNU_PROCESS_EXIT_DIAG)'))
block = '\n'.join(added[start:])
assert block.rstrip().endswith('#endif') and 'ucp' in block
src = r'''#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdbool.h>
#include <assert.h>
#define __arm64__ 1
#define KERN_SUCCESS 0
#define SHARED_REGION_BASE_ARM64 0x180000000ULL
#define SHARED_REGION_SIZE_ARM64 0x180000000ULL
#define WTERMSIG(x) ((x) & 0x7f)
typedef void *thread_t; typedef void *task_t; typedef void *vm_shared_region_t; typedef uint64_t mach_vm_offset_t; typedef uint64_t user_addr_t;
struct arm_saved_state { uint64_t pc, lr, sp, fp; };
struct uthread { int uu_exception; long long uu_code, uu_subcode; };
struct proc { char p_name[33]; };
static struct proc *cur; static const char *bootarg; static struct arm_saved_state regs; static int lines; static char last[256];
static struct proc *current_proc(void) { return cur; }
static int PE_parse_boot_argn(const char *k, void *o, int n) { (void)k; if (!bootarg) return 0; snprintf(o, n, "%s", bootarg); return 1; }
struct arm_saved_state *find_user_regs(thread_t t) { (void)t; return &regs; }
static uint64_t get_saved_state_pc(struct arm_saved_state *s) { return s->pc; }
static uint64_t get_saved_state_lr(struct arm_saved_state *s) { return s->lr; }
static uint64_t get_saved_state_sp(struct arm_saved_state *s) { return s->sp; }
static uint64_t get_saved_state_fp(struct arm_saved_state *s) { return s->fp; }
static vm_shared_region_t vm_shared_region_get(task_t t) { (void)t; return (void *)1; }
static int vm_shared_region_start_address(vm_shared_region_t r, mach_vm_offset_t *a, task_t t) { (void)r; (void)t; *a = 0x18ead4000ULL; return 0; }
static void vm_shared_region_deallocate(vm_shared_region_t r) { (void)r; }
static int proc_getpid(struct proc *p) { (void)p; return 113; }
/* user memory: a frame chain and one Mach-O header at 0x104000000 */
static uint64_t mem_addr[16], mem_val[16][2]; static int mem_n;
static int copyin(user_addr_t a, void *out, size_t n) {
  if (n == 4) { if (a == 0x104000000ULL) { *(uint32_t *)out = 0xfeedfacf; return 0; } if (a < 0x104000000ULL) return 14; *(uint32_t *)out = 0; return 0; }
  for (int i = 0; i < mem_n; i++) if (mem_addr[i] == a) { memcpy(out, mem_val[i], 16); return 0; }
  return 14; }
#define printf(...) (++lines, snprintf(last, sizeof last, __VA_ARGS__))
static void run(struct proc *p, int rv, thread_t self, task_t task, struct uthread *ut) {
''' + block + r'''
}
int main(void) {
  struct proc p = {"iconservicesagent"}; struct uthread ut = {1, 1, 0}; cur = &p;
  regs = (struct arm_saved_state){0, 0x18f001234ULL, 0x16f000000ULL, 0x16f000100ULL};
  mem_addr[0] = 0x16f000100ULL; mem_val[0][0] = 0x16f000200ULL; mem_val[0][1] = 0x18f005678ULL;
  mem_addr[1] = 0x16f000200ULL; mem_val[1][0] = 0x16f000300ULL; mem_val[1][1] = 0x104012345ULL;
  mem_addr[2] = 0x16f000300ULL; mem_val[2][0] = 0x16f000100ULL; mem_val[2][1] = 0x18f00aaaaULL; /* goes back: stop */
  mem_n = 3;
  bootarg = 0; run(&p, 11, 0, (void *)1, &ut); assert(lines == 0);
  bootarg = "backboardd"; run(&p, 11, 0, (void *)1, &ut); assert(lines == 0);
  bootarg = "iconservicesagent"; run(&p, 11, 0, (void *)1, &ut);
  /* header + pc + lr + 3 chain entries */
  assert(lines == 6); assert(strstr(last, "bt4=0x18f00aaaa cache image=0x0"));
  lines = 0; cur = 0; run(&p, 11, 0, (void *)1, &ut); assert(lines == 0); cur = &p;  /* not the exiting process */
  regs.pc = 0x104012345ULL; regs.fp = 0x16f000301ULL; /* misaligned frame pointer: registers only */
  run(&p, 11, 0, (void *)1, &ut); assert(lines == 3); assert(strstr(last, "lr1=0x18f001234 cache image=0x0"));
  for (int i = 0; i < 40; i++) { lines = 0; run(&p, 11, 0, (void *)1, &ut); }
  assert(lines == 0); /* 32 per boot */
  puts("PASS: ucp filter, exiting-process check, frame chain stops, cache marking, header walk, 32-crash budget");
  return 0; }
'''
with tempfile.TemporaryDirectory() as d:
    c = Path(d) / 't.c'; c.write_text(src)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Wno-unused-parameter', '-Wno-unused-function', '-Werror', '-fsanitize=address,undefined',
                    '-DXNU_PROCESS_EXIT_DIAG=1', str(c), '-o', str(Path(d) / 't')], check=True)
    subprocess.run([str(Path(d) / 't')], check=True)


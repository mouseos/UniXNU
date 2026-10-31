#!/usr/bin/env python3
"""Run the syscall profile core from the XNU patch on the host with kernel stubs."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
patch = (root / 'patches/xnu/zzzz-syscall-trace.patch').read_text()
hunks = patch.split('diff --git ')
core_file = next(h for h in hunks if h.startswith('a/osfmk/arm64/bsd_arm64.c'))
added = [x[1:] for x in core_file.splitlines() if x.startswith('+') and not x.startswith('+++')]
start = added.index('#if defined(XNU_SYSCALL_TRACE) && XNU_SYSCALL_TRACE')
end = added.index('#endif /* XNU_SYSCALL_TRACE */')
core = '\n'.join(x for x in added[start:end + 1] if not x.startswith('#include'))
for name in ('bsd/dev/arm/systemcalls.c', 'osfmk/arm64/sleh.c', 'osfmk/arm64/bsd_arm64.c'):
    hunk = next(h for h in hunks if h.startswith('a/' + name))
    lines = [x[1:] for x in hunk.splitlines() if x.startswith('+') and not x.startswith('+++')]
    opens = sum(1 for x in lines if x.startswith('#if defined(XNU_SYSCALL_TRACE) && XNU_SYSCALL_TRACE'))
    closes = sum(1 for x in lines if x.startswith('#endif'))
    # Every added line sits behind the build flag.
    assert opens and opens == closes, name

src = r'''#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdarg.h>
#include <assert.h>
#define __improbable(x) (x)
#define __unused __attribute__((unused))
#define relaxed __ATOMIC_RELAXED
#define os_atomic_inc(p, o) __atomic_add_fetch((p), 1, o)
#define os_atomic_add(p, v, o) __atomic_add_fetch((p), (v), o)
#define os_atomic_load(p, o) __atomic_load_n((p), o)
#define os_atomic_store(p, v, o) __atomic_store_n((p), (v), o)
#define os_atomic_xchg(p, v, o) __atomic_exchange_n((p), (v), o)
#define os_atomic_cmpxchg(p, e, n, o) ({ __typeof__(*(p)) _e = (e); __atomic_compare_exchange_n((p), &_e, (n), 0, o, o); })
#define TUNABLE(t, v, k, d) t v = d
#define MACH_TRAP_TABLE_COUNT 128
#define NSEC_PER_MSEC 1000000ULL
#define THREAD_CALL_PRIORITY_LOW 0
#define THREAD_CALL_OPTIONS_ONCE 0
#define bzero(p, n) memset((p), 0, (n))
struct arm_saved_state { uint64_t pc, lr; };
typedef void *thread_call_param_t;
typedef void (*thread_call_func_t)(thread_call_param_t, thread_call_param_t);
typedef struct { thread_call_func_t f; int pending; } *thread_call_t;
typedef struct { uint64_t mach_header_vm_address; } *task_t;
typedef uint64_t user_addr_t;
typedef unsigned long vm_size_t;
static int copyinstr(user_addr_t a, char *b, vm_size_t n, vm_size_t *done)
{ if (a == 0xbad) return 14; snprintf(b, n, "%s", (const char *)(uintptr_t)a); *done = strlen(b) + 1; return 0; }
typedef struct { uint32_t sr_slide; } *vm_shared_region_t;
static uint64_t clock_now = 1000;
static uint64_t mach_absolute_time(void) { return clock_now; }
static void absolutetime_to_nanoseconds(uint64_t a, uint64_t *n) { *n = a; }
static void nanoseconds_to_absolutetime(uint64_t n, uint64_t *a) { *a = n; }
static struct { thread_call_func_t f; int pending; } call;
static thread_call_t thread_call_allocate_with_options(thread_call_func_t f, void *p, int pri, int opt)
{ (void)p; (void)pri; (void)opt; call.f = f; return (thread_call_t)&call; }
static int thread_call_enter(thread_call_t c) { c->pending++; return 0; }
static struct { uint64_t mach_header_vm_address; } the_task = { 0x100b88000 };
static task_t current_task(void) { return (task_t)&the_task; }
static struct { uint32_t sr_slide; } region = { 0x1c3c000 };
static vm_shared_region_t vm_shared_region_get(task_t t) { (void)t; return (vm_shared_region_t)&region; }
static void vm_shared_region_deallocate(vm_shared_region_t r) { (void)r; }
static uint64_t get_saved_state_pc(struct arm_saved_state *s) { return s->pc; }
static uint64_t get_saved_state_lr(struct arm_saved_state *s) { return s->lr; }
static uint64_t tid = 7;
static void *current_thread(void) { return 0; }
static uint64_t thread_tid(void *t) { (void)t; return tid; }
static char out[64][512]; static int lines;
static int capture(const char *f, ...) { va_list a; va_start(a, f); vsnprintf(out[lines++], sizeof(out[0]), f, a); va_end(a); return 0; }
#define printf capture
''' + core + r'''
static void run_call(void) { assert(call.pending == 1); call.pending = 0; lines = 0; call.f(0, 0); }
int main(void)
{
	struct arm_saved_state st = { 0x1e4f56794, 0x1b090c308 };
	uint64_t a_err[4] = { 3, 0x16f1e2b10, 1, 0 }, a_ok[4] = { 9, 9, 9, 9 };
	assert(!unixnu_systrace_wants(1));
	unixnu_st_pid = 1;
	assert(unixnu_systrace_wants(1) && !unixnu_systrace_wants(2));
	unixnu_systrace_note(20, 0, 0, a_ok, -1, &st, 0);
	assert(lines == 1 && strstr(out[0], "enabled pid=1") && call.pending == 0);
	for (int i = 0; i < 3; i++) { unixnu_systrace_enter(374); clock_now += 100; unixnu_systrace_note(374, 35, 0, a_err, -1, &st, clock_now - 100); }
	tid = 8;
	unixnu_systrace_enter(374); unixnu_systrace_note(374, 0, 5, a_ok, -1, &st, clock_now);
	for (int i = 0; i < 5; i++) { unixnu_systrace_enter(600 + 31); unixnu_systrace_note(600 + 31, 0, 0, a_ok, -1, &st, 0); }
	for (int i = 0; i < 10; i++) unixnu_systrace_enter(368);
	uint64_t a_path[4] = { (uint64_t)(uintptr_t)"/System/Library/LaunchDaemons/x.plist", 0x1000000, 0, 0 };
	uint64_t a_bad[4] = { 0xbad, 0, 0, 0 };
	unixnu_systrace_enter(398); unixnu_systrace_note(398, 2, 0, a_path, 0, &st, clock_now);
	unixnu_systrace_enter(398); unixnu_systrace_note(398, 0, 3, a_bad, 0, &st, clock_now);
	assert(call.pending == 0);
	clock_now = 1000 + 1000 * NSEC_PER_MSEC;
	unixnu_systrace_note(20, 0, 0, a_ok, -1, &st, clock_now);
	unixnu_systrace_note(20, 0, 0, a_ok, -1, &st, clock_now);
	run_call();
	assert(strstr(out[0], "pid=1 ") && strstr(out[0], "slide=0x1c3c000") && strstr(out[0], "main=0x100b88000"));
	assert(strstr(out[0], "total=24 numbers=5"));
	assert(strstr(out[1], "bsd=368 in=10 n=0 err=0"));
	assert(strstr(out[2], "mach=31 in=5 n=5 err=0 last_err=0 cont=5 avg_ns=0"));
	assert(strstr(out[3], "bsd=374 in=4 n=4 err=3 last_err=35 cont=0 avg_ns=75 ret=0x0 a=0x3,0x16f1e2b10,0x1,0x0 tid=7 pc=0x1e4f56794 lr=0x1b090c308"));
	assert(strstr(out[4], "bsd=20 in=0 n=3") || strstr(out[5], "bsd=20 in=0 n=3"));
	int found = 0;
	for (int i = 1; i < lines; i++)
		if (strstr(out[i], "bsd=398 in=2 n=2 err=1 last_err=2") && strstr(out[i], " path=/System/Library/LaunchDaemons/x.plist")) found++;
	assert(found == 1);
	assert(!strstr(out[3], "path="));
	assert(lines == 6);
	unixnu_systrace_note(20, 0, 0, a_ok, -1, &st, clock_now);
	assert(call.pending == 0);
	clock_now += 1000 * NSEC_PER_MSEC;
	unixnu_systrace_note(20, 0, 0, a_ok, -1, &st, clock_now);
	run_call();
	assert(strstr(out[0], "total=2 numbers=1") && lines == 2);
	unixnu_st_max_windows = 2;
	clock_now += 1000 * NSEC_PER_MSEC;
	unixnu_systrace_note(20, 0, 0, a_ok, -1, &st, clock_now);
	clock_now += 5000 * NSEC_PER_MSEC;
	unixnu_systrace_note(20, 0, 0, a_ok, -1, &st, clock_now);
	assert(call.pending == 0);
	return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
    c = Path(d) / 't.c'
    c.write_text(src)
    exe = Path(d) / 't'
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    '-DXNU_SYSCALL_TRACE=1', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
script = (root / 'scripts/build-xnu-4k-baseline.sh').read_text()
assert 'XNU_SYSCALL_TRACE:-0' in script and 'bsd/DEVELOPMENT/systemcalls.o' in script
assert '-DXNU_SYSCALL_TRACE=$SYSCALL_TRACE' in script
print('PASS: syscall profile counts, failing sample, entry-only calls, order, reset, window limit, opt-in flag')


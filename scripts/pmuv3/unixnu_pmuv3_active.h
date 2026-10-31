/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
#include <stdbool.h>

/* CPU-local caller serializes all operations with local interrupts masked.
 * A nonzero external ownership generation must remain valid throughout the
 * measurement. This arithmetic cannot establish exclusion from firmware. */
typedef struct { uint64_t before, after; uint32_t cycles; bool overflow; } unixnu_pmu_point;
typedef struct {
 uint64_t generation, cycles, min_ticks, max_ticks, last_after;
 unixnu_pmu_point start;
 unsigned cpu, intervals;
 uint32_t last_cycles;
 bool active, idle, failed;
} unixnu_pmu_active;
static inline bool unixnu_pmu_fail(unixnu_pmu_active *s) { s->failed=true; return false; }
static inline bool unixnu_pmu_open(unixnu_pmu_active *s, unsigned cpu, uint64_t gen, unixnu_pmu_point p) {
 if (s->failed || s->active || !gen || p.overflow || p.after-p.before>UINT64_MAX/2) return unixnu_pmu_fail(s);
 if (s->generation && (s->generation!=gen || s->cpu!=cpu || p.before-s->last_after>UINT64_MAX/2 || p.cycles<s->last_cycles)) return unixnu_pmu_fail(s);
 s->generation=gen; s->cpu=cpu; s->start=p; s->active=true; s->idle=false; return true;
}
static inline bool unixnu_pmu_close(unixnu_pmu_active *s, unsigned cpu, uint64_t gen, unixnu_pmu_point p) {
 if (s->failed || !s->active || cpu!=s->cpu || gen!=s->generation || p.overflow || s->start.overflow || p.cycles<s->start.cycles) return unixnu_pmu_fail(s);
 uint64_t a=s->start.after-s->start.before, mid=p.before-s->start.after, b=p.after-p.before;
 if (!mid || a>UINT64_MAX/2 || mid>UINT64_MAX/2 || b>UINT64_MAX/2 || a>UINT64_MAX/2-mid || b>UINT64_MAX/2-mid-a) return unixnu_pmu_fail(s);
 uint64_t max=a+mid+b, delta=(uint64_t)p.cycles-s->start.cycles;
 if (UINT64_MAX-s->cycles<delta || UINT64_MAX-s->min_ticks<mid || UINT64_MAX-s->max_ticks<max || s->intervals==UINT32_MAX) return unixnu_pmu_fail(s);
 s->cycles+=delta; s->min_ticks+=mid; s->max_ticks+=max; s->last_after=p.after; s->last_cycles=p.cycles; s->intervals++; s->active=false; return true;
}
static inline bool unixnu_pmu_idle_enter(unixnu_pmu_active *s, unsigned cpu, uint64_t gen, unixnu_pmu_point p) {
 if (!unixnu_pmu_close(s,cpu,gen,p)) return false; s->idle=true; return true;
}
static inline bool unixnu_pmu_idle_exit(unixnu_pmu_active *s, unsigned cpu, uint64_t gen, unixnu_pmu_point p) {
 if (!s->idle) return unixnu_pmu_fail(s); return unixnu_pmu_open(s,cpu,gen,p);
}
static inline bool unixnu_pmu_bounds(const unixnu_pmu_active *s, uint64_t freq, uint64_t *lo, uint64_t *hi) {
 if (s->failed || s->active || !s->intervals || !freq || !s->min_ticks || !s->max_ticks || !lo || !hi || lo==hi) return false;
 __uint128_t x=(__uint128_t)s->cycles*freq, l=x/s->max_ticks, h=x/s->min_ticks+(x%s->min_ticks!=0);
 if (h>UINT64_MAX) return false; *lo=(uint64_t)l; *hi=(uint64_t)h; return true;
}

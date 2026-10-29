/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include "unixnu_pmuv3_active.h"
/* Called only on the current CPU with IRQ and FIQ masked. The external
 * caller must maintain a non-revocable platform PMU lease and watchdog guard
 * from before configuring the hardware until after restoring it. The local
 * claim below serializes participants only; it does not certify EL2/EL3. */
static unixnu_pmu_active unixnu_pmu_cpus[MAX_CPUS];
static uint64_t unixnu_pmu_claims[MAX_CPUS];
static uint64_t unixnu_pmu_pmcr[MAX_CPUS], unixnu_pmu_filter[MAX_CPUS];
#define UNIXNU_PMU_REG(r) __builtin_arm_rsr64(r)
static bool unixnu_pmu_point_read(unsigned cpu, unixnu_pmu_point *p) {
 uint64_t pmcr=UNIXNU_PMU_REG("PMCR_EL0"), enabled=UNIXNU_PMU_REG("PMCNTENSET_EL0");
 uint64_t filter=UNIXNU_PMU_REG("PMCCFILTR_EL0"), irq=UNIXNU_PMU_REG("PMINTENSET_EL1");
 if ((pmcr & 0x7f)!=1 || enabled!=(1ULL<<31) || (filter & 0xfc000000ULL) || irq ||
     (unixnu_pmu_pmcr[cpu] && (pmcr!=unixnu_pmu_pmcr[cpu] || filter!=unixnu_pmu_filter[cpu]))) return false;
 p->before=UNIXNU_PMU_REG("CNTVCT_EL0"); __builtin_arm_isb(0xf);
 p->cycles=(uint32_t)UNIXNU_PMU_REG("PMCCNTR_EL0"); __builtin_arm_isb(0xf);
 p->after=UNIXNU_PMU_REG("CNTVCT_EL0"); p->overflow=UNIXNU_PMU_REG("PMOVSCLR_EL0")!=0;
 return true;
}
static inline int unixnu_pmu_cpu(void) { int c=getCpuDatap()->cpu_number; return c>=0 && c<MAX_CPUS ? c : -1; }
bool unixnu_pmuv3_active_start(unsigned cpu, uint64_t gen);
bool unixnu_pmuv3_active_stop(unsigned cpu, uint64_t gen, uint64_t *cycles, uint64_t *min_ticks, uint64_t *max_ticks, unsigned *intervals);
bool unixnu_pmuv3_active_start(unsigned cpu, uint64_t gen) {
 if (!gen || unixnu_pmu_cpu()!=(int)cpu || cpu>=MAX_CPUS) return false;
 uint64_t empty=0; if (!__atomic_compare_exchange_n(&unixnu_pmu_claims[cpu],&empty,gen,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) return false;
 unixnu_pmu_cpus[cpu]=(unixnu_pmu_active){0}; unixnu_pmu_pmcr[cpu]=0; unixnu_pmu_filter[cpu]=0;
 unixnu_pmu_point p; bool ok=unixnu_pmu_point_read(cpu,&p);
 if (ok) {unixnu_pmu_pmcr[cpu]=UNIXNU_PMU_REG("PMCR_EL0");unixnu_pmu_filter[cpu]=UNIXNU_PMU_REG("PMCCFILTR_EL0");ok=unixnu_pmu_open(&unixnu_pmu_cpus[cpu],cpu,gen,p);}
 if (!ok) __atomic_store_n(&unixnu_pmu_claims[cpu],0,__ATOMIC_RELEASE);
 return ok;
}
static void unixnu_pmuv3_idle_boundary(bool entry) {
 int c=unixnu_pmu_cpu(); if(c<0) return; unsigned cpu=(unsigned)c;
 uint64_t gen=__atomic_load_n(&unixnu_pmu_claims[cpu],__ATOMIC_ACQUIRE); if(!gen) return;
 unixnu_pmu_point p; if (!unixnu_pmu_point_read(cpu,&p)) {unixnu_pmu_cpus[cpu].failed=true;return;}
 if(entry) (void)unixnu_pmu_idle_enter(&unixnu_pmu_cpus[cpu],cpu,gen,p);
 else (void)unixnu_pmu_idle_exit(&unixnu_pmu_cpus[cpu],cpu,gen,p);
}
bool unixnu_pmuv3_active_stop(unsigned cpu, uint64_t gen, uint64_t *cycles, uint64_t *min_ticks, uint64_t *max_ticks, unsigned *intervals) {
 if (!gen || cpu>=MAX_CPUS || unixnu_pmu_cpu()!=(int)cpu || __atomic_load_n(&unixnu_pmu_claims[cpu],__ATOMIC_ACQUIRE)!=gen || !cycles || !min_ticks || !max_ticks || !intervals) return false;
 unixnu_pmu_point p; unixnu_pmu_active *s=&unixnu_pmu_cpus[cpu];
 bool ok=unixnu_pmu_point_read(cpu,&p) && unixnu_pmu_close(s,cpu,gen,p) && !s->failed;
 if(ok) {*cycles=s->cycles;*min_ticks=s->min_ticks;*max_ticks=s->max_ticks;*intervals=s->intervals;}
 __atomic_store_n(&unixnu_pmu_claims[cpu],0,__ATOMIC_RELEASE); return ok;
}
#undef UNIXNU_PMU_REG

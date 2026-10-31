#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#ifdef NDEBUG
#error Tests require assertions
#endif
#include <assert.h>
#include <stdio.h>
#define MAX_CPUS 4
struct cpudata {int cpu_number;} cpus[4]={{0},{1},{2},{3}}; static unsigned current;
static struct cpudata *getCpuDatap(void) {return &cpus[current];}
static uint64_t ticks,cycles,pmcr=1,enabled=1ULL<<31,filter,irq,overflow;
static uint64_t fake_read(const char *r) {
 if(!strcmp(r,"PMCR_EL0"))return pmcr; if(!strcmp(r,"PMCNTENSET_EL0"))return enabled;
 if(!strcmp(r,"PMCCFILTR_EL0"))return filter; if(!strcmp(r,"PMINTENSET_EL1"))return irq;
 if(!strcmp(r,"CNTVCT_EL0"))return ticks++; if(!strcmp(r,"PMCCNTR_EL0"))return cycles;
 if(!strcmp(r,"PMOVSCLR_EL0"))return overflow; assert(0);return 0;
}
#define __builtin_arm_rsr64(r) fake_read(r)
#define __builtin_arm_isb(x) ((void)(x))
#include "backend.h"
int main(void) {
 uint64_t cy=0,mi=0,ma=0;unsigned n=0;
 assert(unixnu_pmuv3_active_start(0,1));assert(!unixnu_pmuv3_active_start(0,2));
 ticks+=100;cycles+=10000;unixnu_pmuv3_idle_boundary(true);
 ticks+=50;cycles+=50;unixnu_pmuv3_idle_boundary(false);
 ticks+=100;cycles+=10000;assert(unixnu_pmuv3_active_stop(0,1,&cy,&mi,&ma,&n));assert(cy==20000&&n==2&&mi>0&&ma>=mi);
 for(current=0;current<4;current++){ticks=100;cycles=100;assert(unixnu_pmuv3_active_start(current,2));ticks+=100;cycles+=1000;assert(unixnu_pmuv3_active_stop(current,2,&cy,&mi,&ma,&n));assert(cy==1000);}
 current=0; ticks=100;cycles=0;assert(unixnu_pmuv3_active_start(0,3));overflow=1ULL<<31;assert(!unixnu_pmuv3_active_stop(0,3,&cy,&mi,&ma,&n));overflow=0;
 assert(unixnu_pmuv3_active_start(0,4));assert(!unixnu_pmuv3_active_stop(1,4,&cy,&mi,&ma,&n));ticks+=100;cycles+=100;assert(unixnu_pmuv3_active_stop(0,4,&cy,&mi,&ma,&n));
 enabled=3;assert(!unixnu_pmuv3_active_start(0,5));enabled=1ULL<<31;
 puts("PASS PMUv3 backend: CPU local claims, idle intervals, overflow and state refusal");
}

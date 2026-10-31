#include "unixnu_pmuv3_active.h"
#ifdef NDEBUG
#error Tests require assertions
#endif
#include <assert.h>
#include <stdio.h>
static unixnu_pmu_point p(uint64_t t,uint32_t c) { return (unixnu_pmu_point){t,t+2,c,false}; }
int main(void) {
 unixnu_pmu_active s[4]={0}; uint64_t lo,hi;
 for(unsigned c=0;c<4;c++) {assert(unixnu_pmu_open(&s[c],c,7,p(100,1000)));assert(unixnu_pmu_idle_enter(&s[c],c,7,p(230,11000)));assert(unixnu_pmu_idle_exit(&s[c],c,7,p(300,15000)));assert(unixnu_pmu_close(&s[c],c,7,p(430,25000)));assert(unixnu_pmu_bounds(&s[c],13000000,&lo,&hi));assert(s[c].cycles==20000&&lo==984848484&&hi==1015625000);}
 unixnu_pmu_active x={0};assert(unixnu_pmu_open(&x,0,1,p(0,10)));unixnu_pmu_point q=p(100,1);q.overflow=true;assert(!unixnu_pmu_close(&x,0,1,q));assert(!unixnu_pmu_bounds(&x,13000000,&lo,&hi));
 x=(unixnu_pmu_active){0};assert(unixnu_pmu_open(&x,0,1,p(0,10)));assert(!unixnu_pmu_close(&x,1,1,p(100,20)));
 x=(unixnu_pmu_active){0};assert(unixnu_pmu_open(&x,0,1,p(0,10)));assert(!unixnu_pmu_close(&x,0,2,p(100,20)));
 x=(unixnu_pmu_active){0};assert(!unixnu_pmu_idle_exit(&x,0,1,p(0,1)));
 x=(unixnu_pmu_active){0};assert(unixnu_pmu_open(&x,0,1,p(100,10)));assert(!unixnu_pmu_close(&x,0,1,p(50,20)));
 x=(unixnu_pmu_active){0};assert(unixnu_pmu_open(&x,0,1,p(0,100)));assert(unixnu_pmu_idle_enter(&x,0,1,p(100,200)));assert(!unixnu_pmu_idle_exit(&x,0,1,p(200,1)));
 x=(unixnu_pmu_active){0};assert(unixnu_pmu_open(&x,0,1,p(0,10)));assert(unixnu_pmu_idle_enter(&x,0,1,p(100,10)));assert(unixnu_pmu_idle_exit(&x,0,1,p(200,10)));assert(unixnu_pmu_close(&x,0,1,p(300,100)));assert(x.intervals==2&&x.cycles==90);assert(!unixnu_pmu_bounds(&x,13000000,&lo,&lo));
 x=(unixnu_pmu_active){0};assert(unixnu_pmu_open(&x,0,1,p(UINT64_MAX-5,10)));assert(unixnu_pmu_close(&x,0,1,p(2,20)));assert(x.min_ticks==6&&x.max_ticks==10);
 puts("PASS per-CPU active intervals, idle pairs, generation, overflow and time validation");
}

#!/usr/bin/env python3
"""Analyze complete, boot-local CS and MSDC overlap records; no device access."""
import argparse, json, re
from pathlib import Path

def fields(line):
    return {k:int(v) for k,v in re.findall(r'\b([a-z_]+)=(\d+)',line)}

def parse(text):
    streams={'CS':{},'NativeMsdc':{}}; active={}; incomplete=0; stopped=0
    seen={'CS':0,'NativeMsdc':0}
    observed={'CS':{'full':0,'busy':0,'keys_full':0},'NativeMsdc':{'full':0,'contention':0}}
    for line in text.splitlines():
        if 'NativeMsdc overlap stopped final_interval_unreported=1' in line:
            stopped+=1
            continue
        m=re.search(r'(CS|NativeMsdc) overlap (begin|event|end)\b',line)
        if not m: continue
        name,kind=m.groups(); f=fields(line)
        if 'seq' not in f: incomplete+=1; continue
        seq=f['seq']
        if kind=='begin':
            seen[name]+=1
            for k in observed[name]: observed[name][k]+=f.get(k,0)
            if name in active: incomplete+=1
            if seq in streams[name]: raise ValueError('repeated sequence: separate boots before analysis')
            active[name]={'header':f,'events':[],'seq':seq}
        elif name not in active or active[name]['seq']!=seq: incomplete+=1
        elif kind=='event': active[name]['events'].append(f)
        else:
            group=active.pop(name); expected=group['header'].get('count',-1)
            required={'seq','id','op','pid','tid','start','end','base','bytes','reads','error'} if name=='CS' else {'seq','index','ns','pid','tid','window','block','count'}
            bad=any(not required.issubset(e) for e in group['events'])
            if name=='NativeMsdc' and (group['header'].get('prequeue',1)!=1 or group['header'].get('unit')!=512): bad=True
            if name=='NativeMsdc': bad |= [e.get('index') for e in group['events']] != list(range(expected))
            if len(group['events']) != expected or (name=='CS' and f.get('count')!=expected) or bad: incomplete+=1
            else: streams[name][seq]=group
    incomplete+=len(active)
    return streams,incomplete,stopped,seen,observed

def analyze(text):
    if text.count('[pmic6392_init] Preloader Start') > 1:
        raise ValueError('multiple a04br3 preloader boots: separate boots before analysis')
    streams,incomplete,stopped,seen,observed=parse(text); cs=[]; io=[]; loss={}
    for name,groups in streams.items():
        keys=('full','busy','keys_full') if name=='CS' else ('full','contention')
        loss[name]={k:sum(g['header'].get(k,0) for g in groups.values()) for k in keys}
        for g in groups.values(): (cs if name=='CS' else io).extend(g['events'])
    starts={}; ends={}; invalid_cs=0; duplicates=set()
    for e in cs:
        if not all(k in e for k in ('id','op','pid','tid','start','end','base','bytes','reads','error')): continue
        key=(e['id'],e['op'])
        target=ends if e['end'] else starts
        if key in target: duplicates.add(key); invalid_cs+=1
        else: target[key]=e
    completed=[]
    for key,e in ends.items():
        if key in duplicates: continue
        # An end includes its own start; a missing start is visible, not invented.
        if e['end']<e['start']:
            invalid_cs+=1
            continue
        completed.append({**e,'start_observed':key in starts})
    preparation=[]
    for i,a in enumerate(completed):
        for b in completed[i+1:]:
            if a['id']!=b['id'] or a['op']==b['op']: continue
            lo=max(a['base'],b['base']);hi=min(a['base']+a['bytes'],b['base']+b['bytes'])
            if lo<hi:
                preparation.append({'id':a['id'],'ops':[a['op'],b['op']],'file_offset':lo,'bytes':hi-lo,
                                    'time_overlap':max(a['start'],b['start'])<=min(a['end'],b['end']),
                                    'errors':[a['error'],b['error']]})
    block=[]
    for i,a in enumerate(io):
        if not all(k in a for k in ('pid','tid','window','block','count','ns')): continue
        for b in io[i+1:]:
            if not all(k in b for k in ('pid','tid','window','block','count','ns')): continue
            if a['window']!=b['window'] or (a['pid'],a['tid'])==(b['pid'],b['tid']):continue
            lo=max(a['block'],b['block']);hi=min(a['block']+a['count'],b['block']+b['count'])
            if lo<hi:block.append({'window':a['window'],'block':lo,'sectors':hi-lo,'delta_ns':abs(a['ns']-b['ns']),'a':[a['pid'],a['tid'],a['ns']],'b':[b['pid'],b['tid'],b['ns']]})
    candidates=[]
    for e in completed:
        matches=[v for v in io if all(k in v for k in ('pid','tid','ns','block','count','window')) and v['pid']==e['pid'] and v['tid']==e['tid'] and e['start']<=v['ns']<=e['end']]
        candidates.append({'id':e['id'],'op':e['op'],'same_thread_offers':len(matches),'offer_bytes':sum(v['count']*512 for v in matches),'start_observed':e['start_observed']})
    return {'reports':{name:len(groups) for name,groups in streams.items()},'missing_streams':[name for name,groups in streams.items() if not groups], 'streams_not_seen':[name for name,n in seen.items() if not n], 'observed_loss_headers':observed, 'reported_loss_present':any(v for group in observed.values() for v in group.values()), 'full_capture_proven':False, 'loss':loss,'coverage':'sampled_incomplete_if_loss_or_interrupted','stopped_with_unreported_final_interval':stopped,'invalid_cs_events':invalid_cs,'incomplete_reports':incomplete,'cs_start_without_end':len(starts.keys()-ends.keys()),'cs_end_without_start':len(ends.keys()-starts.keys()),'cs_completed':len(completed),'block_offers':len(io),'block_offer_stage':'prequeue_offer_later_rejection_possible','file_range_overlaps':preparation,'block_range_overlaps':block,'temporal_thread_candidates':candidates,'limitations':'Block records are prequeue offers and may later be rejected; all records are bounded samples favoring the first 32 records of each interval, loss counters may shift between adjacent intervals and the final partial interval is discarded on stop; absence of overlap is not evidence of absence; block overlaps compare offers at any time in the same boot; observed loss headers may belong to incomplete reports and are not guaranteed complete; offers are not physical I/O; file offsets and block offsets are not a mapping; cache/asynchronous I/O and drops prevent causal attribution.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('log',type=Path);a=p.parse_args();print(json.dumps(analyze(a.log.read_text(errors='replace')),indent=2))
if __name__=='__main__':main()

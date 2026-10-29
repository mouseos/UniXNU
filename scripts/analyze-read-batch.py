#!/usr/bin/env python3
"""Compare complete first-boot RST snapshots; never infer unobserved I/O or cache state."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics

TAGS={'sig':('c','b','w','e','rc','rn'), 'add':('rb','ac','ab','an','bc','be'),
      'phase':('ic','in','pre','mc','mn','post'), 'vnode':('cross','drop','a','v','o','peer'),
      'prep':('pc','pb','pn','pe','hit'), 'hash':('rc','rb','rn','on','dn','bat')}
TOKEN=re.compile(r'([a-z]+)=([0-9a-f]+)\Z')
BEGIN=re.compile(r'root timing begin pid=(\d+) comm=([^\s]+) ns=(\d+)')
ANCHOR=b'[pmic6392_init] Preloader Start'
REASON=re.compile(rb'(?i)\bBOOT_REASON[ \t]*[:=][ \t]*(0[xX][0-9a-fA-F]+|\d+)(?![0-9A-Za-z])')
REASON_MARK=re.compile(rb'(?i)\bBOOT_REASON\s*[:=]')
PANIC=re.compile(rb'(?i)(?:panic\s*\(|kernel panic)')
EL3=re.compile(rb'(?i)(?:EL3[^\r\n]{0,60}exception|exception[^\r\n]{0,60}EL3)')
STORAGE_FIELDS=('read_calls','read_requested_bytes','read_ns','verify_calls','verify_bytes','verify_ns','read_total_ns','verify_total_ns')
END=re.compile(r'root timing end pid=(\d+) comm=([^\s]+) elapsed_ns=(\d+) error=(-?\d+) kr=(-?\d+)')


def sha(data):return hashlib.sha256(data).hexdigest()


def parse_log(data):
    records={};errors=[];timing=[];active={};ambiguous=set()
    lines=data.split(b'\n')
    for i,part in enumerate(lines):
        raw=part+(b'\n' if i<len(lines)-1 else b'')
        if re.search(rb'(?<!\S)RST ',raw):
            if not raw.endswith(b'\n') or len(re.findall(rb'(?<!\S)RST ',raw))!=1:
                errors.append('truncated_or_concatenated_rst');continue
            if raw[:raw.index(b'RST ')].strip():errors.append('prefixed_rst_record')
            try: line=raw[raw.index(b'RST '):].rstrip(b'\r\n').decode('ascii')
            except UnicodeDecodeError:errors.append('non_ascii_rst');continue
            parts=line.split();
            if len(parts)<3 or parts[0]!='RST' or parts[1] not in TAGS:
                errors.append('unknown_rst_record');continue
            tag=parts[1]; values={}; bad=False
            for token in parts[2:]:
                m=TOKEN.fullmatch(token)
                if not m or m.group(1) in values:bad=True;break
                key,value=m.groups()
                try:values[key]=int(value,16 if tag=='vnode' and key in ('a','o') else 10)
                except ValueError:bad=True;break
                if values[key]>(1<<64)-1:bad=True;break
            if bad or set(values)!=set(('q','p','u')+TAGS[tag]) or values['q'] not in (1,2) or values['p']<=0 or values['u']<=0:
                errors.append('malformed_rst_record');continue
            key=(values['q'],values['p'],values['u']);bucket=records.setdefault(key,{})
            if tag in bucket:errors.append('duplicate_rst_record');continue
            bucket[tag]=values
        line=raw.decode('ascii','replace')
        begin=BEGIN.search(line);end=END.search(line)
        if (begin or end) and not raw.endswith(b'\n'):
            errors.append('truncated_root_timing');continue
        if begin:
            pid=int(begin.group(1));entry={'pid':pid,'comm':begin.group(2),'begin_ns':int(begin.group(3))}
            if pid in active:ambiguous.add(pid)
            else:active[pid]=entry
        if end:
            pid=int(end.group(1));entry=active.pop(pid,None)
            if entry is None or pid in ambiguous or entry['comm']!=end.group(2):
                ambiguous.add(pid);continue
            entry.update(elapsed_ns=int(end.group(3)),error=int(end.group(4)),kr=int(end.group(5)))
            fields=re.findall(r'\b(read_calls|read_requested_bytes|read_ns|verify_calls|verify_bytes|verify_ns|read_total_ns|verify_total_ns)=(\d+)',line[end.end():])
            if len({k for k,v in fields})!=len(fields):errors.append('duplicate_storage_timing_field')
            entry['storage']={k:int(v) for k,v in fields}
            timing.append(entry)
    return records,errors,timing,sorted(active),sorted(ambiguous)


def evidence(condition, label):
    value=condition.get(label)
    return isinstance(value,dict) and value.get('verified') is True and isinstance(value.get('evidence'),str) and bool(value['evidence'].strip())


def capture(directory, variant, manifest, pid, report, condition, expected_sha):
    capture_bytes=(directory/'capture.json').read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}',str(expected_sha)) or sha(capture_bytes)!=expected_sha:raise ValueError('capture digest does not match plan')
    metadata=json.loads(capture_bytes)
    flash_bytes=(directory/'flash-record.json').read_bytes()
    if sha(flash_bytes)!=metadata['flash_record_sha256']:raise ValueError('flash record digest mismatch')
    flash=json.loads(flash_bytes)
    actual_success=flash.get('flash_success') is True and isinstance(flash.get('flash_success_evidence'),str) and bool(flash['flash_success_evidence'].strip())
    completed_offset=flash.get('flash_completed_uart_offset')
    if flash.get('uart_offset')!=metadata['flash_offset'] or flash.get('boot_sha256')!=metadata['flash_boot_sha256'] or actual_success!=metadata.get('flash_success_claimed') or flash.get('flash_success_evidence')!=metadata.get('flash_success_evidence') or completed_offset!=metadata.get('flash_completed_uart_offset'):raise ValueError('flash record inconsistent')
    boots=metadata.get('boots',[])
    if not boots or boots[0].get('index')!=1 or boots[0].get('path')!='boot-1.raw':raise ValueError('missing first boot')
    b=boots[0];raw=(directory/'boot-1.raw').read_bytes();snapshot=(directory/'post-flash.raw').read_bytes()
    if sha(raw)!=b['sha256'] or len(raw)!=b['bytes'] or sha(snapshot)!=metadata['snapshot_sha256']:raise ValueError('capture digest mismatch')
    offset=b['start_offset']-metadata['flash_offset'];end=b['end_offset']-metadata['flash_offset']
    if offset<0 or end<offset or snapshot[offset:end]!=raw or metadata['snapshot_end_offset']-metadata['flash_offset']!=len(snapshot):raise ValueError('capture boundary mismatch')
    first=snapshot.find(ANCHOR);following=snapshot.find(ANCHOR,first+len(ANCHOR)) if first>=0 else -1
    expected_end=following if following>=0 else len(snapshot)
    anchor_after=type(completed_offset) is int and metadata['flash_offset']<=completed_offset<=b['start_offset']
    if anchor_after!=metadata.get('first_anchor_after_flash'):raise ValueError('flash completion boundary inconsistent')
    if first!=offset or end!=expected_end or bool(b.get('closed_by_next_preloader'))!=(following>=0) or not raw.startswith(ANCHOR):
        raise ValueError('first boot anchor or termination inconsistent')
    def events(data,pattern):
        return [m.start() for m in pattern.finditer(data)]
    def event_offsets(entries, data, pattern, absolute):
        return [(x.get('offset'),x.get('absolute_offset')) for x in entries]==[(m.start(),absolute+m.start()) for m in pattern.finditer(data)]
    def reason_values(entries,data,absolute):
        return [(x.get('offset'),x.get('absolute_offset'),x.get('value')) for x in entries]==[(m.start(),absolute+m.start(),int(m.group(1),16 if m.group(1).lower().startswith(b'0x') else 10)) for m in REASON.finditer(data)]
    if b.get('boot_reason_markers')!=len(events(raw,REASON_MARK)):raise ValueError('first boot reason marker count inconsistent')
    if not event_offsets(b.get('panics',[]),raw,PANIC,b['start_offset']) or not event_offsets(b.get('el3_candidates',[]),raw,EL3,b['start_offset']) or not reason_values(b.get('boot_reasons',[]),raw,b['start_offset']):
        raise ValueError('first boot event metadata inconsistent')
    if metadata.get('flash_boot_sha256')!=manifest['variants'][variant]['boot_sha256']:raise ValueError('flash image does not match pair manifest')
    records,errors,timing,open_pids,ambiguous=parse_log(raw)
    matches=[(k,v) for k,v in records.items() if k[0]==report and k[1]==pid]
    reasons=[]
    if metadata.get('flash_success_claimed') is not True or not isinstance(metadata.get('flash_success_evidence'),str) or not metadata['flash_success_evidence'].strip():reasons.append('flash_success_unverified')
    if metadata.get('checkpoint_verified') is True:
        cp_bytes=(directory/'uart-checkpoint.json').read_bytes();cp=json.loads(cp_bytes);tail=(directory/'checkpoint-tail.raw').read_bytes()
        if (sha(cp_bytes)!=metadata.get('checkpoint_sha256') or cp.get('uart_offset')!=metadata['flash_offset'] or
            type(cp.get('source_dev')) is not int or type(cp.get('source_inode')) is not int or cp.get('source_dev')!=metadata.get('source_dev') or cp.get('source_inode')!=metadata.get('source_inode') or
            cp.get('tail_bytes')!=len(tail) or cp.get('tail_start_offset',-1)+len(tail)!=metadata['flash_offset'] or
            cp.get('tail_sha256')!=sha(tail)):
            raise ValueError('UART checkpoint metadata inconsistent')
    else:reasons.append('uart_checkpoint_unverified')
    prefix=metadata.get('pre_preloader')
    prefix_raw=snapshot[:offset]
    if not isinstance(prefix,dict) or prefix.get('start_offset')!=metadata['flash_offset'] or prefix.get('end_offset')!=b['start_offset'] or not event_offsets(prefix.get('panics',[]),prefix_raw,PANIC,metadata['flash_offset']) or not event_offsets(prefix.get('el3_candidates',[]),prefix_raw,EL3,metadata['flash_offset']) or prefix.get('boot_reason_markers')!=len(events(prefix_raw,REASON_MARK)) or not reason_values(prefix.get('boot_reasons',[]),prefix_raw,metadata['flash_offset']):
        raise ValueError('pre-preloader metadata inconsistent')
    if anchor_after and any(metadata['flash_offset']+n>=completed_offset for n in events(prefix_raw,PANIC)+events(prefix_raw,EL3)):
        reasons.append('post_flash_prefix_crash_unattributed')
    if not anchor_after:reasons.append('flash_to_first_anchor_order_unverified')
    if not b.get('closed_by_next_preloader'):reasons.append('first_boot_open')
    if not b.get('boot_reasons') or b.get('boot_reason_markers')!=len(b['boot_reasons']):reasons.append('first_boot_reason_missing_or_unparsed')
    if len({x['value'] for x in b.get('boot_reasons',[])})>1:reasons.append('first_boot_reason_conflict')
    if b.get('panics'):reasons.append('first_boot_panic')
    if b.get('el3_candidates'):reasons.append('first_boot_el3_candidate')
    if errors:reasons.append('malformed_or_duplicate_rst')
    if len(matches)!=1:reasons.append('missing_or_ambiguous_pid_report'); selected=None
    else:
        key,selected=matches[0]
        if set(selected)!=set(TAGS):reasons.append('incomplete_rst_report')
    if not evidence(condition,'uart_integrity'):reasons.append('uart_integrity_unverified')
    if not evidence(condition,'timing_quiescent'):reasons.append('timing_quiescence_unverified')
    if not evidence(condition,'crash_free'):reasons.append('crash_free_unverified')
    if not evidence(condition,'storage_provider'):reasons.append('storage_provider_unverified')
    cache=condition.get('cache',{})
    if not isinstance(cache,dict) or cache.get('state') not in ('cold','warm') or not isinstance(cache.get('evidence'),str) or not cache['evidence'].strip():reasons.append('cache_state_unverified')
    relevant=[t for t in timing if t['pid']==pid]
    if pid in open_pids or pid in ambiguous or len(relevant)!=1:reasons.append('root_timing_missing_or_ambiguous')
    if any(t['comm'] != ('launchd' if pid==1 else condition.get('expected_comm')) for t in relevant):reasons.append('process_name_unverified_or_mismatch')
    if any(t['error'] or t['kr'] for t in relevant):reasons.append('root_timing_failed')
    if any(set(t['storage'])!=set(STORAGE_FIELDS) for t in relevant):reasons.append('storage_timing_fields_missing')
    if selected and set(selected)==set(TAGS):
        h=selected['hash'];p=selected['prep'];sig=selected['sig'];add=selected['add']
        if sig['e'] or add['be'] or p['pe']:reasons.append('signature_or_preparation_error')
        if p['hit']:reasons.append('coalescing_reuse_observed')
        if not p['pc'] or not h['rb'] or not p['pn']:reasons.append('no_completed_preparation')
        if h['rb']!=p['pb']:reasons.append('requested_bytes_not_equal')
        if variant=='baseline' and h['bat']!=0:reasons.append('baseline_batch_selected')
        if variant=='batch' and (h['bat']<=0 or h['bat']!=p['pc']):reasons.append('batch_selection_not_complete')
    else:key=None
    arg_lines=[line.split(b'boot-args =',1)[1].strip().decode('ascii','replace') for line in raw.split(b'\n') if b'boot-args =' in line]
    if len(arg_lines)!=1 or arg_lines[0]!=manifest['variants'][variant]['kernel_args']:
        reasons.append('boot_arguments_missing_or_mismatch')
    next_boot=boots[1] if len(boots)>1 else None
    if following>=0:
        third=snapshot.find(ANCHOR,following+len(ANCHOR)); next_end=third if third>=0 else len(snapshot)
        second=snapshot[following:next_end]
        if (next_boot is None or next_boot.get('index')!=2 or next_boot.get('start_offset')!=metadata['flash_offset']+following or
            next_boot.get('end_offset')!=metadata['flash_offset']+next_end or next_boot.get('sha256')!=sha(second) or
            next_boot.get('closed_by_next_preloader')!=(third>=0) or
            next_boot.get('boot_reason_markers')!=len(events(second,REASON_MARK)) or
            not event_offsets(next_boot.get('panics',[]),second,PANIC,next_boot['start_offset']) or
            not event_offsets(next_boot.get('el3_candidates',[]),second,EL3,next_boot['start_offset']) or
            not reason_values(next_boot.get('boot_reasons',[]),second,next_boot['start_offset']) or
            b.get('subsequent_boot_reason_candidate')!=(next_boot.get('boot_reasons') or [None])[0]):
            raise ValueError('following boot metadata inconsistent')
        if next_boot.get('panics'):reasons.append('following_boot_panic')
        if next_boot.get('el3_candidates'):reasons.append('following_boot_el3_candidate')
        if len({x['value'] for x in next_boot.get('boot_reasons',[])})>1:reasons.append('following_boot_reason_conflict')
        if not next_boot.get('boot_reasons') or next_boot.get('boot_reason_markers')!=len(next_boot['boot_reasons']):reasons.append('following_boot_reason_missing_or_unparsed')
        elif next_boot['boot_reasons'][0]['value']==9:reasons.append('following_watchdog_reason_observed')
        reset=condition.get('following_reset',{})
        if (not isinstance(reset,dict) or type(reset.get('expected_reason')) is not int or
            not next_boot.get('boot_reasons') or reset.get('expected_reason')!=next_boot['boot_reasons'][0]['value'] or
            not isinstance(reset.get('evidence'),str) or not reset['evidence'].strip()):reasons.append('following_reset_unverified')
    elif next_boot is not None:
        raise ValueError('unexpected following boot')
    return {'variant':variant,'boot_sha256':metadata['flash_boot_sha256'],'first_boot_sha256':b['sha256'],
            'capture_sha256':sha(capture_bytes),'flash_record_sha256':metadata['flash_record_sha256'],'snapshot_sha256':metadata['snapshot_sha256'],
            'pre_preloader':prefix,
            'first_boot':{'start_offset':b['start_offset'],'end_offset':b['end_offset'],'closed_by_next_preloader':b['closed_by_next_preloader'],
                          'boot_reasons':b.get('boot_reasons',[]),'panics':b.get('panics',[]),'el3_candidates':b.get('el3_candidates',[]),
                          'subsequent_boot_reason_candidate':b.get('subsequent_boot_reason_candidate')},
            'following_boot':None if next_boot is None else {'boot_reasons':next_boot.get('boot_reasons',[]),'panics':next_boot.get('panics',[]),'el3_candidates':next_boot.get('el3_candidates',[]),'closed_by_next_preloader':next_boot.get('closed_by_next_preloader',False)},
            'report_key':list(key) if key else None,'records':selected,'rst_errors':errors,'root_timing':relevant,
            'root_timing_open_pids':open_pids,'root_timing_ambiguous_pids':ambiguous,'conditions':condition,'reasons':reasons,
            'limits':['RST snapshots are cumulative, non-transactional and may include in-flight work.',
                      'UART and timing attestations are external assertions, not proven by this parser.',
                      'read bytes are requested bytes, not physical I/O; cache state cannot be inferred.',
                      'No per-call coalescing wait is measured; pn is aggregate wall time, not CPU time.']}


def analyze(plan, manifest, base):
    if not isinstance(plan.get('pairs'),list) or not plan['pairs']:raise ValueError('at least one pair required')
    if (manifest.get('source_commit')!='e8f5385e4cee02bb15efa2fb97c20bb59b98d72f' or manifest.get('device_commit')!='8fde8ba87486338342f3be528823cb46394f2c5b' or manifest.get('uefi_commit')!='d3d4f28a89b29553ede7d7523c6af86d7e2459e8'):
        raise ValueError('pair manifest source mismatch')
    hashes=[manifest['variants'][v]['boot_sha256'] for v in ('baseline','batch')]
    if hashes[0]==hashes[1] or any(not isinstance(h,str) or not re.fullmatch(r'[0-9a-f]{64}',h) for h in hashes):raise ValueError('invalid pair boot hashes')
    if manifest['variants']['batch']['kernel_args'] != manifest['variants']['baseline']['kernel_args']+' native-cs-read-batch=1':raise ValueError('manifest profiles differ unexpectedly')
    pairs=[];ratios=[];seen_boots=set();previous_order=None
    for index,pair in enumerate(plan['pairs']):
        pid=pair.get('pid',1);report=pair.get('report',1)
        if type(pid)!=int or pid<=0 or type(report)!=int or report not in (1,2):raise ValueError('invalid pid/report')
        results={}
        for variant in ('baseline','batch'):
            info=pair[variant];directory=(base/Path(info['capture'])).resolve()
            results[variant]=capture(directory,variant,manifest,pid,report,info.get('conditions',{}),info.get('capture_sha256'))
        reasons=[variant+':'+reason for variant in results for reason in results[variant]['reasons']]
        order=pair.get('order');order_evidence=pair.get('order_evidence')
        if order not in ('baseline-first','batch-first') or not isinstance(order_evidence,str) or not order_evidence.strip():reasons.append('run_order_unverified')
        elif previous_order==order:reasons.append('run_order_not_alternating')
        if order in ('baseline-first','batch-first'):previous_order=order
        ids=[results[v]['first_boot_sha256'] for v in ('baseline','batch')]
        if len(set(ids))!=2 or any(value in seen_boots for value in ids):reasons.append('reused_or_identical_boot_capture')
        seen_boots.update(ids)
        a=results['baseline']['records'];b=results['batch']['records']
        if a and b and set(a)==set(TAGS) and set(b)==set(TAGS):
            for tag,key in (('hash','rb'),('prep','pb'),('prep','pc'),('sig','c')):
                if a[tag][key]!=b[tag][key]:reasons.append('different_'+tag+'_'+key)
            ac=results['baseline']['conditions'].get('cache',{});bc=results['batch']['conditions'].get('cache',{})
            if not isinstance(ac,dict) or not isinstance(bc,dict) or ac.get('state')!=bc.get('state'):reasons.append('different_cache_state')
            ratio=b['prep']['pn']/a['prep']['pn'] if a['prep']['pn'] else None
        else:ratio=None
        if not reasons and ratio is not None:ratios.append(ratio)
        pairs.append({'index':index+1,'pid':pid,'report':report,'order':order,'order_evidence':order_evidence,'runs':results,'conditional_eligible':not reasons,
                      'reasons':reasons,'prepare_time_ratio_batch_over_baseline':ratio})
    eligible=len(ratios)>=3
    return {'schema':1,'pairs':pairs,'eligible_pair_count':len(ratios),'minimum_pairs':3,
            'median_ratio':statistics.median(ratios) if ratios else None,'maximum_ratio':max(ratios) if ratios else None,
            'meets_predeclared_threshold':None if not eligible else statistics.median(ratios)<=0.95 and max(ratios)<=1.10,
            'conclusion':'conditional_exploratory_only',
            'limitations':['Fresh ADT random seeds differ; causal single-variable equivalence is not proven.',
                           'Metrics rely on attestations and bounded non-atomic RST snapshots; no actual media I/O or latency causality is established.',
                           'Read-batch is a request-size change, and the collector does not operate hardware.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);a=p.parse_args()
    plan_bytes=a.plan.read_bytes();manifest_bytes=a.manifest.read_bytes()
    plan=json.loads(plan_bytes);manifest=json.loads(manifest_bytes)
    result=analyze(plan,manifest,a.plan.resolve().parent)
    result['plan_sha256']=sha(plan_bytes);result['manifest_sha256']=sha(manifest_bytes)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,TypeError,AttributeError) as e:raise SystemExit(str(e))

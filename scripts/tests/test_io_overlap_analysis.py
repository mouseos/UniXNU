#!/usr/bin/env python3
import importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'analyze-io-overlap.py';spec=importlib.util.spec_from_file_location('overlap',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
text='''CS overlap begin seq=1 count=4 full=2 busy=1 keys_full=0
CS overlap event seq=1 id=1 op=1 pid=1 tid=11 start=10 end=0 base=0 bytes=0 reads=0 error=0
CS overlap event seq=1 id=1 op=2 pid=2 tid=22 start=12 end=0 base=4096 bytes=0 reads=0 error=0
CS overlap event seq=1 id=1 op=1 pid=1 tid=11 start=10 end=20 base=0 bytes=16384 reads=1 error=0
CS overlap event seq=1 id=1 op=2 pid=2 tid=22 start=12 end=25 base=4096 bytes=16384 reads=1 error=0
CS overlap end seq=1 count=4
NativeMsdc overlap begin seq=1 count=2 full=9 contention=0 unit=512 prequeue=1
NativeMsdc overlap event seq=1 index=0 ns=15 pid=1 tid=11 window=1 block=100 count=32
NativeMsdc overlap event seq=1 index=1 ns=16 pid=2 tid=22 window=1 block=116 count=32
NativeMsdc overlap end seq=1
'''
r=m.analyze(text);assert r['file_range_overlaps'][0]['bytes']==12288 and r['file_range_overlaps'][0]['time_overlap'];assert r['block_range_overlaps'][0]['sectors']==16 and r['block_range_overlaps'][0]['delta_ns']==1;assert r['temporal_thread_candidates'][0]['same_thread_offers']==1;assert r['block_offer_stage']=='prequeue_offer_later_rejection_possible';assert r['loss']['NativeMsdc']['full']==9 and r['loss']['CS']['full']==2
partial=m.analyze(text.replace('NativeMsdc overlap end seq=1',''));assert partial['incomplete_reports']==1 and partial['observed_loss_headers']['NativeMsdc']['full']==9 and partial['reported_loss_present'] and 'NativeMsdc' not in partial['streams_not_seen']
assert m.analyze(text.replace('window=1 block=100','window=1 missing=100'))['incomplete_reports']==1
assert m.analyze(text.replace('prequeue=1','prequeue=0'))['incomplete_reports']==1
assert m.analyze(text.replace(' prequeue=1',''))['block_offers']==2 # compatible older records have identical offer semantics
assert m.analyze(text.replace('unit=512','unit=4096'))['incomplete_reports']==1
assert m.analyze(text.replace('CS overlap end seq=1 count=4','CS overlap event seq=1 id=1 op=1 pid=1 tid=11 start=10 end=20 base=0 bytes=16384 reads=1 error=0\nCS overlap end seq=1 count=5').replace('seq=1 count=4 full=', 'seq=1 count=5 full='))['invalid_cs_events']==1
assert 'busy' not in r['loss']['NativeMsdc'] and r['coverage']=='sampled_incomplete_if_loss_or_interrupted'
assert m.analyze(text+'NativeMsdc overlap stopped final_interval_unreported=1\n')['stopped_with_unreported_final_interval']==1
assert m.analyze('')['missing_streams']==['CS','NativeMsdc'] and m.analyze('')['streams_not_seen']==['CS','NativeMsdc']
assert not r['full_capture_proven']
try:m.parse(text+text)
except ValueError:pass
else:raise AssertionError('must refuse multiple boots')
print('PASS overlap parser: complete groups, partial groups, losses, duplicate boot refusal, range intersections and candidate correlation')

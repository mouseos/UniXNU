#!/usr/bin/env python3
import hashlib,importlib.util,json,os,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
A=load('analysis',ROOT/'scripts/analyze-read-batch.py')
DEVICE=Path(os.environ.get('A04BR3_DEVICE_SOURCE',ROOT.parent/'UniXNU-a04br3-read-batch-analysis'))
C=load('capture',DEVICE/'scripts/collect-read-batch-uart.py')


def logs(batch,marker,rb=32768,pc=2,bat=None,panic=False,truncate=False,next_reason=4,following_panic=False,later_panic=False,batch_pn=80,extra=b''):
 if bat is None:bat=pc if batch else 0
 tags=['sig q=1 p=1 u=101 c=2 b=20 w=200 e=0 rc=2 rn=10',
       'add q=1 p=1 u=101 rb=20 ac=2 ab=20 an=180 bc=2 be=0',
       'phase q=1 p=1 u=101 ic=2 in=2 pre=2 mc=2 mn=2 post=100',
       'vnode q=1 p=1 u=101 cross=0 drop=0 a=0 v=0 o=0 peer=0',
       f'prep q=1 p=1 u=101 pc={pc} pb={rb} pn={batch_pn if batch else 100} pe=0 hit=0',
       f'hash q=1 p=1 u=101 rc={1 if batch else 2} rb={rb} rn=10 on=10 dn=10 bat={bat}']
 body=C.ANCHOR+b'\nBOOT_REASON: 4\n'+marker.encode()+b'\n'+('boot-args = x'+(' native-cs-read-batch=1' if batch else '')+'\n').encode()+b''.join(('RST '+x+'\n').encode() for x in tags)
 body+=b'root timing begin pid=1 comm=launchd ns=1000 files=1 mappings=1\nroot timing end pid=1 comm=launchd elapsed_ns=200 error=0 kr=0 read_calls=2 read_requested_bytes=32768 read_ns=3 verify_calls=2 verify_bytes=32768 verify_ns=4 read_total_ns=3 verify_total_ns=4\n'
 if panic:body+=b'panic(cpu 1): first\n'
 body+=extra
 if truncate:body+=b'RST hash q=1 p=1'
 return body+C.ANCHOR+f'\nBOOT_REASON={next_reason}\n'.encode()+(b'kernel panic following\n' if following_panic else b'')+(C.ANCHOR+b'\nBOOT_REASON=4\npanic: third\n' if later_panic else b'')

class Analysis(unittest.TestCase):
 def make(self,root,variant,marker,**opts):
  uart=root/(marker+'.uart');uart.write_bytes(b'old-log\n');cp=root/(marker+'.checkpoint');C.checkpoint(uart,cp);uart.write_bytes(b'old-log\n'+logs(variant=='batch',marker,**opts));f=root/(marker+'.json')
  f.write_text(json.dumps({'uart_offset':8,'boot_sha256':('b' if variant=='batch' else 'a')*64,'flash_success':True,'flash_success_evidence':'successful flash log','flash_completed_uart_offset':8,'uart_checkpoint':str(cp)}));out=root/marker
  C.collect(uart,f,out);return str(out)
 def info(self,path,conditions):
  return {'capture':path,'capture_sha256':hashlib.sha256((Path(path)/'capture.json').read_bytes()).hexdigest(),'conditions':conditions}
 def test_three_pairs_and_cache_gating(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);conditions={'uart_integrity':{'verified':True,'evidence':'collector integrity record'},'timing_quiescent':{'verified':True,'evidence':'independent trace'},'crash_free':{'verified':True,'evidence':'review'},'storage_provider':{'verified':True,'evidence':'provider'},'following_reset':{'expected_reason':4,'evidence':'controlled reset'},'cache':{'state':'warm','evidence':'controlled procedure'}}
   pairs=[{**{v:self.info(self.make(p,v,f'{v}{i}'),conditions) for v in ('baseline','batch')},'order':'baseline-first' if i%2==0 else 'batch-first','order_evidence':'flash log'} for i in range(3)]
   manifest={'source_commit':'e8f5385e4cee02bb15efa2fb97c20bb59b98d72f','device_commit':'8fde8ba87486338342f3be528823cb46394f2c5b','uefi_commit':'d3d4f28a89b29553ede7d7523c6af86d7e2459e8','variants':{'baseline':{'boot_sha256':'a'*64,'kernel_args':'x'},'batch':{'boot_sha256':'b'*64,'kernel_args':'x native-cs-read-batch=1'}}}
   result=A.analyze({'pairs':pairs},manifest,p);self.assertEqual(result['eligible_pair_count'],3);self.assertTrue(result['meets_threshold']);self.assertEqual(result['conclusion'],'conditional_exploratory_only')
   old=pairs[2]['batch'];pairs[2]['batch']=self.info(self.make(p,'batch','slow',batch_pn=120),conditions);result=A.analyze({'pairs':pairs},manifest,p);self.assertFalse(result['meets_threshold']);pairs[2]['batch']=old
   extra=[{**{v:self.info(self.make(p,v,f'extra{v}{i}'),conditions) for v in ('baseline','batch')},'order':'batch-first' if i==0 else 'baseline-first','order_evidence':'flash log'} for i in range(2)]
   for pair in (pairs[1],extra[0]):pair['batch']['conditions']={**conditions,'cache':{'state':'unknown'}}
   order_result=A.analyze({'pairs':pairs+extra},manifest,p);self.assertEqual(order_result['eligible_pair_count'],1);self.assertIn('eligible_run_order_not_alternating',order_result['pairs'][2]['reasons'])
   pairs[1]['batch']['conditions']=conditions
   pairs[0]['batch']['conditions']={**conditions,'cache':{'state':'unknown'}};r=A.analyze({'pairs':pairs},manifest,p);self.assertEqual(r['eligible_pair_count'],2);self.assertIsNone(r['meets_threshold']);self.assertIn('batch:cache_state_unverified',r['pairs'][0]['reasons'])
   pairs[0]['batch']['conditions']={**conditions,'crash_free':{'verified':False},'storage_provider':{}};r=A.analyze({'pairs':pairs},manifest,p);self.assertIn('batch:crash_free_unverified',r['pairs'][0]['reasons']);self.assertIn('batch:storage_provider_unverified',r['pairs'][0]['reasons'])
   pairs[1]['order']='baseline-first';r=A.analyze({'pairs':pairs},manifest,p);self.assertIn('run_order_not_alternating',r['pairs'][1]['reasons'])
   pairs[1]['baseline']=pairs[0]['baseline'];r=A.analyze({'pairs':pairs},manifest,p);self.assertIn('reused_or_identical_boot_capture',r['pairs'][1]['reasons'])
 def test_mismatch_panic_reboot_and_tamper(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);ca=self.make(p,'baseline','a',panic=True,next_reason=9,later_panic=True);cb=self.make(p,'batch','b',rb=16384,bat=1,following_panic=True)
   condition={'uart_integrity':{'verified':True,'evidence':'x'},'timing_quiescent':{'verified':True,'evidence':'x'},'crash_free':{'verified':True,'evidence':'x'},'storage_provider':{'verified':True,'evidence':'x'},'following_reset':{'expected_reason':4,'evidence':'x'},'cache':{'state':'warm','evidence':'x'}}
   manifest={'source_commit':'e8f5385e4cee02bb15efa2fb97c20bb59b98d72f','device_commit':'8fde8ba87486338342f3be528823cb46394f2c5b','uefi_commit':'d3d4f28a89b29553ede7d7523c6af86d7e2459e8','variants':{'baseline':{'boot_sha256':'a'*64,'kernel_args':'x'},'batch':{'boot_sha256':'b'*64,'kernel_args':'x native-cs-read-batch=1'}}}
   plan={'pairs':[{'baseline':self.info(ca,condition),'batch':self.info(cb,condition),'order':'baseline-first','order_evidence':'flash log'}]};r=A.analyze(plan,manifest,p)['pairs'][0]
   self.assertIn('baseline:first_boot_panic',r['reasons']);self.assertIn('baseline:following_watchdog_reason_observed',r['reasons']);self.assertIn('batch:following_boot_panic',r['reasons']);self.assertFalse(r['runs']['batch']['first_boot']['panics']);self.assertIn('different_hash_rb',r['reasons']);self.assertIn('batch:batch_selection_not_complete',r['reasons']);self.assertEqual(r['runs']['baseline']['following_boot']['boot_reasons'][0]['value'],9);self.assertEqual(r['runs']['baseline']['following_boot']['panics'],[]);self.assertEqual(len(r['runs']['baseline']['later_boots'][0]['panics']),1)
   cpath=Path(ca)/'capture.json';c=json.loads(cpath.read_text());c['boots'][0]['panics']=[];cpath.write_text(json.dumps(c))
   with self.assertRaises(ValueError):A.analyze(plan,manifest,p)
   plan['pairs'][0]['baseline']['capture_sha256']=hashlib.sha256(cpath.read_bytes()).hexdigest()
   with self.assertRaisesRegex(ValueError,'event metadata inconsistent'):A.analyze(plan,manifest,p)
 def test_crossing_anchor_is_ineligible(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);u=p/'uart';u.write_bytes(b'old'+C.ANCHOR[:10]);cp=p/'cp';C.checkpoint(u,cp);offset=u.stat().st_size
   u.write_bytes(b'old'+C.ANCHOR+logs(False,'second'));f=p/'f'
   f.write_text(json.dumps({'uart_offset':offset,'boot_sha256':'a'*64,'uart_checkpoint':str(cp),'flash_completed_uart_offset':offset}))
   out=p/'capture';C.collect(u,f,out);manifest={'variants':{'baseline':{'boot_sha256':'a'*64,'kernel_args':'x'}}}
   r=A.capture(out,'baseline',manifest,1,1,{},hashlib.sha256((out/'capture.json').read_bytes()).hexdigest())
   self.assertIn('flash_offset_crosses_preloader_anchor',r['reasons'])
 def test_other_process_incomplete_diagnostics_are_ineligible(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);manifest={'variants':{'baseline':{'boot_sha256':'a'*64,'kernel_args':'x'}}}
   for i,(extra,expected) in enumerate(((b'RST sig q=2 p=2 u=202 c=2 b=20 w=200 e=0 rc=2 rn=10\n','incomplete_rst_group'),(b'root timing begin pid=2 comm=x ns=1 files=1 mappings=1\n','unfinished_or_ambiguous_root_timing'),(b'garbageRST sig q=1 p=1 u=101 c=2 b=20 w=200 e=0 rc=2 rn=10\n','malformed_or_duplicate_diagnostics'))):
    out=Path(self.make(p,'baseline',f'bad{i}',extra=extra));r=A.capture(out,'baseline',manifest,1,1,{},hashlib.sha256((out/'capture.json').read_bytes()).hexdigest());self.assertIn(expected,r['reasons'])
 def test_json_and_event_truncation(self):
  with self.assertRaisesRegex(ValueError,'duplicate JSON'):A.strict_json(b'{\"a\":1,\"a\":2}')
  self.assertTrue(A.has_truncated_events({'boots':[{'panics':[{'truncated':True}]}]}))
 def test_malformed_and_overlapping_begin(self):
  raw=logs(False,'bad',truncate=True).split(C.ANCHOR)[1];_,errors,_,_,_=A.parse_log(raw);self.assertTrue(errors)
  good=logs(False,'normal').split(C.ANCHOR)[1]
  begin=b'root timing begin pid=1 comm=launchd ns=1 files=1 mappings=1\n'
  end=b'root timing end pid=1 comm=launchd elapsed_ns=2 error=0 kr=0 read_calls=2 read_requested_bytes=32768 read_ns=3 verify_calls=2 verify_bytes=32768 verify_ns=4 read_total_ns=3 verify_total_ns=4\n'
  _,_,timing,_,amb=A.parse_log(begin+begin+end);self.assertEqual(timing,[]);self.assertEqual(amb,[1])
  for raw in (good+b'root timing begin pid=X comm=launchd ns=1 files=1 mappings=1\n',good.replace(b'read_calls=2',b'read_calls=2CORRUPT'),begin+end.rstrip(b'\n')+end,begin+b'root timing end pid=1 comm=launchd elapsed_ns=2 error=0 kr=0\n'):
   _,errors,_,_,_=A.parse_log(raw);self.assertIn('malformed_root_timing',errors)
  _,errors,_,_,_=A.parse_log(b'FIRST report\n');self.assertEqual(errors,[])
  _,errors,_,_,_=A.parse_log(b'garbage RST sig q=1 p=1 u=1 c=2 b=20 w=200 e=0 rc=2 rn=10\n');self.assertIn('prefixed_rst_record',errors)

if __name__=='__main__':unittest.main()

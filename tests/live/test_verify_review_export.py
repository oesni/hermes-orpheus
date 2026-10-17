"""Synthetic verifier controls; these are not live execution evidence."""
import copy
import json
import runpy
import unittest
from pathlib import Path

verify=runpy.run_path(str(Path(__file__).with_name('verify_review_export.py')))['verify']


def session(bridge=False):
    messages=[]
    def exchange(name,args,result):
        call_id='call-'+str(len(messages))
        if bridge:
            args={'calls':[{'name':name,'arguments':args}]}
            name='tool_call'
        messages.append({'role':'assistant','tool_calls':[{'id':call_id,'function':{'name':name,'arguments':json.dumps(args)}}]})
        messages.append({'role':'tool','tool_call_id':call_id,'content':json.dumps(result)})
    exchange('orpheus_presets',{}, {'presets':[{'id':'reviewer','execution_capability':'compatible','capability_reasons':[]}] })
    exchange('orpheus_spawn',{'preset_id':'reviewer','task':'Review discounted_total'}, {'request_id':'test-request','state':'running'})
    exchange('orpheus_status',{'request_id':'test-request'}, {'request_id':'test-request','state':'SUCCEEDED','result':{'ready':True,'summary':json.dumps({'function':'discounted_total','input_cents':10000,'actual_cents':10000,'expected_cents':9000,'explanation':'Inclusive threshold excludes exactly the boundary.'})}})
    return {'id':'synthetic','messages':messages}


class VerifyTests(unittest.TestCase):
    def test_direct_and_deferred_tool_calls_require_linked_results(self):
        for bridge in (False,True):
            with self.subTest(bridge=bridge):
                evidence=session(bridge)
                self.assertTrue(verify(evidence)['verified'])
                evidence['messages'][-1]['tool_call_id']='unrelated'
                with self.assertRaisesRegex(ValueError,'missing_linked'): verify(evidence)

    def test_self_report_alone_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,'missing_linked'):
            verify({'messages':[{'role':'assistant','content':'Child succeeded and found 10000 should be 9000.'}]})

    def test_bridge_batch_does_not_guess_output_association(self):
        evidence=session(True)
        function=evidence['messages'][0]['tool_calls'][0]['function']
        args=json.loads(function['arguments']); args['calls']*=2
        function['arguments']=json.dumps(args)
        with self.assertRaisesRegex(ValueError,'bridge_shape'): verify(evidence)

    def test_alternative_delegation_in_bridge_is_rejected(self):
        evidence=session(True)
        function=evidence['messages'][2]['tool_calls'][0]['function']
        args=json.loads(function['arguments']);args['calls'][0]['name']='delegate_task'
        function['arguments']=json.dumps(args)
        with self.assertRaisesRegex(ValueError,'alternative_delegation'): verify(evidence)

    def test_correct_finding_under_wrong_request_is_rejected(self):
        evidence=session(True)
        result=json.loads(evidence['messages'][-1]['content']); result['request_id']='other-request'
        evidence['messages'][-1]['content']=json.dumps(result)
        with self.assertRaisesRegex(ValueError,'request_identity'): verify(evidence)

    def test_malformed_collection_items_fail_closed(self):
        for malformed in (42, "not-an-object", None):
            with self.subTest(item=malformed):
                evidence=session()
                evidence['messages'][0]['tool_calls']=[malformed]
                with self.assertRaisesRegex(ValueError,'invalid_tool_call'): verify(evidence)
                evidence=session()
                evidence['messages'][1]['content']=json.dumps({'presets':[malformed]})
                with self.assertRaisesRegex(ValueError,'invalid_presets'): verify(evidence)

    def test_unverified_or_unreasoned_reviewer_cannot_pass_discovery(self):
        for capability,reasons in [('unverified',[]),('compatible',['unsupported_effort']),('compatible',None)]:
            with self.subTest(capability=capability,reasons=reasons):
                evidence=session()
                evidence['messages'][1]['content']=json.dumps({'presets':[{'id':'reviewer','execution_capability':capability,'capability_reasons':reasons}]})
                with self.assertRaisesRegex(ValueError,'reviewer_not_compatible'): verify(evidence)

    def test_cli_malformed_presets_returns_json_failure_without_traceback(self):
        import subprocess
        import sys
        import tempfile
        evidence=session()
        evidence['messages'][1]['content']=json.dumps({'presets':[42]})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'export.jsonl'
            path.write_text(json.dumps(evidence)+'\n')
            completed=subprocess.run([sys.executable,str(Path(__file__).with_name('verify_review_export.py')),str(path),'--session-id','synthetic'],capture_output=True,text=True)
        self.assertEqual(completed.returncode,1)
        self.assertEqual(json.loads(completed.stdout),{'verified':False,'error':'invalid_presets'})
        self.assertEqual(completed.stderr,'')

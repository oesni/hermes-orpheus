import tempfile
import unittest
from orpheus.host import SubagentAdapter, HostError


class Lifecycle:
    def __init__(self):
        self.calls=[]
        self.owner=True
        self.state='RUNNING'
    def launch(self,request):
        self.calls.append(request)
        return {'model': request['model'],'provider':request['provider'],'capability':'secret-handle'}
    def status(self,handle):
        return {'state':self.state if self.owner else 'UNKNOWN','diagnostic':None if self.owner else 'UNKNOWN_HANDLE','handle':handle}
    def result(self,handle):
        return {'ready':self.state=='SUCCEEDED','summary':'result','handle':handle}
    def cancel(self,handle,reason):
        return {'accepted':True,'state':'CANCEL_REQUESTED'}


class ExtendedLifecycle(Lifecycle):
    def capabilities(self):
        return {'reasoning_effort':'per-launch-v1','disable_fallback':'per-launch-v1'}


class HostTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings={'provider':'test','model':'small'}
    def adapter(self,host=None,settings=None,fallback=True):
        host=host or Lifecycle()
        adapter=SubagentAdapter(host,self.directory.name,{'fallback_disabled':fallback,'verified_settings':[settings or self.settings]})
        self.addCleanup(adapter.close)
        return adapter,host
    def test_baseline_effort_fails_before_launch(self):
        selected={**self.settings,'effort':'high'}
        adapter,host=self.adapter(settings=selected)
        with self.assertRaisesRegex(HostError,'per-launch'): adapter.launch({'resolved':selected},'task')
        self.assertEqual(host.calls,[])
    def test_unverified_tuple_and_fallback_fail_closed(self):
        adapter,host=self.adapter(fallback=False)
        with self.assertRaisesRegex(HostError,'fallback'): adapter.launch({'resolved':self.settings},'task')
        adapter.deployment['fallback_disabled']=True
        with self.assertRaisesRegex(HostError,'Exact'): adapter.launch({'resolved':{**self.settings,'model':'other'}},'task')
        self.assertEqual(host.calls,[])
    def test_extension_sends_per_launch_effort_and_fallback(self):
        selected={**self.settings,'effort':'high'}
        adapter,host=self.adapter(ExtendedLifecycle(),selected,fallback=False)
        result=adapter.launch({'resolved':selected},'task',{'fact':'explicit'})
        self.assertEqual(host.calls[0]['reasoning_effort'],'high')
        self.assertTrue(host.calls[0]['disable_fallback'])
        self.assertIsNone(result['observed'])
        self.assertNotIn('capability',str(result))
    def test_native_ownership_required_for_status_and_cancel(self):
        adapter,host=self.adapter()
        launched=adapter.launch({'resolved':self.settings},'task')
        host.owner=False
        with self.assertRaises(HostError): adapter.status(launched['request_id'])
        with self.assertRaises(HostError): adapter.cancel(launched['request_id'])
    def test_cancel_ack_does_not_claim_terminal(self):
        adapter,host=self.adapter()
        launched=adapter.launch({'resolved':self.settings},'task')
        self.assertEqual(adapter.cancel(launched['request_id'])['state'],'cancellation_pending')
    def test_launch_exception_is_unknown_never_retry(self):
        class Broken(Lifecycle):
            def launch(self,request):
                super().launch(request)
                raise RuntimeError('credential must never leak')
        adapter,host=self.adapter(Broken())
        outcome=adapter.launch({'resolved':self.settings},'task')
        self.assertEqual(outcome['state'],'unknown')
        self.assertNotIn('credential',str(outcome))
        self.assertEqual(len(host.calls),1)
    def test_result_omits_native_capability(self):
        adapter,host=self.adapter()
        launched=adapter.launch({'resolved':self.settings},'task')
        host.state='SUCCEEDED'
        outcome=adapter.status(launched['request_id'])
        self.assertNotIn('secret-handle',str(outcome))
        self.assertEqual(outcome['result_availability'],'available')

class RetentionPrivacyTests(unittest.TestCase):
    def test_existing_public_state_directory_is_tightened(self):
        import os
        import stat
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            path.chmod(0o755)
            for suffix in ('-wal','-shm','-journal'):
                (path/('subagents.sqlite'+suffix)).touch(mode=0o644)
            adapter=SubagentAdapter(Lifecycle(),path)
            try:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o700)
                for candidate in path.glob('subagents.sqlite*'):
                    self.assertEqual(stat.S_IMODE(candidate.stat().st_mode),0o600)
            finally: adapter.close()

    def test_retention_erases_terminal_rows_and_live_sensitive_inputs(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            adapter=SubagentAdapter(Lifecycle(),directory)
            try:
                for name,state in [('done','SUCCEEDED'),('ambiguous','unknown')]:
                    adapter.db.execute('INSERT INTO children VALUES (?,?,?,?,?,?,?)',(name,'sensitive-selection',state,'opaque-handle','sensitive-result',0,1))
                adapter.db.commit()
                self.assertEqual(adapter.expire_records(now=2),2)
                self.assertIsNone(adapter.db.execute("SELECT id FROM children WHERE id='done'").fetchone())
                self.assertEqual(adapter.db.execute("SELECT selection,result,handle,expires_at FROM children WHERE id='ambiguous'").fetchone(),('{}',None,'opaque-handle',None))
                query='SELECT id,state FROM children WHERE expires_at IS NOT NULL AND expires_at <= ? ORDER BY expires_at LIMIT 256'
                plan=adapter.db.execute('EXPLAIN QUERY PLAN '+query,(2,)).fetchall()
                self.assertIn('child_expiry',str(plan))
            finally: adapter.close()

    def test_native_redaction_uses_explicit_global_literals(self):
        class Sensitive(Lifecycle):
            def result(self,handle): return {'ready':True,'summary':'secret value','error_message':'secret'}
        with tempfile.TemporaryDirectory() as directory:
            host=Sensitive()
            adapter=SubagentAdapter(host,directory,{'fallback_disabled':True,'verified_settings':[{'provider':'test','model':'small'}]},redact_literals=['secret'])
            try:
                launched=adapter.launch({'resolved':{'provider':'test','model':'small'}},'task')
                outcome=adapter.status(launched['request_id'])
                self.assertEqual(outcome['result']['summary'],'[REDACTED] value')
                self.assertEqual(outcome['result']['error_message'],'[REDACTED]')
            finally: adapter.close()

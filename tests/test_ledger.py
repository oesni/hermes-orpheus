import time
import pytest
from orpheus.ledger import Ledger, Conflict


def test_replay_and_signed_conflict(tmp_path):
    path=tmp_path/'ledger.db'; one=Ledger(path); two=Ledger(path)
    first,new=one.reserve('scope','digest',{'target':'a'},event_id='signed')
    assert new
    same,new=two.reserve('scope','digest',{'target':'b'})
    assert not new and same['id']==first['id'] and same['target']=='a'
    with pytest.raises(Conflict): two.reserve('scope','different',{},event_id='signed')
    one.close(); two.close()
    restarted=Ledger(path)
    assert not restarted.reserve('scope','digest',{})[1]
    restarted.close()


def test_cancel_fences_late_selection_and_expired_owner(tmp_path):
    ledger=Ledger(tmp_path/'ledger.db'); row,_=ledger.reserve('s','d',{})
    ledger.cancel(row['id'])
    assert not ledger.change(row['id'],1,('resolving',),'selected')
    assert ledger.get(row['id'])['state']=='cancelled'
    row,_=ledger.reserve('s','d2',{})
    ledger.db.execute('UPDATE runs SET lease=0 WHERE id=?',(row['id'],))
    assert not ledger.change(row['id'],1,('resolving',),'selected')
    assert ledger.claim(row['id'])['generation']==2
    ledger.close()


def test_result_expiry_cas_preserves_concurrent_disposition(tmp_path):
    path=tmp_path/'ledger.db'; first=Ledger(path); second=Ledger(path)
    row,_=first.reserve('scope','digest',{})
    first.change(row['id'],1,('resolving',),'unknown',result='old output',result_expires=0,result_availability='available')
    actual=first.db
    class Interleave:
        def execute(self,sql,args=()):
            if sql.startswith('UPDATE runs SET data=?,retention_at=NULL WHERE id=? AND data=?'):
                assert second.abandon(row['id'])
            return actual.execute(sql,args)
    first.db.execute('UPDATE runs SET retention_at=0 WHERE id=?',(row['id'],))
    first.db=Interleave()
    first.expire_results()
    assert second.get(row['id'])['disposition']=='abandoned'
    first.db=actual
    first.expire_results()
    result=first.get(row['id'])
    assert result['disposition']=='abandoned' and result['result_availability']=='expired' and 'result' not in result
    first.close(); second.close()



def test_terminal_compaction_keeps_replay_tombstone_and_private_files(tmp_path):
    import os
    import stat
    directory=tmp_path/'state'; directory.mkdir(mode=0o755)
    ledger=Ledger(directory/'db')
    row,_=ledger.reserve('scope','body',{'task':'secret task','context':{'secret':'data'},'registry_snapshot':{'huge':'snapshot'},'payload':{'input':'task'}})
    ledger.change(row['id'],1,('resolving',),'failed',result='sensitive output')
    ledger.db.execute('UPDATE runs SET retention_at=0 WHERE id=?',(row['id'],))
    ledger.expire_results()
    compacted=ledger.get(row['id'])
    assert compacted['compacted'] and compacted['result_availability']=='expired'
    assert not {'task','context','registry_snapshot','payload','result'} & compacted.keys()
    duplicate,new=ledger.reserve('scope','body',{'task':'new'})
    assert not new and duplicate['id']==row['id']
    assert stat.S_IMODE(directory.stat().st_mode)==0o700
    for path in directory.iterdir(): assert stat.S_IMODE(path.stat().st_mode)==0o600
    ledger.close()



def test_abandoned_compaction_preserves_late_receipt_without_resurrection(tmp_path):
    ledger=Ledger(tmp_path/'db')
    row,_=ledger.reserve('scope','digest',{'task':'sensitive','context':{'secret':'yes'},'registry_snapshot':{'secret':'snapshot'},'target':'api','principal':'profile','target_snapshot':{'url':'https://host','principal':'profile','models':{'large':'not needed'}}})
    ledger.change(row['id'],1,('resolving',),'starting',dispatch_token='one-dispatch',idempotency_key='one-key',payload_digest='payload-digest',payload={'input':'sensitive','model':'model','provider':'provider'})
    ledger.change(row['id'],1,('starting',),'unknown')
    assert ledger.abandon(row['id'])
    assert ledger.active()==[] and ledger.get(row['id'])['retention_at'] is not None
    ledger.db.execute('UPDATE runs SET retention_at=0 WHERE id=?',(row['id'],))
    ledger.expire_results()
    compacted=ledger.get(row['id'])
    assert compacted['disposition']=='abandoned' and compacted['state']=='unknown'
    assert not {'task','context','registry_snapshot','payload','result'} & compacted.keys()
    assert compacted['target_snapshot']=={'url':'https://host','principal':'profile'}
    assert not ledger.reserve('scope','digest',{'task':'new'})[1]
    assert not ledger.publish_acceptance(row['id'],'wrong','one-key','payload-digest','host')
    assert ledger.publish_acceptance(row['id'],'one-dispatch','one-key','payload-digest','host')
    accepted=ledger.get(row['id'])
    assert accepted['host_id']=='host' and accepted['disposition']=='abandoned' and accepted['state']=='unknown'
    assert 'payload' not in accepted and ledger.active()==[]
    ledger.close()


def test_unknown_compaction_retains_status_recovery_identity(tmp_path):
    ledger=Ledger(tmp_path/'db'); row,_=ledger.reserve('s','d',{'task':'secret','registry_snapshot':{},'context':{},'target':'api','principal':'p','target_snapshot':{'url':'https://host','principal':'p'}})
    ledger.change(row['id'],1,('resolving',),'unknown',host_id='original')
    deadline=ledger.get(row['id'])['retention_at']
    ledger.change(row['id'],1,('unknown',),'unknown',error={'code':'still_unknown'})
    assert ledger.get(row['id'])['retention_at']==deadline
    ledger.db.execute('UPDATE runs SET retention_at=0')
    ledger.expire_results()
    saved=ledger.get(row['id']); assert saved['host_id']=='original' and saved['target']=='api' and 'task' not in saved
    assert len(ledger.active())==1
    # Later acquired output remains bounded even after input compaction.
    ledger.change(row['id'],1,('unknown',),'completed',result='later result')
    assert ledger.get(row['id'])['retention_at'] is not None
    ledger.close()



def test_unknown_without_host_id_is_not_polled_but_late_acceptance_reactivates(tmp_path):
    ledger=Ledger(tmp_path/'db'); row,_=ledger.reserve('s','d',{})
    ledger.change(row['id'],1,('resolving',),'starting',dispatch_token='token',idempotency_key='key',payload_digest='digest',payload={'model':'m','provider':'p'})
    ledger.change(row['id'],1,('starting',),'unknown')
    assert ledger.active()==[]
    assert ledger.publish_acceptance(row['id'],'token','key','digest','known-host')
    assert [item['id'] for item in ledger.active()]==[row['id']]
    ledger.close()

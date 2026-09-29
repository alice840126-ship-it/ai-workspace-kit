import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from workspace.core import Ledger
from workspace.alerts import notification,issue,observations,health_report,daily_hold_note

class AlertsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.l=Ledger(self.root/'ledger')
        (self.root/'.codex/sessions').mkdir(parents=True)
        self.disk=patch('workspace.alerts.shutil.disk_usage',return_value=SimpleNamespace(free=20*1024**3));self.disk.start()
    def tearDown(self):self.disk.stop();self.l.db.close();self.tmp.cleanup()
    def test_alternating_tick_exception_does_not_repeat_project_alert(self):
        project={'project:repo:autosave':issue('command_failed','프로젝트')}
        self.assertIn('프로젝트',notification(self.l,project))
        self.assertIn('Workspace',notification(self.l,{**project,'workspace':issue('ValueError','Workspace')}))
        for _ in range(4):
            self.assertEqual(notification(self.l,{**project,'workspace':('ok','')}),'[SILENT]')
            self.assertEqual(notification(self.l,{**project,'workspace':issue('ValueError','Workspace')}),'[SILENT]')
    def test_changing_held_count_is_daily_only(self):
        with self.l.db:self.l.db.execute("insert into attempts values('a','held',0)")
        self.assertIn('기존 기록 원인 미분류 1건',daily_hold_note(self.l))
        self.assertEqual(notification(self.l,observations(self.l,self.root)),'[SILENT]')
        with self.l.db:
            self.l.db.execute("insert into attempts values('b','held',1)")
            self.l.db.execute("insert into attempt_reasons values('b','unapproved_link')")
        note=daily_hold_note(self.l);self.assertIn('허용되지 않은 링크 1건',note);self.assertIn('원인 미분류 1건',note)
        self.assertNotIn('민감정보 감지',note)
        self.assertEqual(notification(self.l,observations(self.l,self.root)),'[SILENT]')
    def test_active_editing_busy_and_intake_are_not_incidents(self):
        folder=self.root/'.codex/state/canonical-sync';folder.mkdir(parents=True)
        for code in ['checkout_changed_during_sync','source_changed_during_snapshot','generated_concurrent_edit','locked']:
            data={'projects':[{'project':'owner/project','status':'uncommitted','ok':False,'intake_status':'deferred','autosave':{'ok':False,'code':code}}]}
            (folder/'projects-last.json').write_text(json.dumps(data))
            self.assertEqual(notification(self.l,observations(self.l,self.root)),'[SILENT]')
    def test_security_is_immediate_and_health_does_not_consume_it(self):
        current={'project':issue('snapshot_secret_scan_blocked','프로젝트')}
        self.assertIn('보안',health_report(current));self.assertIsNone(self.l.get('notification_incidents_v1'))
        self.assertIn('보안',notification(self.l,current));self.assertEqual(notification(self.l,current),'[SILENT]')
        notification(self.l,{'project':issue('command_failed','프로젝트')})
        self.assertEqual(notification(self.l,current),'[SILENT]')
    def test_recurrence_requires_three_consecutive_success_observations(self):
        failure={'scope':issue('command_failed','프로젝트')}
        notification(self.l,failure)
        for _ in range(2):notification(self.l,{'scope':('ok','')})
        notification(self.l,{'scope':('transient','')})
        notification(self.l,{'scope':('ok','')})
        self.assertEqual(notification(self.l,failure),'[SILENT]')
        for _ in range(3):self.assertEqual(notification(self.l,{'scope':('ok','')}),'[SILENT]')
        self.assertIn('프로젝트',notification(self.l,failure))
    def test_untrusted_error_is_not_in_alert(self):
        self.assertNotIn('/private',issue('error /private/runtime/file','프로젝트')[1])

if __name__=='__main__':unittest.main()

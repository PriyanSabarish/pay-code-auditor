"""Preview protocol tests only; no payroll correctness claims."""
import time
import unittest
from fastapi.testclient import TestClient
from web.preview_api import app, jobs, sample_result, AuditJob, Progress


class PreviewApiTests(unittest.TestCase):
    def test_job_lifecycle_and_server_export(self):
        with TestClient(app) as client:
            created=client.post('/api/audits',data={'award_id':'demo-award','mode':'full'},files={'paycodes':('codes.csv',b'code,name\nA,Example'), 'payruns':('runs.csv',b'code,amount\nA,100')})
            self.assertEqual(created.status_code,202)
            path=f"/api/audits/{created.json()['audit_id']}"
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                job=client.get(path).json()
                if job['status']=='awaiting_input':break
                time.sleep(.1)
            self.assertEqual(job['status'],'awaiting_input')
            self.assertEqual(job['progress']['completed'],8)
            self.assertEqual(client.get(path+'/report.csv').status_code,409)
            self.assertEqual(client.post(path+'/answer',json={'question_id':'wrong','answer':'context'}).status_code,409)
            answered=client.post(path+'/answer',json={'question_id':job['pending_question']['id'],'answer':'Example reviewer context'})
            self.assertEqual(answered.json()['status'],'complete')
            verdict=client.post(path+'/verdicts/SITE_ALLOW',json={'action':'override','treatment':'no','note':'=FORMULA()'})
            self.assertEqual(verdict.status_code,200)
            exported=client.get(path+'/report.csv')
            self.assertIn("'=FORMULA()",exported.text)
            self.assertIn('override',exported.text)
            self.assertIn('attachment',exported.headers['content-disposition'])
            self.assertEqual(client.get(path+'/letter/SITE_ALLOW').status_code,200)
            self.assertIn('DRAFT FOR PROFESSIONAL REVIEW',client.get(path+'/letter/SITE_ALLOW?download=true').text)

    def test_invalid_files_return_field_errors(self):
        with TestClient(app) as client:
            result=client.post('/api/audits',data={'award_id':'demo-award'},files={'paycodes':('bad.csv',b'code,name\nA,B,C'), 'payruns':('runs.csv',b'code,amount\nA,100')})
            self.assertEqual(result.status_code,422)
            self.assertEqual(result.json()['detail'][0]['loc'],['body','paycodes'])

    def test_unknown_job_and_invalid_decisions(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/audits/missing').status_code,404)
            jobs['decision-test']=AuditJob(audit_id='decision-test',status='complete',result=sample_result(),progress=Progress(completed=8,total=8,message='test'))
            path='/api/audits/decision-test/verdicts/ORD_HRS'
            self.assertEqual(client.post(path,json={'action':'approve','treatment':'no'}).status_code,422)
            self.assertEqual(client.post(path,json={'action':'override','treatment':'no','note':''}).status_code,422)

    def test_spa_refresh_and_api_routes_are_separate(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/workspace/review').status_code,200)
            self.assertIn('id="root"',client.get('/workspace/review').text)
            self.assertEqual(client.get('/api/not-a-route').status_code,404)
            self.assertEqual(client.get('/assets/not-a-file.js').status_code,404)


if __name__=='__main__':unittest.main()

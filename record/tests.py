import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import AnesthesiaRecord, AnesthesiaCase, FreeTextNote


class SaveAllTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('doc', password='x')
        self.user.is_approved = True
        self.user.save()
        self.other = User.objects.create_user('other', password='x')
        self.other.is_approved = True
        self.other.save()
        self.client.force_login(self.user)
        self.url = reverse('record_save_all')

    def post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type='application/json')

    def base_payload(self, columns, **extra):
        payload = {
            'case': {
                'info': {'patient_id': 'P1', 'patient_name': '홍길동'},
                'events': [{'time': '2026-09-23T15:05', 'label': 'Induction'}],
                'rows': [{'name': 'EtCO2', 'group': 'gas', 'unit': 'mmHg'}, {'name': 'HR', 'group': 'vital'}],
            },
            'note': '15:00 Time out',
            'columns': columns,
        }
        payload.update(extra)
        return payload

    def test_creates_case_note_and_records(self):
        res = self.post(self.base_payload([
            {'id': None, 'timestamp': '2026-09-23T15:05', 'hr': '80', 'sbp': '120', 'dbp': '70', 'spo2': '99.4',
             'extra_vitals': {'EtCO2': '35'}, 'notes': 'memo'},
            {'id': None, 'timestamp': '2026-09-23T15:00', 'hr': '', 'sbp': '', 'dbp': '', 'spo2': '',
             'extra_vitals': {}, 'notes': ''},
        ]))
        self.assertEqual(res.status_code, 200)
        state = res.json()['state']
        self.assertEqual([r['timestamp'] for r in state['records']], ['2026-09-23T15:00', '2026-09-23T15:05'])
        rec = state['records'][1]
        self.assertEqual((rec['hr'], rec['spo2'], rec['extra_vitals']), (80, 99, {'EtCO2': 35}))
        # 기본 행 이름(HR)은 추가 행 목록에 저장되지 않음
        self.assertEqual([r['name'] for r in state['case']['rows']], ['EtCO2'])
        self.assertEqual(FreeTextNote.objects.get(user=self.user).content, '15:00 Time out')
        self.assertEqual(AnesthesiaRecord.objects.filter(user=self.user, patient_id='P1').count(), 2)

    def test_updates_and_deletes_in_one_request(self):
        keep = AnesthesiaRecord.objects.create(user=self.user, hr=60)
        drop = AnesthesiaRecord.objects.create(user=self.user, hr=70)
        res = self.post(self.base_payload(
            [{'id': keep.id, 'timestamp': '2026-09-23T16:00', 'hr': '65', 'extra_vitals': {}}],
            deleted=[drop.id],
        ))
        self.assertEqual(res.status_code, 200)
        keep.refresh_from_db()
        self.assertEqual(keep.hr, 65)
        self.assertFalse(AnesthesiaRecord.objects.filter(id=drop.id).exists())

    def test_rejects_non_numeric_without_partial_save(self):
        res = self.post(self.base_payload([
            {'id': None, 'timestamp': '2026-09-23T15:00', 'hr': '80'},
            {'id': None, 'timestamp': '2026-09-23T15:05', 'hr': 'abc'},
        ]))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(AnesthesiaRecord.objects.count(), 0)
        self.assertFalse(AnesthesiaCase.objects.filter(user=self.user).exists())

    def test_cannot_touch_other_users_records(self):
        theirs = AnesthesiaRecord.objects.create(user=self.other, hr=50)
        self.post(self.base_payload(
            [{'id': theirs.id, 'timestamp': '2026-09-23T15:00', 'hr': '99'}],
            deleted=[theirs.id],
        ))
        theirs.refresh_from_db()
        self.assertEqual(theirs.hr, 50)
        # 다른 사용자의 id를 보내면 새 레코드로 생성됨
        self.assertEqual(AnesthesiaRecord.objects.filter(user=self.user, hr=99).count(), 1)

    def test_delete_requires_post(self):
        rec = AnesthesiaRecord.objects.create(user=self.user)
        res = self.client.get(reverse('delete_record', args=[rec.id]))
        self.assertEqual(res.status_code, 405)
        self.assertTrue(AnesthesiaRecord.objects.filter(id=rec.id).exists())

    def test_page_renders_state_safely(self):
        AnesthesiaCase.objects.create(user=self.user, info={'patient_name': '</script><script>alert(1)</script>'})
        res = self.client.get(reverse('anesthesia_record'))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, '</script><script>alert(1)')

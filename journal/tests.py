import json
from datetime import date, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import processing
from .models import Issue, Journal, Paper
from .templatetags.journal_extras import summary_html


def make_pdf(text):
    """글자 한 줄짜리 최소 PDF (테스트용)."""
    stream = f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode()
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj" % i + obj + b"endobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    return out


SUMMARY = {
    "title": "AI read title", "authors": "AI Author", "doi": "",
    "short_summary": "  핵심 한 문장  요약. ",
    "sections": [{"heading": "연구 목적", "body": "목적 내용."}, {"heading": "주요 결과", "body": "결과 <b>내용</b>."}],
}


@override_settings(GEMINI_API_KEY="test-key", JOURNAL_CRON_TOKEN="")
class JournalTestBase(TestCase):
    def setUp(self):
        # 테스트가 실제 Gemini 를 부르지 않게 (환경변수에 키가 있어도) · 논문 사이 쉬는 시간 없이
        processing._model_skip_until.clear()
        self.addCleanup(processing._model_skip_until.clear)
        for target in ("journal.processing.requests.post", "journal.processing.time.sleep"):
            patcher = mock.patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        # PDF 는 실제 B2 대신 메모리 저장소로
        field = Paper._meta.get_field("pdf_file")
        self._storage = field.storage
        field.storage = InMemoryStorage()
        self.addCleanup(setattr, field, "storage", self._storage)
        worker = mock.patch("journal.processing.start_worker")
        self.start_worker = worker.start()
        self.addCleanup(worker.stop)
        User = get_user_model()
        self.staff = User.objects.create_user("boss", "b@example.com", "x", is_staff=True, is_approved=True)
        self.member = User.objects.create_user("m", "m@example.com", "x", is_approved=True)
        self.journal = Journal.objects.create(name="BJA", slug="bja")


class UploadTests(JournalTestBase):
    def upload(self, name="01_Some paper.pdf", content=None, **data):
        pdf = SimpleUploadedFile(name, content if content is not None else make_pdf("hello"), content_type="application/pdf")
        return self.client.post(reverse("journal:upload_file"), {"file": pdf, **data})

    def test_staff_only(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("journal:upload")).status_code, 302)
        self.assertEqual(self.upload(journal_id=self.journal.pk, volume="1").status_code, 302)
        self.assertFalse(Paper.objects.exists())
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("journal:upload")), "논문 올리기")
        self.assertContains(self.client.get(reverse("journal:journal_stand")), reverse("journal:upload"))

    def test_new_issue_upload_queues_processing_and_skips_duplicates(self):
        self.client.force_login(self.staff)
        res = self.upload(journal_id=self.journal.pk, volume="137", number="2", publish_date="2026-08-01").json()
        self.assertTrue(res["ok"])
        issue = Issue.objects.get(pk=res["issue"]["id"])
        self.assertEqual((issue.volume, issue.number, str(issue.publish_date)), ("137", "2", "2026-08-01"))
        paper = Paper.objects.get()
        self.assertEqual((paper.title, paper.processing_status, paper.order), ("Some paper", "pending", 1))
        self.start_worker.assert_called()
        # 같은 파일 다시 → 새로 만들지 않음, 다른 파일은 같은 호 다음 순서로
        again = self.upload(issue_id=issue.pk).json()
        self.assertTrue(again["duplicate"])
        self.upload("02_other.pdf", make_pdf("other"), issue_id=issue.pk)
        self.assertEqual(list(issue.papers.values_list("order", flat=True)), [1, 2])
        # 같은 권·호를 새 호로 다시 적어도 기존 호를 씀
        self.upload("03.pdf", make_pdf("third"), journal_id=self.journal.pk, volume="137", number="2")
        self.assertEqual(Issue.objects.count(), 1)

    def test_rejects_non_pdf_and_missing_issue(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.upload(journal_id=self.journal.pk).status_code, 400)                 # 권 없음
        self.assertEqual(self.upload("x.pdf", b"not a pdf", journal_id=self.journal.pk, volume="1").status_code, 400)
        self.assertEqual(self.upload("x.txt", journal_id=self.journal.pk, volume="1").status_code, 400)
        self.assertFalse(Paper.objects.exists())

    def test_status_and_actions(self):
        self.client.force_login(self.staff)
        issue = Issue.objects.create(journal=self.journal, volume="1")
        done = Paper.objects.create(issue=issue, title="done", ai_summary="요약", pdf_file="papers/a.pdf")
        bare = Paper.objects.create(issue=issue, title="bare", pdf_file="papers/b.pdf")
        err = Paper.objects.create(issue=issue, title="err", ai_summary="x", processing_status="error",
                                   processing_message="Gemini 한도", pdf_file="papers/c.pdf")
        rows = self.client.get(reverse("journal:processing_status"), {"issue": issue.pk}).json()["papers"]
        self.assertEqual({r["title"]: r["status"] for r in rows}, {"done": "done", "bare": "no_summary", "err": "error"})
        post = lambda action: self.client.post(reverse("journal:processing_action"),
                                               json.dumps({"action": action, "issue": issue.pk}), content_type="application/json").json()
        self.assertEqual(post("retry")["queued"], 1)
        self.assertEqual(post("summarize_missing")["queued"], 1)
        statuses = dict(Paper.objects.values_list("title", "processing_status"))
        self.assertEqual(statuses, {"done": "", "bare": "pending", "err": "pending"})


class ProcessingTests(JournalTestBase):
    def make_paper(self, text="Study doi:10.1016/j.bja.2026.01.001. Methods"):
        issue = Issue.objects.create(journal=self.journal, volume="1")
        paper = Paper(issue=issue, title="file name", processing_status="pending")
        paper.pdf_file.save("p.pdf", ContentFile(make_pdf(text)), save=False)
        paper.save()
        return paper

    def test_find_doi(self):
        self.assertEqual(processing.find_doi("see https://doi.org/10.1016/j.bja.2026.01.001)."), "10.1016/j.bja.2026.01.001")
        self.assertEqual(processing.find_doi("no doi here"), "")

    @mock.patch("journal.processing.crossref_metadata",
                return_value={"title": "Exact Title From Crossref", "authors": "Kim A, Lee B"})
    @mock.patch("journal.processing._gemini_summary", return_value=dict(SUMMARY))
    def test_process_paper_fills_everything(self, gemini, crossref):
        paper = self.make_paper()
        processing.run_pending()
        paper.refresh_from_db()
        crossref.assert_called_with("10.1016/j.bja.2026.01.001")
        pdf_bytes, text = gemini.call_args.args
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertIn("Methods", text)
        self.assertEqual((paper.title, paper.authors, paper.doi),
                         ("Exact Title From Crossref", "Kim A, Lee B", "10.1016/j.bja.2026.01.001"))
        self.assertEqual(paper.short_summary, "핵심 한 문장 요약.")
        self.assertEqual(paper.ai_summary, "### 연구 목적\n목적 내용.\n\n### 주요 결과\n결과 <b>내용</b>.")
        self.assertEqual((paper.processing_status, paper.attempts, paper.next_attempt_at), ("", 1, None))

    @mock.patch("journal.processing.crossref_metadata", return_value=None)
    def test_gemini_reads_pdf_and_ai_metadata(self, crossref):
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(SUMMARY, ensure_ascii=False)}]}}]}
        paper = self.make_paper("no identifier here")
        with mock.patch("journal.processing.requests.post", return_value=ok) as post:
            processing.run_pending()
        paper.refresh_from_db()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(post.call_args.kwargs["params"], {"key": "test-key"})
        self.assertIn("gemini-4-hydrogen", post.call_args.args[0])              # 논문 요약은 Hydrogen 먼저
        self.assertEqual(payload["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})
        self.assertEqual(payload["contents"][0]["parts"][0]["inline_data"]["mime_type"], "application/pdf")
        self.assertEqual((paper.title, paper.authors, paper.doi), ("AI read title", "AI Author", ""))
        self.assertIn("AI 가 PDF", paper.processing_message)
        self.assertEqual(paper.processing_status, "")

    @mock.patch("journal.processing.crossref_metadata", return_value=None)
    @mock.patch("journal.processing._gemini_summary", side_effect=processing.ProcessingError("PDF 를 읽을 수 없음"))
    def test_failure_is_recorded_not_raised(self, *_):
        paper = self.make_paper()
        processing.run_pending()
        paper.refresh_from_db()
        self.assertEqual(paper.processing_status, "error")
        self.assertIn("PDF 를 읽을 수 없음", paper.processing_message)
        self.assertEqual(paper.title, "file name")

    @mock.patch("journal.processing.crossref_metadata", return_value=None)
    def test_quota_puts_all_waiting_papers_on_hold_then_resumes(self, crossref):
        first, second = self.make_paper(), self.make_paper("second paper")
        limit = processing.RetryLater(timedelta(hours=3), "Gemini 무료 한도 초과")
        with mock.patch("journal.processing._gemini_summary", side_effect=limit) as gemini:
            processing.run_pending()
        self.assertEqual(gemini.call_count, 1)                    # 한도면 나머지는 두드리지 않음
        for p in (first, second):
            p.refresh_from_db()
            self.assertEqual(p.processing_status, "pending")
            self.assertAlmostEqual((p.next_attempt_at - timezone.now()).total_seconds(), 3 * 3600, delta=60)
            self.assertIn("자동으로", p.processing_message)
        self.assertIsNone(processing._claim_next())               # 아직 때가 아님
        self.assertIsNotNone(processing.next_due_at())
        # 시간이 지나면 다시 처리
        Paper.objects.update(next_attempt_at=timezone.now() - timedelta(minutes=1))
        with mock.patch("journal.processing._gemini_summary", return_value=dict(SUMMARY)):
            processing.run_pending()
        self.assertEqual(list(Paper.objects.values_list("processing_status", flat=True)), ["", ""])
        self.assertEqual(Paper.objects.filter(next_attempt_at__isnull=False).count(), 0)

    def test_quota_wait_follows_google_reset(self):
        def resp(details):
            r = mock.Mock()
            r.json.return_value = {"error": {"code": 429, "details": details}}
            return r
        per_day = resp([{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
                        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "40s"}])
        now = datetime(2026, 11, 21, 20, 0, tzinfo=ZoneInfo("America/Los_Angeles"))     # 태평양 오후 8시
        self.assertEqual(processing.quota_wait(per_day, now), timedelta(hours=4, minutes=5))   # 자정 + 5분
        per_minute = resp([{"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
                           {"retryDelay": "37s"}])
        self.assertEqual(processing.quota_wait(per_minute, now), timedelta(seconds=60))
        self.assertEqual(processing.quota_wait(resp([{"retryDelay": "90s"}]), now), timedelta(seconds=105))
        self.assertEqual(processing.quota_wait(resp([]), now), timedelta(hours=3))      # 알 수 없음 → 3시간

    @override_settings(JOURNAL_GEMINI_MODEL="model-a", GEMINI_MODEL="model-b", GEMINI_FALLBACK_MODELS="")
    def test_next_model_on_quota_and_retry_when_all_limited(self):
        limited = mock.Mock(status_code=429, text="quota")
        limited.json.return_value = {"error": {"details": [{"violations": [{"quotaId": "PerMinute"}]}, {"retryDelay": "20s"}]}}
        ok = mock.Mock(status_code=200)
        with mock.patch("journal.processing.requests.post", side_effect=[limited, ok]) as post:
            self.assertIs(processing._gemini_post({}), ok)          # 모델마다 한도가 따로 → 다음 모델
        self.assertIn("model-b", post.call_args.args[0])
        with mock.patch("journal.processing.requests.post", return_value=ok) as post:
            processing._gemini_post({})                              # 한도에 걸린 model-a 는 1분 동안 건너뜀
        self.assertEqual(post.call_count, 1)
        self.assertIn("model-b", post.call_args.args[0])
        processing._model_skip_until.clear()
        with mock.patch("journal.processing.requests.post", return_value=limited):
            with self.assertRaises(processing.RetryLater) as ctx:
                processing._gemini_post({})
        self.assertEqual(ctx.exception.wait, timedelta(seconds=60))
        processing._model_skip_until.clear()                         # (한도로 둘 다 건너뛰는 중이라 비우고)
        bad_key = mock.Mock(status_code=400, text="API key not valid")
        with mock.patch("journal.processing.requests.post", return_value=bad_key):
            with self.assertRaisesMessage(processing.ProcessingError, "GEMINI_API_KEY"):
                processing._gemini_post({})

    @override_settings(JOURNAL_GEMINI_MODEL="gemini-4-hydrogen", GEMINI_MODEL="gemini-3.1-flash-lite", GEMINI_FALLBACK_MODELS="")
    def test_busy_model_is_skipped_for_a_while(self):
        busy = mock.Mock(status_code=503, text="high demand")
        ok = mock.Mock(status_code=200)
        with mock.patch("journal.processing.requests.post", side_effect=[busy, ok]):
            processing._gemini_post({})
        with mock.patch("journal.processing.requests.post", return_value=ok) as post:
            processing._gemini_post({})                              # 과부하 난 Hydrogen 은 30분 건너뛰고 바로 다음 모델
        self.assertEqual(post.call_count, 1)
        self.assertIn("gemini-3.1-flash-lite", post.call_args.args[0])
        processing._model_skip_until["gemini-4-hydrogen"] = timezone.now() - timedelta(seconds=1)
        with mock.patch("journal.processing.requests.post", return_value=ok) as post:
            processing._gemini_post({})                              # 시간이 지나면 다시 Hydrogen 먼저
        self.assertIn("gemini-4-hydrogen", post.call_args.args[0])

    def test_model_order_and_thinking_only_for_new_models(self):
        with override_settings(JOURNAL_GEMINI_MODEL="gemini-4-hydrogen", GEMINI_MODEL="gemini-3.1-flash-lite",
                               GEMINI_FALLBACK_MODELS="gemini-2.5-flash,gemini-4-hydrogen"):
            self.assertEqual(processing.journal_models(), ["gemini-4-hydrogen", "gemini-3.1-flash-lite", "gemini-2.5-flash"])
        base = {"generationConfig": {"temperature": 0.2}}
        self.assertIn("thinkingConfig", processing._payload_for("gemini-3.1-flash-lite", base)["generationConfig"])
        self.assertEqual(processing._payload_for("gemini-2.5-flash", base), base)     # 2.5 는 thinkingLevel 을 모름
        self.assertEqual(base, {"generationConfig": {"temperature": 0.2}})            # 원본은 그대로

    def test_no_key_is_clear_error(self):
        with override_settings(GEMINI_API_KEY=""):
            with self.assertRaisesMessage(processing.ProcessingError, "GEMINI_API_KEY"):
                processing.summarize(b"%PDF", "some text")

    def test_summary_rendering(self):
        html = summary_html("### 연구 목적\n목적 <script>.\n\n### 결과\n결과 1\n결과 2")
        self.assertEqual(html, '<h4 class="summary-heading">연구 목적</h4><p>목적 &lt;script&gt;.</p>'
                               '<h4 class="summary-heading">결과</h4><p>결과 1<br>결과 2</p>')
        self.assertEqual(summary_html("예전 문단 요약\n\n둘째 문단"), "<p>예전 문단 요약</p><p>둘째 문단</p>")

    def test_detail_page_renders_sections(self):
        paper = self.make_paper()
        Paper.objects.filter(pk=paper.pk).update(ai_summary="### 연구 목적\n내용", processing_status="")
        self.client.force_login(self.member)
        with mock.patch("journal.views.generate_paper_url", return_value="https://example.com/p.pdf"):
            res = self.client.get(paper.get_absolute_url())
        self.assertContains(res, '<h4 class="summary-heading">연구 목적</h4>', html=True)


class AutoIssueTests(JournalTestBase):
    META = {"title": "Crossref Title", "authors": "Kim A", "volume": "137", "issue": "3",
            "date": date(2026, 3, 1), "journal": "British Journal of Anaesthesia"}

    def upload(self, name, content, meta):
        pdf = SimpleUploadedFile(name, content, content_type="application/pdf")
        with mock.patch("journal.processing.pdf_metadata", return_value=("10.1/x", meta)):
            return self.client.post(reverse("journal:upload_file"), {"file": pdf, "mode": "auto", "journal_id": self.journal.pk})

    def test_volume_issue_date_from_crossref(self):
        self.client.force_login(self.staff)
        res = self.upload("a.pdf", make_pdf("a"), self.META).json()
        self.assertTrue(res["ok"] and res["created_issue"])
        self.assertFalse(res["journal_mismatch"])                    # BJA = British Journal of Anaesthesia
        issue = Issue.objects.get()
        self.assertEqual((issue.volume, issue.number, issue.publish_date), ("137", "3", date(2026, 3, 1)))
        paper = Paper.objects.get()
        self.assertEqual((paper.title, paper.authors, paper.doi, paper.processing_status),
                         ("Crossref Title", "Kim A", "10.1/x", "pending"))
        # 같은 권·호 → 같은 호, 다른 호 → 새 호
        self.assertFalse(self.upload("b.pdf", make_pdf("b"), self.META).json()["created_issue"])
        self.upload("c.pdf", make_pdf("c"), dict(self.META, issue="4", date=date(2026, 4, 1)))
        self.assertEqual(sorted(Issue.objects.values_list("number", flat=True)), ["3", "4"])
        # 같은 파일은 다시 안 올라감 (학술지 전체에서)
        self.assertTrue(self.upload("a-again.pdf", make_pdf("a"), self.META).json()["duplicate"])
        self.assertEqual(Paper.objects.count(), 3)
        # 이번에 올린 논문들 현황 (여러 호)
        ids = ",".join(str(i) for i in Paper.objects.values_list("id", flat=True))
        rows = self.client.get(reverse("journal:processing_status"), {"papers": ids}).json()["papers"]
        self.assertEqual(len({r["issue_id"] for r in rows}), 2)

    def test_without_volume_asks_for_issue(self):
        self.client.force_login(self.staff)
        res = self.upload("online-first.pdf", make_pdf("x"), dict(self.META, volume="", issue=""))
        self.assertEqual(res.status_code, 400)
        self.assertTrue(res.json()["need_issue"])
        self.assertIn("온라인 선공개", res.json()["error"])
        res = self.upload("no-doi.pdf", make_pdf("y"), None)
        self.assertIn("Crossref", res.json()["error"])
        self.assertFalse(Paper.objects.exists() or Issue.objects.exists())

    def test_journal_mismatch_flag(self):
        self.client.force_login(self.staff)
        res = self.upload("a.pdf", make_pdf("a"), dict(self.META, journal="Anesthesiology")).json()
        self.assertTrue(res["journal_mismatch"])


class ProcessTickTests(JournalTestBase):
    url = "/journal/process-tick/"

    def test_disabled_without_token(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)

    @override_settings(JOURNAL_CRON_TOKEN="s3cret")
    def test_token_and_wakes_worker(self):
        self.assertEqual(self.client.get(self.url, HTTP_X_CRON_TOKEN="nope").status_code, 403)
        issue = Issue.objects.create(journal=self.journal, volume="1")
        later = Paper.objects.create(issue=issue, title="later", processing_status="pending",
                                     next_attempt_at=timezone.now() + timedelta(hours=2))
        res = self.client.post(self.url, HTTP_X_CRON_TOKEN="s3cret").json()
        self.assertEqual((res["pending"], res["due_now"]), (1, 0))
        self.start_worker.assert_not_called()                      # 아직 때가 아님
        Paper.objects.filter(pk=later.pk).update(next_attempt_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.get(self.url, HTTP_X_CRON_TOKEN="s3cret").json()["due_now"], 1)
        self.start_worker.assert_called_once()

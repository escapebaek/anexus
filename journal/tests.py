import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

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


class JournalTestBase(TestCase):
    def setUp(self):
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
        issue = Issue.objects.get(pk=res["issue_id"])
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
        self.assertEqual(paper.processing_status, "")

    @mock.patch("journal.processing.crossref_metadata", return_value=None)
    @mock.patch("journal.processing._gemini_summary", side_effect=processing.ProcessingError("quota"))
    @mock.patch("journal.processing._text_provider_summary", return_value=dict(SUMMARY))
    def test_falls_back_to_text_provider_and_ai_metadata(self, text_provider, gemini, crossref):
        paper = self.make_paper("no identifier here")
        processing.run_pending()
        paper.refresh_from_db()
        text_provider.assert_called_once()
        self.assertEqual((paper.title, paper.authors, paper.doi), ("AI read title", "AI Author", ""))
        self.assertIn("AI 가 PDF", paper.processing_message)

    @mock.patch("journal.processing.crossref_metadata", return_value=None)
    @mock.patch("journal.processing._gemini_summary", side_effect=processing.ProcessingError("quota"))
    @mock.patch("journal.processing._text_provider_summary", side_effect=processing.ProcessingError("groq down"))
    def test_failure_is_recorded_not_raised(self, *_):
        paper = self.make_paper()
        processing.run_pending()
        paper.refresh_from_db()
        self.assertEqual(paper.processing_status, "error")
        self.assertIn("quota", paper.processing_message)
        self.assertEqual(paper.title, "file name")

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

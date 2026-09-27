import hashlib
import json
import re
from pathlib import Path

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.decorators import user_is_approved
from anhub.storage_backends import generate_paper_url
from . import processing
from .models import Journal, Issue, Paper


@login_required
@user_is_approved
def journal_stand(request):
    journals = Journal.objects.filter(is_active=True)
    return render(request, 'journal/journal_stand.html', {'journals': journals})


@login_required
@user_is_approved
def journal_detail(request, slug):
    journal = get_object_or_404(Journal, slug=slug, is_active=True)
    return _render_issue(request, journal, journal.latest_issue)


@login_required
@user_is_approved
def issue_detail(request, slug, issue_pk):
    journal = get_object_or_404(Journal, slug=slug, is_active=True)
    issue = get_object_or_404(Issue, pk=issue_pk, journal=journal)
    return _render_issue(request, journal, issue)


def _render_issue(request, journal, issue):
    context = {
        'journal': journal,
        'issue': issue,
        'papers': issue.papers.all() if issue else Paper.objects.none(),
        'past_issues': journal.issues.exclude(pk=issue.pk) if issue else journal.issues.all(),
        'is_latest_issue': issue is not None and issue.pk == journal.latest_issue.pk,
    }
    return render(request, 'journal/journal_detail.html', context)


@login_required
@user_is_approved
def paper_detail(request, pk):
    paper = get_object_or_404(Paper, pk=pk)
    view_url = None
    download_url = None
    if paper.pdf_file:
        view_url = generate_paper_url(paper.pdf_file.name, disposition='inline')
        download_url = generate_paper_url(
            paper.pdf_file.name, disposition='attachment', filename=paper.title
        )
    context = {
        'paper': paper,
        'view_url': view_url,
        'download_url': download_url,
    }
    return render(request, 'journal/paper_detail.html', context)


# ---------------------------------------------------------------------------
# 논문 올리기 (관리자 전용): PDF 끌어다 놓기 → 제목·저자·요약 자동 (journal/processing.py)
# ---------------------------------------------------------------------------

staff_required = user_passes_test(lambda u: u.is_active and u.is_staff, login_url='login')
MAX_PDF_BYTES = 40 * 1024 * 1024


def _paper_row(paper):
    return {
        'id': paper.pk,
        'title': paper.title,
        'authors': paper.authors,
        'status': paper.processing_status or ('done' if paper.ai_summary else 'no_summary'),
        'message': paper.processing_message,
        'short_summary': paper.short_summary,
        'url': paper.get_absolute_url(),
        'admin_url': f'/admin/journal/paper/{paper.pk}/change/',
    }


@staff_required
def upload_page(request):
    journals = Journal.objects.all()
    issues = Issue.objects.select_related('journal').order_by('journal__order', 'journal__name', '-publish_date')
    return render(request, 'journal/upload.html', {
        'journals': journals,
        'issues': [{'id': i.pk, 'journal': i.journal_id, 'label': str(i), 'volume': i.volume,
                    'number': i.number, 'date': i.publish_date.isoformat()} for i in issues],
        'today': timezone.localdate().isoformat(),
    })


def _issue_from_request(data):
    """기존 호(issue_id) 또는 새 호(journal + 권/호/발행일, 같은 권·호가 있으면 그것)."""
    if data.get('issue_id'):
        return Issue.objects.filter(pk=data['issue_id']).first()
    journal = Journal.objects.filter(pk=data.get('journal_id') or 0).first()
    volume = (data.get('volume') or '').strip()[:50]
    number = (data.get('number') or '').strip()[:50]
    if journal is None or not volume:
        return None
    issue, _ = Issue.objects.get_or_create(
        journal=journal, volume=volume, number=number,
        defaults={'publish_date': parse_date(data.get('publish_date') or '') or timezone.localdate()})
    return issue


@staff_required
@require_POST
def upload_file(request):
    upload = request.FILES.get('file')
    issue = _issue_from_request(request.POST)
    if issue is None:
        return JsonResponse({'ok': False, 'error': '학술지와 권(Volume)을 입력하거나 기존 호를 고르세요.'}, status=400)
    if upload is None or not upload.name.lower().endswith('.pdf'):
        return JsonResponse({'ok': False, 'error': 'PDF 파일만 올릴 수 있습니다.'}, status=400)
    if upload.size > MAX_PDF_BYTES:
        return JsonResponse({'ok': False, 'error': 'PDF 가 너무 큽니다 (최대 40MB).'}, status=400)

    digest = hashlib.sha1()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    if upload.read(5) != b'%PDF-':
        return JsonResponse({'ok': False, 'error': 'PDF 파일이 아닙니다.'}, status=400)
    upload.seek(0)
    sha1 = digest.hexdigest()
    existing = issue.papers.filter(source_sha1=sha1).first()
    if existing:
        return JsonResponse({'ok': True, 'duplicate': True, 'issue_id': issue.pk, 'paper': _paper_row(existing)})

    # 처리 전 임시 제목: 파일 이름 ('01_' 같은 앞 번호·밑줄 정리)
    title = re.sub(r'^\d+[\s._-]+', '', Path(upload.name).stem).replace('_', ' ').strip() or Path(upload.name).stem
    order = (issue.papers.aggregate(Max('order'))['order__max'] or 0) + 1
    paper = Paper(issue=issue, title=title[:500], order=order, source_sha1=sha1,
                  processing_status='pending', processing_message='요약 대기 중',
                  processing_updated=timezone.now())
    paper.pdf_file.save(upload.name, upload, save=False)
    paper.save()
    processing.start_worker()
    return JsonResponse({'ok': True, 'issue_id': issue.pk, 'paper': _paper_row(paper)})


@staff_required
def processing_status(request):
    issue = Issue.objects.filter(pk=request.GET.get('issue') or 0).first()
    if issue is None:
        return JsonResponse({'ok': False, 'error': 'Issue not found'}, status=404)
    papers = [_paper_row(p) for p in issue.papers.all()]
    if any(p['status'] in ('pending', 'running') for p in papers):
        processing.start_worker()     # 서버가 재시작돼 멈춘 작업도 다시 이어서
    return JsonResponse({'ok': True, 'issue': {'id': issue.pk, 'label': str(issue),
                                               'url': issue.get_absolute_url()}, 'papers': papers})


@staff_required
@require_POST
def processing_action(request):
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    issue = Issue.objects.filter(pk=data.get('issue') or 0).first()
    if issue is None:
        return JsonResponse({'ok': False, 'error': 'Issue not found'}, status=404)
    papers = issue.papers.exclude(processing_status__in=('pending', 'running')).exclude(pdf_file='')
    if data.get('action') == 'retry':
        papers = papers.filter(processing_status='error')
    elif data.get('action') == 'summarize_missing':
        papers = papers.filter(ai_summary='')
    elif data.get('action') == 'resummarize' and data.get('paper'):
        papers = papers.filter(pk=data['paper'])
    else:
        return JsonResponse({'ok': False, 'error': 'Invalid action'}, status=400)
    count = papers.update(processing_status='pending', processing_message='요약 대기 중',
                          processing_updated=timezone.now())
    if count:
        processing.start_worker()
    return JsonResponse({'ok': True, 'queued': count})

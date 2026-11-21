import hashlib
import hmac
import json
import re
from pathlib import Path

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Max
from django.conf import settings
from django.http import Http404, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
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
    waiting = paper.processing_status == 'pending' and paper.next_attempt_at and paper.next_attempt_at > timezone.now()
    return {
        'id': paper.pk,
        'title': paper.title,
        'authors': paper.authors,
        'status': 'waiting' if waiting else (paper.processing_status or ('done' if paper.ai_summary else 'no_summary')),
        'message': paper.processing_message,
        'short_summary': paper.short_summary,
        'url': paper.get_absolute_url(),
        'admin_url': f'/admin/journal/paper/{paper.pk}/change/',
        'issue_id': paper.issue_id,
        'issue_label': str(paper.issue),
    }


def _issue_row(issue):
    return {'id': issue.pk, 'journal': issue.journal_id, 'label': str(issue), 'volume': issue.volume,
            'number': issue.number, 'date': issue.publish_date.isoformat(), 'url': issue.get_absolute_url()}


@staff_required
def upload_page(request):
    journals = Journal.objects.all()
    issues = Issue.objects.select_related('journal').order_by('journal__order', 'journal__name', '-publish_date')
    return render(request, 'journal/upload.html', {
        'journals': journals,
        'issues': [_issue_row(i) for i in issues],
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


def _auto_issue(journal, meta):
    """Crossref 의 권·호로 그 학술지의 호를 찾고, 없으면 Crossref 발행일로 새로 만든다. 권이 없으면 None."""
    if journal is None or not meta or not meta.get('volume'):
        return None, False
    issue, created = Issue.objects.get_or_create(
        journal=journal, volume=meta['volume'], number=meta.get('issue') or '',
        defaults={'publish_date': meta.get('date') or timezone.localdate()})
    return issue, created


@staff_required
@require_POST
def upload_file(request):
    """PDF 한 개 올리기. mode=auto 면 학술지만 받고, PDF 의 DOI → Crossref 권·호·발행일로 호를 정한다
    (그 호가 없으면 새로 만듦). 아니면 예전처럼 고른 호(issue_id) 또는 새 호(권/호/발행일)."""
    upload = request.FILES.get('file')
    if upload is None or not upload.name.lower().endswith('.pdf'):
        return JsonResponse({'ok': False, 'error': 'PDF 파일만 올릴 수 있습니다.'}, status=400)
    if upload.size > MAX_PDF_BYTES:
        return JsonResponse({'ok': False, 'error': 'PDF 가 너무 큽니다 (최대 40MB).'}, status=400)
    pdf_bytes = upload.read()
    upload.seek(0)
    if not pdf_bytes.startswith(b'%PDF-'):
        return JsonResponse({'ok': False, 'error': 'PDF 파일이 아닙니다.'}, status=400)
    sha1 = hashlib.sha1(pdf_bytes).hexdigest()
    doi, meta = processing.pdf_metadata(pdf_bytes)

    auto = request.POST.get('mode') == 'auto'
    created_issue = False
    if auto:
        journal = Journal.objects.filter(pk=request.POST.get('journal_id') or 0).first()
        if journal is None:
            return JsonResponse({'ok': False, 'error': '학술지를 고르세요.'}, status=400)
        issue, created_issue = _auto_issue(journal, meta)
        if issue is None:
            why = ('PDF 에서 DOI 를 찾지 못했습니다' if not doi else
                   'Crossref 에서 논문 정보를 찾지 못했습니다' if not meta else
                   '아직 권·호가 없는 온라인 선공개 논문입니다')
            return JsonResponse({'ok': False, 'need_issue': True,
                                 'error': f'{why} - 호를 직접 골라 다시 올려 주세요.'}, status=400)
        existing = Paper.objects.filter(issue__journal=journal, source_sha1=sha1).select_related('issue').first()
    else:
        issue = _issue_from_request(request.POST)
        if issue is None:
            return JsonResponse({'ok': False, 'error': '학술지와 권(Volume)을 입력하거나 기존 호를 고르세요.'}, status=400)
        existing = issue.papers.filter(source_sha1=sha1).first()
    if existing:
        return JsonResponse({'ok': True, 'duplicate': True, 'issue': _issue_row(existing.issue),
                             'paper': _paper_row(existing)})

    # 처리 전 제목: Crossref 제목, 없으면 파일 이름 ('01_' 같은 앞 번호·밑줄 정리)
    title = re.sub(r'^\d+[\s._-]+', '', Path(upload.name).stem).replace('_', ' ').strip() or Path(upload.name).stem
    order = (issue.papers.aggregate(Max('order'))['order__max'] or 0) + 1
    paper = Paper(issue=issue, title=((meta or {}).get('title') or title)[:500], authors=((meta or {}).get('authors') or '')[:500],
                  doi=(doi or '')[:255], order=order, source_sha1=sha1,
                  processing_status='pending', processing_message='요약 대기 중',
                  processing_updated=timezone.now())
    paper.pdf_file.save(upload.name, upload, save=False)
    paper.save()
    processing.start_worker()
    return JsonResponse({'ok': True, 'issue': _issue_row(issue), 'created_issue': created_issue,
                         'journal_mismatch': bool(auto and meta and meta.get('journal') and not _same_journal(issue.journal, meta['journal'])),
                         'crossref_journal': (meta or {}).get('journal', ''),
                         'paper': _paper_row(paper)})


def _same_journal(journal, crossref_name):
    """고른 학술지와 Crossref 의 학술지 이름이 대충 같은지 (단어가 하나라도 겹치거나 약어가 들어 있으면 같다고 봄)."""
    words = lambda s: {w for w in re.findall(r'[a-z]{3,}', s.lower()) if w not in ('the', 'and', 'journal', 'for', 'international')}
    mine, theirs = words(f'{journal.name} {journal.slug}'), words(crossref_name)
    initials = ''.join(w[0] for w in re.findall(r'[A-Za-z]+', crossref_name) if w.lower() not in ('of', 'the', 'and', 'for'))
    return bool(mine & theirs) or journal.slug.lower() in initials.lower() or journal.name.lower() in initials.lower()


def _ids(value):
    return [int(x) for x in re.findall(r'\d+', str(value or ''))][:500]


@staff_required
def processing_status(request):
    """호 하나(issue=) 또는 이번에 올린 논문들(papers=1,2,3 - 자동 모드는 여러 호에 나뉘어 들어감)."""
    ids = _ids(request.GET.get('papers'))
    issue = None
    if ids:
        qs = Paper.objects.filter(pk__in=ids).select_related('issue__journal').order_by('issue_id', 'order', 'id')
    else:
        issue = Issue.objects.filter(pk=request.GET.get('issue') or 0).first()
        if issue is None:
            return JsonResponse({'ok': False, 'error': 'Issue not found'}, status=404)
        qs = issue.papers.select_related('issue__journal')
    papers = [_paper_row(p) for p in qs]
    if any(p['status'] in ('pending', 'running') for p in papers):
        processing.start_worker()     # 서버가 재시작돼 멈춘 작업도 다시 이어서
    return JsonResponse({'ok': True, 'issue': _issue_row(issue) if issue else None, 'papers': papers})


@staff_required
@require_POST
def processing_action(request):
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    ids = _ids(data.get('papers'))
    if ids:
        papers = Paper.objects.filter(pk__in=ids)
    else:
        issue = Issue.objects.filter(pk=data.get('issue') or 0).first()
        if issue is None:
            return JsonResponse({'ok': False, 'error': 'Issue not found'}, status=404)
        papers = issue.papers.all()
    papers = papers.exclude(processing_status__in=('pending', 'running')).exclude(pdf_file='')
    if data.get('action') == 'retry':
        papers = papers.filter(processing_status='error')
    elif data.get('action') == 'summarize_missing':
        papers = papers.filter(ai_summary='')
    elif data.get('action') == 'resummarize' and data.get('paper'):
        papers = papers.filter(pk=data['paper'])
    else:
        return JsonResponse({'ok': False, 'error': 'Invalid action'}, status=400)
    count = papers.update(processing_status='pending', processing_message='요약 대기 중',
                          processing_updated=timezone.now(), next_attempt_at=None)
    if count:
        processing.start_worker()
    return JsonResponse({'ok': True, 'queued': count})


@csrf_exempt
def process_tick(request):
    """GitHub Actions 가 30분마다 부르는 주소: 잠든 서버를 깨우고, 다시 시도할 때가 된 논문을 이어서 처리.
    헤더 X-Cron-Token 이 settings.JOURNAL_CRON_TOKEN 과 같아야 함 (설정이 비어 있으면 꺼짐)."""
    token = settings.JOURNAL_CRON_TOKEN
    if not token:
        raise Http404
    if not hmac.compare_digest(request.headers.get('X-Cron-Token', ''), token):
        return JsonResponse({'ok': False}, status=403)
    now = timezone.now()
    pending = Paper.objects.filter(processing_status__in=('pending', 'running'))
    due = processing._due_pending(now).count()
    if due or pending.filter(processing_status='running').exists():
        processing.start_worker()
    upcoming = processing.next_due_at()
    return JsonResponse({'ok': True, 'pending': pending.count(), 'due_now': due,
                         'next_attempt_at': upcoming.isoformat() if upcoming else None})

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404

from accounts.decorators import user_is_approved
from anhub.storage_backends import generate_paper_url
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

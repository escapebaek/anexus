from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from journal.models import Issue, Paper


class Command(BaseCommand):
    help = (
        "Bulk-import papers into a specific journal issue from a folder.\n"
        "For each PDF, place a sidecar text file with the same base name "
        "(e.g. paper1.pdf + paper1.txt) formatted as:\n"
        "  Title: <title>\n"
        "  Authors: <authors>\n"
        "  ===\n"
        "  <AI summary text, can span multiple lines>\n"
        "If no sidecar file is found, the filename is used as the title and "
        "authors/summary are left blank.\n"
        "Papers are assigned an incrementing 'order' continuing after whatever "
        "already exists in the issue, in the order the PDF files are processed "
        "(alphabetical by filename) - prefix filenames like 01_, 02_ to control it.\n"
        "Run with --list-issues to see the id / slug:volume:number reference for "
        "every existing issue."
    )

    def add_arguments(self, parser):
        parser.add_argument('folder', nargs='?', help='Folder containing PDFs and matching .txt sidecar files')
        parser.add_argument(
            '--issue',
            help='Target issue: its database id, or "<journal-slug>:<volume>:<number>"',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Preview what would be imported without saving or uploading anything',
        )
        parser.add_argument(
            '--list-issues', action='store_true',
            help='List every issue with its id and slug:volume:number reference, then exit',
        )

    def handle(self, *args, **options):
        if options['list_issues']:
            self._print_issues()
            return

        if not options['folder'] or not options['issue']:
            raise CommandError('folder and --issue are required (or pass --list-issues alone)')

        folder = Path(options['folder'])
        if not folder.is_dir():
            raise CommandError(f"Folder not found: {folder}")

        issue = self._resolve_issue(options['issue'])
        dry_run = options['dry_run']

        pdf_files = sorted(folder.glob('*.pdf'))
        if not pdf_files:
            self.stdout.write(self.style.WARNING(f"No PDF files found in {folder}"))
            return

        next_order = issue.papers.aggregate(Max('order'))['order__max'] or 0

        created = 0
        for pdf_path in pdf_files:
            next_order += 1
            meta_path = pdf_path.with_suffix('.txt')
            title, authors, summary = self._parse_sidecar(meta_path, fallback_title=pdf_path.stem)

            flag = '' if meta_path.exists() else '  [no sidecar .txt found]'
            self.stdout.write(f"- (order={next_order}) {pdf_path.name} -> \"{title}\" ({authors or 'no authors'}){flag}")

            if dry_run:
                continue

            paper = Paper(issue=issue, title=title, authors=authors, ai_summary=summary, order=next_order)
            with open(pdf_path, 'rb') as fh:
                paper.pdf_file.save(pdf_path.name, File(fh), save=False)
            paper.save()
            created += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Dry run: would import {len(pdf_files)} paper(s) into {issue}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Imported {created} paper(s) into {issue}"))

    def _print_issues(self):
        issues = Issue.objects.select_related('journal').order_by('journal__name', '-publish_date')
        if not issues:
            self.stdout.write('No issues found yet - create a Journal and an Issue in /admin/ first.')
            return
        for issue in issues:
            ref = f"{issue.journal.slug}:{issue.volume}:{issue.number}"
            self.stdout.write(f'id={issue.pk:<5} --issue "{ref}"   ({issue})')

    def _resolve_issue(self, ref):
        if ref.isdigit():
            try:
                return Issue.objects.get(pk=int(ref))
            except Issue.DoesNotExist:
                raise CommandError(f"Issue id {ref} not found")

        parts = ref.split(':')
        if len(parts) != 3:
            raise CommandError('Use --issue <id> or --issue "<journal-slug>:<volume>:<number>"')
        slug, volume, number = parts
        try:
            return Issue.objects.get(journal__slug=slug, volume=volume, number=number)
        except Issue.DoesNotExist:
            raise CommandError(f"No issue found for journal '{slug}' volume '{volume}' number '{number}'")

    def _parse_sidecar(self, meta_path, fallback_title):
        if not meta_path.exists():
            return fallback_title, '', ''

        title = fallback_title
        authors = ''
        summary_lines = []
        in_summary = False

        for line in meta_path.read_text(encoding='utf-8').splitlines():
            if in_summary:
                summary_lines.append(line)
                continue
            if line.strip() == '===':
                in_summary = True
                continue
            if line.lower().startswith('title:'):
                title = line.split(':', 1)[1].strip() or fallback_title
            elif line.lower().startswith('authors:'):
                authors = line.split(':', 1)[1].strip()

        return title, authors, '\n'.join(summary_lines).strip()

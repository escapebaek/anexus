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
        "  Summary: <one-line short summary, shown in the issue paper list>\n"
        "  ===\n"
        "  <full multi-paragraph AI summary, shown on the paper detail page>\n"
        "If no sidecar file is found, the filename is used as the title and "
        "authors/summaries are left blank.\n"
        "Papers are assigned an incrementing 'order' continuing after whatever "
        "already exists in the issue, in the order the PDF files are processed "
        "(alphabetical by filename) - prefix filenames like 01_, 02_ to control it.\n"
        "Safe to re-run on a folder you've already imported: any PDF whose parsed "
        "title already exists in this issue is skipped automatically (pass --force "
        "to re-import it anyway and create a duplicate row).\n"
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
        parser.add_argument(
            '--force', action='store_true',
            help='Import even if a paper with the same title already exists in this issue '
                 '(creates a duplicate row instead of skipping)',
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
        existing_titles = set(issue.papers.values_list('title', flat=True))
        force = options['force']

        created = 0
        skipped = 0
        for pdf_path in pdf_files:
            meta_path = pdf_path.with_suffix('.txt')
            title, authors, short_summary, full_summary = self._parse_sidecar(
                meta_path, fallback_title=pdf_path.stem
            )

            if title in existing_titles and not force:
                self.stdout.write(f"- {pdf_path.name} -> \"{title}\"  [SKIPPED: already in this issue]")
                skipped += 1
                continue

            next_order += 1
            flag = '' if meta_path.exists() else '  [no sidecar .txt found]'
            no_summary_flag = '' if (short_summary or full_summary) else '  [no summary parsed]'
            self.stdout.write(
                f"- (order={next_order}) {pdf_path.name} -> \"{title}\" "
                f"({authors or 'no authors'}){flag}{no_summary_flag}"
            )
            existing_titles.add(title)

            if dry_run:
                created += 1
                continue

            paper = Paper(
                issue=issue, title=title, authors=authors,
                short_summary=short_summary, ai_summary=full_summary, order=next_order,
            )
            with open(pdf_path, 'rb') as fh:
                paper.pdf_file.save(pdf_path.name, File(fh), save=False)
            paper.save()
            created += 1

        verb = 'would import' if dry_run else 'Imported'
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {created} new paper(s), skipped {skipped} already-existing, into {issue}"
        ))

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
            return fallback_title, '', '', ''

        title = fallback_title
        authors = ''
        short_summary = ''
        summary_lines = []
        in_summary = False

        for raw_line in meta_path.read_text(encoding='utf-8').splitlines():
            # Tolerate markdown noise (e.g. "**Title:**") pasted straight from a chat UI.
            clean = raw_line.replace('**', '').replace('#', '').strip()

            if in_summary:
                summary_lines.append(raw_line)
                continue

            separator_chars = set(clean)
            if clean and separator_chars <= {'=', '-'} and len(clean) >= 3:
                in_summary = True
                continue

            if clean.lower().startswith('title:'):
                title = clean.split(':', 1)[1].strip() or fallback_title
            elif clean.lower().startswith('authors:'):
                authors = clean.split(':', 1)[1].strip()
            elif clean.lower().startswith('summary:'):
                short_summary = clean.split(':', 1)[1].strip()

        full_summary = '\n'.join(summary_lines).strip()
        return title, authors, short_summary, full_summary

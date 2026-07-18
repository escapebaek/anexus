from django.db import models
from django.urls import reverse
from django.utils import timezone

from anhub.storage_backends import PaperStorage


class Journal(models.Model):
    name = models.CharField(max_length=255, verbose_name='Journal Name')
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True, verbose_name='Description')
    cover_image = models.ImageField(upload_to='journal_covers/', blank=True, null=True, verbose_name='Cover Image')
    is_active = models.BooleanField(default=True, verbose_name='Active')
    order = models.PositiveIntegerField(default=0, verbose_name='Order')

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Journal'
        verbose_name_plural = 'Journals'

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('journal:journal_detail', args=[self.slug])

    @property
    def latest_issue(self):
        return self.issues.order_by('-publish_date').first()


class Issue(models.Model):
    journal = models.ForeignKey(Journal, related_name='issues', on_delete=models.CASCADE, verbose_name='Journal')
    volume = models.CharField(max_length=50, blank=True, verbose_name='Volume')
    number = models.CharField(max_length=50, blank=True, verbose_name='Number')
    publish_date = models.DateField(default=timezone.now, verbose_name='Publish Date')
    cover_image = models.ImageField(upload_to='issue_covers/', blank=True, null=True, verbose_name='Cover Image')

    class Meta:
        ordering = ['-publish_date']
        verbose_name = 'Issue'
        verbose_name_plural = 'Issues'

    def __str__(self):
        label = ' '.join(p for p in [
            f"Vol.{self.volume}" if self.volume else '',
            f"No.{self.number}" if self.number else '',
        ] if p)
        return f"{self.journal.name} {label}".strip()

    def get_absolute_url(self):
        return reverse('journal:issue_detail', args=[self.journal.slug, self.pk])


class Paper(models.Model):
    issue = models.ForeignKey(Issue, related_name='papers', on_delete=models.CASCADE, verbose_name='Issue')
    title = models.CharField(max_length=500, verbose_name='Title')
    authors = models.CharField(max_length=500, blank=True, verbose_name='Authors')
    ai_summary = models.TextField(blank=True, verbose_name='AI Summary')
    pdf_file = models.FileField(
        upload_to='papers/', storage=PaperStorage(), blank=True, null=True, verbose_name='PDF File'
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Order')
    created_date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['order', '-created_date']
        verbose_name = 'Paper'
        verbose_name_plural = 'Papers'

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('journal:paper_detail', args=[self.pk])

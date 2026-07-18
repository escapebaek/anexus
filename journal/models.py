from django.db import models
from django.urls import reverse
from django.utils import timezone

from anhub.storage_backends import PaperStorage


class Journal(models.Model):
    name = models.CharField(max_length=255, verbose_name='학술지명')
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True, verbose_name='소개')
    cover_image = models.ImageField(upload_to='journal_covers/', blank=True, null=True, verbose_name='표지 이미지')
    is_active = models.BooleanField(default=True, verbose_name='공개 여부')
    order = models.PositiveIntegerField(default=0, verbose_name='정렬 순서')

    class Meta:
        ordering = ['order', 'name']
        verbose_name = '학술지'
        verbose_name_plural = '학술지'

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('journal:journal_detail', args=[self.slug])

    @property
    def latest_issue(self):
        return self.issues.order_by('-publish_date').first()


class Issue(models.Model):
    journal = models.ForeignKey(Journal, related_name='issues', on_delete=models.CASCADE, verbose_name='학술지')
    volume = models.CharField(max_length=50, blank=True, verbose_name='권(Volume)')
    number = models.CharField(max_length=50, blank=True, verbose_name='호(Number)')
    publish_date = models.DateField(default=timezone.now, verbose_name='발행일')
    cover_image = models.ImageField(upload_to='issue_covers/', blank=True, null=True, verbose_name='표지 이미지')

    class Meta:
        ordering = ['-publish_date']
        verbose_name = '호'
        verbose_name_plural = '호'

    def __str__(self):
        label = ' '.join(p for p in [
            f"Vol.{self.volume}" if self.volume else '',
            f"No.{self.number}" if self.number else '',
        ] if p)
        return f"{self.journal.name} {label}".strip()

    def get_absolute_url(self):
        return reverse('journal:issue_detail', args=[self.journal.slug, self.pk])


class Paper(models.Model):
    issue = models.ForeignKey(Issue, related_name='papers', on_delete=models.CASCADE, verbose_name='호')
    title = models.CharField(max_length=500, verbose_name='제목')
    authors = models.CharField(max_length=500, blank=True, verbose_name='저자')
    ai_summary = models.TextField(blank=True, verbose_name='AI 요약')
    pdf_file = models.FileField(
        upload_to='papers/', storage=PaperStorage(), blank=True, null=True, verbose_name='PDF 파일'
    )
    order = models.PositiveIntegerField(default=0, verbose_name='정렬 순서')
    created_date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['order', '-created_date']
        verbose_name = '논문'
        verbose_name_plural = '논문'

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('journal:paper_detail', args=[self.pk])

# board/models.py

from django.db import models
from django.utils import timezone
from ckeditor.fields import RichTextField
from django.conf import settings

class Board(models.Model):
    id = models.IntegerField(primary_key=True, editable=False)
    title = models.CharField(max_length=255, default='default')
    contents = RichTextField(default='default')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_date = models.DateTimeField(default=timezone.now)
    modified_date = models.DateTimeField(default=timezone.now)
    is_notice = models.BooleanField(default=False, verbose_name='공지사항')  # 공지사항 여부 필드 추가
    
    def save(self, *args, **kwargs):
        # 수정 시간 자동 업데이트
        if self.pk:  # 기존 글을 수정하는 경우
            self.modified_date = timezone.now()
            
        if self.id is None:  # 새로운 인스턴스인 경우
            last_entry = Board.objects.order_by('id').last()
            if last_entry:
                self.id = last_entry.id + 1
            else:
                self.id = 1  # 첫 번째 글의 경우 ID는 1
        super().save(*args, **kwargs)

    def __str__(self):
        notice_prefix = "[공지] " if self.is_notice else ""
        return f"{notice_prefix}{self.title}"

    class Meta:
        ordering = ['-is_notice', '-id']  # 공지사항이 먼저, 그 다음 ID 역순

class Comment(models.Model):
    board = models.ForeignKey(Board, related_name='comments', on_delete=models.CASCADE)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content = models.TextField()
    created_date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Comment by {self.author} on {self.board}"
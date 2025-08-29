# board/models.py

from django.db import models
from django.utils import timezone
from mdeditor.fields import MDTextField
from django.conf import settings

class Board(models.Model):
    id = models.IntegerField(primary_key=True, editable=False)
    title = models.CharField(max_length=255, default='default')
    contents = MDTextField(default='default')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_date = models.DateTimeField(default=timezone.now)
    modified_date = models.DateTimeField(default=timezone.now)
    
    def save(self, *args, **kwargs):
        if self.id is None:
            last_entry = Board.objects.order_by('id').last()
            if last_entry:
                self.id = last_entry.id + 1
            else:
                self.id = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

class Comment(models.Model):
    board = models.ForeignKey(Board, related_name='comments', on_delete=models.CASCADE)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content = models.TextField()
    created_date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Comment by {self.author} on {self.board}"
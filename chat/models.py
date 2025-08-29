# chat/models.py - 즉시 사용 가능한 버전
from django.db import models
from django.conf import settings

class ChatRoom(models.Model):
    name = models.CharField(max_length=255, unique=True)
    password = models.CharField(max_length=100, blank=True, null=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_rooms')

    class Meta:
        db_table = 'chat_chatroom'

    def __str__(self):
        return self.name

class Message(models.Model):
    room = models.ForeignKey(ChatRoom, related_name='messages', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    user_username = models.CharField(max_length=150, blank=True)
    
    class Meta:
        db_table = 'chat_message'
        ordering = ['timestamp']
    
    def save(self, *args, **kwargs):
        # Automatically set username when saving
        if not self.user_username and self.user:
            self.user_username = self.user.username
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f'{self.user.username}: {self.content[:20]}'
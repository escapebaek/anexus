from django.db import models
from django.conf import settings

# Models for storing drug search history if needed
class DrugSearchHistory(models.Model):
    query = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )
    
    class Meta:
        ordering = ['-timestamp']
        
    def __str__(self):
        return f"{self.query} - {self.timestamp.strftime('%Y-%m-%d %H:%M')}"
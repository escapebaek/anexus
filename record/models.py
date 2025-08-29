from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User  # 추가
from django.conf import settings  # 추가

class AnesthesiaRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=1)
    patient_id = models.CharField(max_length=50, default="unknown")
    timestamp = models.DateTimeField(default=timezone.now)
    hr = models.IntegerField(null=True, blank=True)
    sbp = models.IntegerField(null=True, blank=True)
    dbp = models.IntegerField(null=True, blank=True)
    spo2 = models.IntegerField(null=True, blank=True)
    extra_vitals = models.JSONField(blank=True, null=True, default=dict)
    additional_notes = models.TextField(blank=True)

    def __str__(self):
        return f"Record for {self.patient_id} at {self.timestamp}"

# 만약 Free Text Note도 사용자별로 관리하려면:
class FreeTextNote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)  # 수정됨
    content = models.TextField(blank=True)
    
    def __str__(self):
        return self.content[:50]

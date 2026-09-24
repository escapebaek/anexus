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


class AnesthesiaCase(models.Model):
    """사용자별 현재 마취 케이스 정보 (환자정보, 마취정보, 이벤트, 행 구성)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='anesthesia_case')
    # 환자/수술 정보: patient_name, sex, age, height, weight, blood_type, operation, surgeon, anesthesiologist, ...
    info = models.JSONField(blank=True, default=dict)
    # 이벤트 목록: [{"time": "YYYY-MM-DDTHH:MM", "label": "Induction"}, ...]
    events = models.JSONField(blank=True, default=list)
    # 추가 행 구성: [{"name": "EtCO2", "group": "gas", "unit": "mmHg"}, ...]
    rows = models.JSONField(blank=True, default=list)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Case of {self.user} ({self.info.get('patient_name', '')})"


class RecordTemplate(models.Model):
    """사용자가 저장해 두는 마취기록 서식 (마취정보, 항목 구성, 기록 문구 등)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='record_templates')
    name = models.CharField(max_length=60)
    # {"info": {...}, "rows": [...], "note": "..."}
    data = models.JSONField(blank=True, default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['user', 'name'], name='unique_record_template_name')]

    def __str__(self):
        return f"{self.name} ({self.user})"

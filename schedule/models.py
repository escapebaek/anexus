from django.db import models
from django.conf import settings

class SurgerySchedule(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='surgery_schedules',
        null=True,  # Allow null values for existing records
        blank=True
    )
    date = models.DateField()
    room = models.CharField(max_length=10)
    time_slot = models.CharField(max_length=10)
    surgery_name = models.CharField(max_length=200)
    department = models.CharField(max_length=50)
    surgeon = models.CharField(max_length=50)
    duration = models.IntegerField()
    patient_name = models.CharField(max_length=50)
    patient_info = models.CharField(max_length=20)
    status = models.CharField(max_length=50, default="예정")

    def __str__(self):
        return f"{self.date} - {self.room} - {self.surgery_name} ({self.status})"
    
class PatientMemo(models.Model):
    schedule = models.ForeignKey(
        SurgerySchedule,
        on_delete=models.CASCADE,
        related_name='memos'
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'patient_memos'  # Specify table name for Supabase
        
    def __str__(self):
        return f"Memo for {self.schedule.patient_name} ({self.created_at})"
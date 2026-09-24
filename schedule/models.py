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
    # 마취의: 업로드 파일에 있으면 채우고, 없으면 현황판에서 직접 입력 (업데이트 시 빈 값으로 덮어쓰지 않음)
    anesthesiologist = models.CharField(max_length=50, blank=True, default="")
    duration = models.IntegerField()
    patient_name = models.CharField(max_length=50)
    patient_info = models.CharField(max_length=20)
    status = models.CharField(max_length=50, default="예정")

    def __str__(self):
        return f"{self.date} - {self.room} - {self.surgery_name} ({self.status})"
    
class RoomFlag(models.Model):
    """사용자가 현황판에서 방에 직접 지정하는 표시: 당직으로 넘길 방 / Hold 방.
    스케줄 '업데이트'에는 유지되고 '전체 교체' 시 초기화된다."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='room_flags')
    room = models.CharField(max_length=10)
    on_call = models.BooleanField(default=False)
    hold = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'room'], name='unique_room_flag')]

    def __str__(self):
        return f"{self.user} {self.room} (on_call={self.on_call}, hold={self.hold})"


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
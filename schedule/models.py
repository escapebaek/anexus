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
    # 마취 방법 코드: GA/SA/EA/CSE/BL/MAC/LA (그 밖의 값은 원문 그대로)
    anesthesia_type = models.CharField(max_length=20, blank=True, default="")
    duration = models.IntegerField()
    patient_name = models.CharField(max_length=50)
    patient_info = models.CharField(max_length=20)
    status = models.CharField(max_length=50, default="예정")
    # 현황판에서 수동으로 상태를 바꾼 경우 True - 스케줄 업데이트 파일의 상태로 덮어쓰지 않음
    status_locked = models.BooleanField(default=False)
    # 현황판에서 수술 단위로 지정: 당직으로 넘길 수술 / Hold 수술 (업데이트 시 유지)
    on_call = models.BooleanField(default=False)
    hold = models.BooleanField(default=False)
    # 현황판에서 직접 정한 방 안 순서 (0 = 지정 안 함 -> 시간 순으로 뒤에). 스케줄 업데이트 시 초기화.
    position = models.PositiveIntegerField(default=0)
    # 현황판에서 '진행중'으로 바꾼 시각 (+ duration = 종료 예정) / '완료'로 바꾼 시각. 업데이트 시 유지.
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

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

class ScheduleUploadJob(models.Model):
    """AI 분석이 필요한 업로드를 백그라운드에서 처리하는 작업 (요청 시간 초과 방지)."""
    STATUS_CHOICES = [("running", "처리 중"), ("done", "완료"), ("error", "오류")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='schedule_upload_jobs')
    filename = models.CharField(max_length=255, blank=True)
    action = models.CharField(max_length=10, default="update")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="running")
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} {self.filename} ({self.status})"


class BoardNotice(models.Model):
    """현황판 오른쪽의 공지·메모 칸 (사용자별 한 개, 일정 업로드와 무관하게 유지)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='board_notice')
    content = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Notice of {self.user}"

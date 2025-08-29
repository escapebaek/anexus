from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from .models import SurgerySchedule
from .forms import ExcelUploadForm
from collections import defaultdict
import pandas as pd
from .models import SurgerySchedule, PatientMemo
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
import json
import logging
from collections import defaultdict

@login_required
def schedule_dashboard(request):
    form = ExcelUploadForm()
    schedules = SurgerySchedule.objects.filter(user=request.user).order_by("date", "room", "time_slot")
    
    schedule_by_room = defaultdict(list)
    for schedule in schedules:
        schedule_by_room[schedule.room].append(schedule)

    # Build a summary dictionary for each room:
    summary_by_room = {}
    for room, schedules in schedule_by_room.items():
        summary = {'ongoing': None, 'pending': 0, 'finished': 0}
        for schedule in schedules:
            if schedule.status in ["진행중", "수술중"]:
                # pick the first ongoing surgery (if any)
                if summary['ongoing'] is None:
                    summary['ongoing'] = schedule
            elif schedule.status == "완료":
                summary['finished'] += 1
            else:
                summary['pending'] += 1
        summary_by_room[room] = summary

    if request.method == "POST":
        action = request.POST.get('action', 'replace')  # 'replace' 또는 'update'
        form = ExcelUploadForm(request.POST, request.FILES)
        if form.is_valid():
            excel_file = request.FILES["file"]
            df = pd.read_excel(excel_file, sheet_name="Sheet1")
            if action == 'replace':
                SurgerySchedule.objects.filter(user=request.user).delete()
                create_schedules_from_dataframe(df, request.user)
            else:
                update_schedules_from_dataframe(df, request.user)
            return redirect("schedule_dashboard")

    return render(request, "schedule/dashboard.html", {
        "schedule_by_room": dict(schedule_by_room),
        "summary_by_room": summary_by_room,
        "form": form
    })

def create_schedules_from_dataframe(df, user):
    """DataFrame에서 새로운 스케줄을 생성하는 헬퍼 함수"""
    for _, row in df.iterrows():
        SurgerySchedule.objects.create(
            user=user,
            date=row["날짜"],
            room=row["방"],
            time_slot=row["시간"],
            surgery_name=row["수술명"],
            department=row["진료과"],
            surgeon=row["집도의"],
            duration=row["수술 시간"],
            patient_name=row["환자명"],
            patient_info=row["환자정보"],
            status=row["진행 상황"]
        )

def update_schedules_from_dataframe(df, user):
    """DataFrame을 사용하여 기존 스케줄을 업데이트하는 헬퍼 함수"""
    # 날짜 형식 통일
    df['날짜'] = pd.to_datetime(df['날짜']).dt.date
    
    # 비교를 위한 기존 스케줄 가져오기
    existing_schedules = SurgerySchedule.objects.filter(user=user)
    
    # 각 스케줄의 고유 식별을 위한 키 생성
    existing_keys = {
        (schedule.date, schedule.room, schedule.time_slot): schedule 
        for schedule in existing_schedules
    }
    
    # 새로운 데이터 처리
    for _, row in df.iterrows():
        key = (row["날짜"], row["방"], row["시간"])
        
        if key in existing_keys:
            # 기존 스케줄이 있으면 업데이트
            schedule = existing_keys[key]
            # 변경사항이 있는지 확인
            if (schedule.surgery_name != row["수술명"] or
                schedule.department != row["진료과"] or
                schedule.surgeon != row["집도의"] or
                schedule.duration != row["수술 시간"] or
                schedule.patient_name != row["환자명"] or
                schedule.patient_info != row["환자정보"] or
                schedule.status != row["진행 상황"]):
                
                # 변경사항이 있을 경우만 업데이트
                schedule.surgery_name = row["수술명"]
                schedule.department = row["진료과"]
                schedule.surgeon = row["집도의"]
                schedule.duration = row["수술 시간"]
                schedule.patient_name = row["환자명"]
                schedule.patient_info = row["환자정보"]
                schedule.status = row["진행 상황"]
                schedule.save()
        else:
            # 새로운 스케줄 생성
            SurgerySchedule.objects.create(
                user=user,
                date=row["날짜"],
                room=row["방"],
                time_slot=row["시간"],
                surgery_name=row["수술명"],
                department=row["진료과"],
                surgeon=row["집도의"],
                duration=row["수술 시간"],
                patient_name=row["환자명"],
                patient_info=row["환자정보"],
                status=row["진행 상황"]
            )
    
logger = logging.getLogger(__name__)

@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def handle_memo(request, schedule_id):
    try:
        schedule = SurgerySchedule.objects.get(id=schedule_id)
    except SurgerySchedule.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Schedule not found'
        }, status=404)

    if request.method == "GET":
        memo = PatientMemo.objects.filter(schedule_id=schedule_id).first()
        return JsonResponse({
            'status': 'success',
            'content': memo.content if memo else ''
        })
    
    elif request.method == "POST":
        try:
            data = json.loads(request.body)
            content = data.get('content', '')
            
            memo, created = PatientMemo.objects.update_or_create(
                schedule=schedule,
                defaults={'content': content}
            )
            
            return JsonResponse({
                'status': 'success',
                'message': 'Memo saved successfully'
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            logger.error(f"Error saving memo: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)

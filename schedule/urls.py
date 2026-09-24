from django.urls import path
from .views import schedule_dashboard
from . import views


urlpatterns = [
    path('dashboard/', schedule_dashboard, name='schedule_dashboard'),
    path('api/memos/<int:schedule_id>/', views.handle_memo, name='handle_memo'),
    path('memos/<int:schedule_id>/', views.handle_memo, name='handle_memo'),
    path('api/schedules/<int:schedule_id>/', views.update_schedule, name='schedule_update'),
    path('api/upload-jobs/<int:job_id>/', views.upload_job_status, name='schedule_upload_job'),
    path('api/notice/', views.save_notice, name='schedule_notice'),
]

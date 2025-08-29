from django.urls import path
from .views import schedule_dashboard
from . import views


urlpatterns = [
    path('dashboard/', schedule_dashboard, name='schedule_dashboard'),
    path('api/memos/<int:schedule_id>/', views.handle_memo, name='handle_memo'),
    path('memos/<int:schedule_id>/', views.handle_memo, name='handle_memo'),
]
from django.urls import path
from . import views

app_name = 'journal'

urlpatterns = [
    path('', views.journal_stand, name='journal_stand'),
    path('upload/', views.upload_page, name='upload'),
    path('upload/file/', views.upload_file, name='upload_file'),
    path('upload/status/', views.processing_status, name='processing_status'),
    path('upload/action/', views.processing_action, name='processing_action'),
    path('paper/<int:pk>/', views.paper_detail, name='paper_detail'),
    path('<slug:slug>/', views.journal_detail, name='journal_detail'),
    path('<slug:slug>/issue/<int:issue_pk>/', views.issue_detail, name='issue_detail'),
]

from django.urls import path
from . import views

app_name = 'journal'

urlpatterns = [
    path('', views.journal_stand, name='journal_stand'),
    path('paper/<int:pk>/', views.paper_detail, name='paper_detail'),
    path('<slug:slug>/', views.journal_detail, name='journal_detail'),
    path('<slug:slug>/issue/<int:issue_pk>/', views.issue_detail, name='issue_detail'),
]

# board/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.board_index, name='board_index'),
    path('<int:pk>/', views.board_detail, name='board_detail'),
    path('<int:pk>/edit/', views.board_edit, name='board_edit'),
    path('<int:pk>/delete/', views.board_delete, name='board_delete'),
    path('create/', views.board_create, name='board_create'),
    path('comment/<int:comment_id>/edit/', views.comment_edit, name='comment_edit'),
    path('comment/<int:comment_id>/delete/', views.comment_delete, name='comment_delete'),
]
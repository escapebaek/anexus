# chat/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.lobby, name='lobby'),
    path('create/', views.create_room, name='create_room'),
    path('<str:room_name>/', views.chat_room, name='chat_room'),
    path('check_password/<str:room_name>/', views.check_room_password, name='check_room_password'),
    path('room_access/<str:room_name>/', views.check_room_access, name='check_room_access'),
    path('delete/<str:room_name>/', views.delete_room, name='delete_room'),
]
from django.urls import path
from . import views

urlpatterns = [
    path('', views.lobby, name='lobby'),
    path('create/', views.create_room, name='create_room'),
    path('leave/<str:room_name>/', views.leave_room, name='leave_room'),
    path('delete/<str:room_name>/', views.delete_room, name='delete_room'),
    path('<str:room_name>/', views.chat_room, name='chat_room'),
    path('check_password/<str:room_name>/', views.check_room_password, name='check_room_password'),
    # API endpoints for Supabase integration
    path('api/send_message/<str:room_name>/', views.send_message, name='send_message'),
    path('api/get_messages/<str:room_name>/', views.get_messages, name='get_messages'),
]
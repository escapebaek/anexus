# chat/views.py - 시간 포맷팅 문제 해결된 버전

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.views.decorators.http import require_POST
from django.conf import settings
from django.utils import timezone
from decouple import config
from .models import ChatRoom, Message
from .forms import ChatRoomForm
import logging

logger = logging.getLogger(__name__)

def format_timestamp(timestamp):
    """크로스 플랫폼 호환 시간 포맷팅 함수"""
    local_time = timezone.localtime(timestamp)
    
    hour = local_time.hour
    minute = local_time.minute
    
    if hour == 0:
        formatted_hour = 12
        am_pm = '오전'
    elif hour < 12:
        formatted_hour = hour
        am_pm = '오전'
    elif hour == 12:
        formatted_hour = 12
        am_pm = '오후'
    else:
        formatted_hour = hour - 12
        am_pm = '오후'
    
    return f"{am_pm} {formatted_hour}:{minute:02d}"

@login_required
def lobby(request):
    rooms = ChatRoom.objects.all().order_by('-id')
    return render(request, 'chat/lobby.html', {'rooms': rooms})

@login_required
def create_room(request):
    if request.method == 'POST':
        form = ChatRoomForm(request.POST)
        if form.is_valid():
            room = form.save(commit=False)
            room.owner = request.user
            room.save()
            return redirect('chat_room', room_name=room.name)
    else:
        form = ChatRoomForm()
    return render(request, 'chat/create_room.html', {'form': form})

@login_required
def check_room_password(request, room_name):
    room = get_object_or_404(ChatRoom, name=room_name)
    if request.method == 'POST':
        password = request.POST.get('password')
        if room.password and password == room.password:
            request.session[f'room_password_{room_name}'] = True
            return JsonResponse({'success': True})
        return JsonResponse({'success': False, 'error': 'Incorrect password'})
    return HttpResponseForbidden()

@login_required
def chat_room(request, room_name):
    room = get_object_or_404(ChatRoom, name=room_name)
    
    # 비밀번호가 설정된 방인 경우 비밀번호 확인
    if room.password and not request.session.get(f'room_password_{room_name}'):
        context = {
            'room': room,
            'requires_password': True,
            'user': request.user
        }
        return render(request, 'chat/room.html', context)
    
    # 기존 메시지들 가져오기
    messages_qs = room.messages.order_by('timestamp').select_related('user')
    
    formatted_messages = []
    for message in messages_qs:
        formatted_time = format_timestamp(message.timestamp)
        
        formatted_messages.append({
            'user': message.user,
            'content': message.content,
            'formatted_time': formatted_time
        })
    
    context = {
        'room': room,
        'messages': formatted_messages,
        'user': request.user,
        'requires_password': False
    }
    return render(request, 'chat/room.html', context)

@login_required
def leave_room(request, room_name):
    room = get_object_or_404(ChatRoom, name=room_name)
    if room.owner == request.user:
        room.delete()
    else:
        room.messages.filter(user=request.user).delete()
    return redirect('lobby')

@login_required
def delete_room(request, room_name):
    room = get_object_or_404(ChatRoom, name=room_name)
    if room.owner == request.user:
        room.delete()
        return redirect('lobby')
    else:
        return HttpResponseForbidden("You are not allowed to delete this room.")

@login_required
def get_messages(request, room_name):
    room = get_object_or_404(ChatRoom, name=room_name)
    messages_qs = room.messages.order_by('timestamp').select_related('user')
    
    messages_data = []
    for message in messages_qs:
        formatted_time = format_timestamp(message.timestamp)
        
        messages_data.append({
            'username': message.user.username,
            'content': message.content,
            'timestamp': formatted_time
        })
    
    return JsonResponse(messages_data, safe=False)

@login_required
def check_room_access(request, room_name):
    room = get_object_or_404(ChatRoom, name=room_name)
    if room.password:
        return render(request, 'chat/password_form.html', {'room': room})
    else:
        return redirect('chat_room', room_name=room_name)
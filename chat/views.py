# chat/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from .models import ChatRoom, Message
from .forms import ChatRoomForm
import logging

logger = logging.getLogger(__name__)

@login_required
def lobby(request):
    rooms = ChatRoom.objects.all()
    logger.debug(f'Rooms: {rooms}')  # 추가된 로깅
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
    """
    AJAX endpoint to check room password
    """
    room = get_object_or_404(ChatRoom, name=room_name)
    if request.method == 'POST':
        password = request.POST.get('password')
        if room.password and password == room.password:
            # Store successful password check in session
            request.session[f'room_password_{room_name}'] = True
            return JsonResponse({'success': True})
        return JsonResponse({'success': False, 'error': 'Incorrect password'})
    return HttpResponseForbidden()

@login_required
def chat_room(request, room_name):
    room = get_object_or_404(ChatRoom, name=room_name)
    
    # Check if room has password and if it's been verified
    if room.password and not request.session.get(f'room_password_{room_name}'):
        return render(request, 'chat/room.html', {'room': room, 'requires_password': True})
    
    if request.method == 'POST':
        message = request.POST.get('message')
        if message:
            Message.objects.create(room=room, user=request.user, content=message)
    
    messages = room.messages.order_by('timestamp')
    return render(request, 'chat/room.html', {'room': room, 'messages': messages})

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
    room = ChatRoom.objects.get(name=room_name)
    messages = room.messages.order_by('timestamp').values('user__username', 'content')
    return JsonResponse(list(messages), safe=False)

@login_required
def check_room_access(request, room_name):
    room = get_object_or_404(ChatRoom, name=room_name)
    if room.password:
        return render(request, 'chat/password_form.html', {'room': room})
    else:
        return redirect('chat_room', room_name=room_name)

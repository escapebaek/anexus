# chat/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.conf import settings
from .models import ChatRoom, Message
from .forms import ChatRoomForm
import logging
import json

logger = logging.getLogger(__name__)

@login_required
def lobby(request):
    rooms = ChatRoom.objects.all()
    logger.debug(f'Rooms: {rooms}')
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
def send_message(request, room_name):
    """
    API endpoint to send messages - 실시간 동기화 개선
    """
    if request.method == 'POST':
        room = get_object_or_404(ChatRoom, name=room_name)
        
        # Check password protection
        if room.password and not request.session.get(f'room_password_{room_name}'):
            return JsonResponse({'success': False, 'error': 'Password required'}, status=403)
        
        try:
            data = json.loads(request.body)
            message_content = data.get('message', '').strip()
            
            if message_content:
                # Save message to database
                message = Message.objects.create(
                    room=room,
                    user=request.user,
                    content=message_content
                )

                # 메시지 데이터를 명확하게 반환 (Supabase가 자동으로 처리)
                return JsonResponse({
                    'success': True,
                    'message': {
                        'id': message.id,
                        'content': message.content,
                        'username': message.user.username,
                        'timestamp': message.timestamp.isoformat(),
                        'room_id': room.id,
                    }
                })
            else:
                return JsonResponse({'success': False, 'error': 'Empty message'}, status=400)
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return JsonResponse({'success': False, 'error': 'Server error'}, status=500)
    
    return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

@login_required
def get_messages(request, room_name):
    """
    API endpoint to get recent messages - ID 기반 필터링으로 변경
    """
    room = get_object_or_404(ChatRoom, name=room_name)
    
    # Check password protection
    if room.password and not request.session.get(f'room_password_{room_name}'):
        return JsonResponse({'success': False, 'error': 'Password required'}, status=403)
    
    try:
        # Get messages from a specific ID if provided (timestamp 대신 ID 사용)
        since_id = request.GET.get('since_id')
        if since_id:
            try:
                since_id = int(since_id)
                messages_qs = room.messages.filter(id__gt=since_id).order_by('timestamp')
            except (ValueError, TypeError):
                logger.warning(f"Invalid message ID: {since_id}")
                messages_qs = room.messages.order_by('timestamp')
        else:
            messages_qs = room.messages.order_by('timestamp')
        
        messages_data = []
        for message in messages_qs:
            messages_data.append({
                'id': message.id,
                'content': message.content,
                'username': message.user.username,
                'timestamp': message.timestamp.isoformat(),
                'room_id': room.id
            })
        
        return JsonResponse({
            'success': True,
            'messages': messages_data
        })
        
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        return JsonResponse({'success': False, 'error': 'Server error'}, status=500)

@login_required
def chat_room(request, room_name):
    room = get_object_or_404(ChatRoom, name=room_name)

    if room.password and not request.session.get(f'room_password_{room_name}'):
        return render(request, 'chat/room.html', {'room': room, 'requires_password': True})

    # 메시지 프레임워크 비우기
    list(messages.get_messages(request))

    chat_messages = room.messages.order_by('timestamp')
    context = {
        'room': room,
        'chat_messages': chat_messages,
        'is_chat_room': True,
        'supabase_url': settings.SUPABASE_URL,
        'supabase_anon_key': settings.SUPABASE_KEY,
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
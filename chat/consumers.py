import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from .models import ChatRoom, Message
from django.utils import timezone

logger = logging.getLogger('chat')

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'chat_{self.room_name}'
        
        # 사용자 인증 확인
        if self.scope['user'].is_anonymous:
            logger.warning(f"Anonymous user tried to connect to room {self.room_name}")
            await self.close()
            return

        self.user = self.scope['user']
        logger.info(f"User {self.user.username} connecting to room {self.room_name}")

        # 방이 존재하는지 확인
        room_exists = await self.check_room_exists()
        if not room_exists:
            logger.warning(f"Room {self.room_name} does not exist")
            await self.close()
            return

        # 그룹에 추가
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
        logger.info(f"User {self.user.username} connected to room {self.room_name}")

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
        logger.info(f"User disconnected from room {getattr(self, 'room_name', 'unknown')}")

    async def receive(self, text_data):
        try:
            text_data_json = json.loads(text_data)
            message = text_data_json.get('message', '').strip()
            
            if not message:
                return
                
            if len(message) > 1000:
                await self.send(text_data=json.dumps({
                    'error': '메시지가 너무 깁니다.'
                }))
                return

            # 메시지 저장
            timestamp = await self.save_message(message)
            if timestamp:
                # 그룹에 브로드캐스트
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': message,
                        'username': self.user.username,
                        'timestamp': timestamp,
                    }
                )
                logger.debug(f"Message sent by {self.user.username} in room {self.room_name}")
            
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON from {self.user.username}")
        except Exception as e:
            logger.error(f"Error in receive: {e}")

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'message': event['message'],
            'username': event['username'],
            'timestamp': event['timestamp'],
        }))

    @database_sync_to_async
    def check_room_exists(self):
        return ChatRoom.objects.filter(name=self.room_name).exists()

    @database_sync_to_async
    def save_message(self, message_content):
        try:
            room = ChatRoom.objects.get(name=self.room_name)
            message = Message.objects.create(
                user=self.user,
                room=room,
                content=message_content
            )
            
            # 크로스 플랫폼 호환 시간 포맷팅
            local_time = timezone.localtime(message.timestamp)
            
            # 12시간 형식으로 포맷팅 (Windows 호환)
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
            
            formatted_time = f"{am_pm} {formatted_hour}:{minute:02d}"
            
            logger.info(f"Message saved successfully: {self.user.username} - {message_content[:20]}...")
            return formatted_time
            
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return None

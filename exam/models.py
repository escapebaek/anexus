from django.db import models
from django.conf import settings  # settings.AUTH_USER_MODEL을 사용하기 위해 추가
from django.contrib.auth import get_user_model  # User 모델을 가져오기 위해 추가
import re

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Exam(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    display_order = models.PositiveIntegerField(default=0, help_text="표시 순서 (숫자가 작을수록 먼저 표시)")

    class Meta:
        ordering = ['display_order', 'date_created']

    def __str__(self):
        return self.title


class Question(models.Model):
    exam = models.ForeignKey(
        Exam, on_delete=models.CASCADE, related_name='questions'
    )
    question_text = models.TextField()
    image = models.ImageField(upload_to='question_images/', blank=True, null=True)
    
    # 새로 추가: 유튜브 동영상 URL 필드
    youtube_url = models.URLField(blank=True, null=True, help_text="유튜브 동영상 URL을 입력하세요")
    
    option1 = models.CharField(max_length=200, default='default')
    option2 = models.CharField(max_length=200, default='default')
    option3 = models.CharField(max_length=200, default='default')
    option4 = models.CharField(max_length=200, default='default')
    option5 = models.CharField(max_length=200, default='default')
    correct_option = models.CharField(max_length=200, default='default')
    comment = models.TextField(default='default')  # Supports multiline comments
    comment_image = models.ImageField(upload_to='question_images/', blank=True, null=True)
    
    # 해설용 유튜브 동영상 URL 필드 (중복 제거)
    comment_youtube_url = models.URLField(blank=True, null=True, help_text="해설용 유튜브 동영상 URL을 입력하세요")
    
    order = models.PositiveIntegerField(default=0)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.question_text
    
    def get_youtube_embed_id(self):
        """유튜브 URL에서 동영상 ID를 추출하는 메서드"""
        if not self.youtube_url:
            return None
        
        url = self.youtube_url.strip()
        
        patterns = [
            # 표준 watch URL: youtube.com/watch?v=VIDEO_ID (v가 처음에 오거나 중간에 오는 경우 모두 처리)
            r'(?:https?://)?(?:www\.)?youtube\.com/watch\?(?:.*&)?v=([a-zA-Z0-9_-]{11})',
            r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
            # 짧은 URL: youtu.be/VIDEO_ID
            r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]{11})',
            # 임베드 URL: youtube.com/embed/VIDEO_ID
            r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})',
            # Shorts URL: youtube.com/shorts/VIDEO_ID
            r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
            # youtube-nocookie.com 임베드
            r'(?:https?://)?(?:www\.)?youtube-nocookie\.com/embed/([a-zA-Z0-9_-]{11})',
            # v/ 형식: youtube.com/v/VIDEO_ID
            r'(?:https?://)?(?:www\.)?youtube\.com/v/([a-zA-Z0-9_-]{11})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def get_comment_youtube_embed_id(self):
        """해설용 유튜브 URL에서 동영상 ID를 추출하는 메서드"""
        if not self.comment_youtube_url:
            return None
        
        url = self.comment_youtube_url.strip()
        
        patterns = [
            # 표준 watch URL: youtube.com/watch?v=VIDEO_ID (v가 처음에 오거나 중간에 오는 경우 모두 처리)
            r'(?:https?://)?(?:www\.)?youtube\.com/watch\?(?:.*&)?v=([a-zA-Z0-9_-]{11})',
            r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
            # 짧은 URL: youtu.be/VIDEO_ID
            r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]{11})',
            # 임베드 URL: youtube.com/embed/VIDEO_ID
            r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})',
            # Shorts URL: youtube.com/shorts/VIDEO_ID
            r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
            # youtube-nocookie.com 임베드
            r'(?:https?://)?(?:www\.)?youtube-nocookie\.com/embed/([a-zA-Z0-9_-]{11})',
            # v/ 형식: youtube.com/v/VIDEO_ID
            r'(?:https?://)?(?:www\.)?youtube\.com/v/([a-zA-Z0-9_-]{11})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None


User = get_user_model()  # 현재 프로젝트에서 사용 중인 사용자 모델을 가져옴

class ExamResult(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    # [수정 1] exam 필드를 nullable/blank 가능하게 변경
    exam = models.ForeignKey(
        Exam, on_delete=models.CASCADE, null=True, blank=True
    )

    # [수정 2] 카테고리 전용 결과 저장을 위한 필드 추가
    category_name = models.CharField(max_length=100, null=True, blank=True)

    date_taken = models.DateTimeField(auto_now_add=True)
    num_correct = models.IntegerField()
    num_incorrect = models.IntegerField()
    num_unanswered = models.IntegerField()
    num_noanswer = models.IntegerField(default=0)
    detailed_results = models.JSONField()  # 각 문제별 결과를 저장

    def __str__(self):
        # exam이 있으면 "유저-시험제목", 없으면 "유저-카테고리명"
        if self.exam:
            return f'{self.user.username} - {self.exam.title} ({self.date_taken})'
        elif self.category_name:
            return f'{self.user.username} - [Category] {self.category_name} ({self.date_taken})'
        return f'{self.user.username} - {self.date_taken}'


class Bookmark(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'question')
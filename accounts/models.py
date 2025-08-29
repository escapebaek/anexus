from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    is_approved = models.BooleanField(default=False)
    is_specially_approved = models.BooleanField(default=False)  # Add this line
    TRAINING_HOSPITAL_CHOICES = [
        ('서울대병원', '서울대병원'),
        ('기타', '기타'),
    ]
    training_hospital = models.CharField(max_length=255, choices=TRAINING_HOSPITAL_CHOICES, default='기타')

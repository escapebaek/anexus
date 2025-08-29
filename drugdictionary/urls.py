# drugdictionary/urls.py
from django.urls import path
from . import views

app_name = 'drugdictionary'

urlpatterns = [
    path('', views.drug_info, name='drug_info'),
    path('get-section/', views.get_section_content, name='get_section_content'),
]
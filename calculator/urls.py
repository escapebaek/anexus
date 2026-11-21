from django.urls import path

from . import views

urlpatterns = [
    path('', views.calculator, name='calculator'),
    # 예전 주소: 성인 /calculator/drug/, 소아 /calculator/pediatric/ → 한 화면으로 이동
    path('drug/', views.drug_calculator, name='calculator_drug'),
    path('pediatric/', views.pediatric_calculator, name='calculator_pediatric'),
]

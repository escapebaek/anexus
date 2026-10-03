from django.urls import path

from . import views

urlpatterns = [
    path('drug/', views.drug_calculator, name='calculator_drug'),
    path('pediatric/', views.pediatric_calculator, name='calculator_pediatric'),
]

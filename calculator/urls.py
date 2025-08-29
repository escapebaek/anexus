from django.urls import path
from calculator import views
from .views import calculator_landing_page

urlpatterns=[
    path('',views.calculator, name='calculator'),
    path('landing/', calculator_landing_page, name='calculator_landing'),
]
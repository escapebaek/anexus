from django.urls import path
from . import views
from .views import ped_landing_page

urlpatterns=[
    path('', views.pedcalculate, name='pedcalculate'),
    path('landing/', ped_landing_page, name='ped_landing'),
]
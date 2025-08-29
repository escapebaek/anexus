from django.urls import path
from coag import views
from .views import coag_landing_page

urlpatterns = [
    path('',views.coag_index, name='coag_index'),
    path('<str:drugName>/',views.coag_detail, name='coag_detail'),
    path('landing/', coag_landing_page, name='coag_landing'),
]
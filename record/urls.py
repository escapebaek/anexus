from django.urls import path
from .views import anesthesia_record_view, delete_record, reset_all

urlpatterns = [
    path('', anesthesia_record_view, name='anesthesia_record'),
    path('delete/<int:record_id>/', delete_record, name='delete_record'),
    path('reset/', reset_all, name='reset_all'),
]

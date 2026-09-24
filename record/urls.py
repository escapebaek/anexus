from django.urls import path
from .views import anesthesia_record_view, save_all, delete_record, reset_all, save_template, delete_template

urlpatterns = [
    path('', anesthesia_record_view, name='anesthesia_record'),
    path('save/', save_all, name='record_save_all'),
    path('templates/save/', save_template, name='record_template_save'),
    path('templates/<int:template_id>/delete/', delete_template, name='record_template_delete'),
    path('delete/<int:record_id>/', delete_record, name='delete_record'),
    path('reset/', reset_all, name='reset_all'),
]

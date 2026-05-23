from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'real_name', 'email', 'training_hospital', 'is_staff', 'is_active', 'is_approved', 'is_specially_approved']
    list_filter = ['is_staff', 'is_active', 'is_approved', 'training_hospital', 'is_specially_approved']
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('real_name', 'is_approved', 'is_specially_approved', 'training_hospital')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (None, {'fields': ('real_name', 'is_approved', 'is_specially_approved', 'training_hospital')}),
    )
    search_fields = ['username', 'real_name', 'email']
    ordering = ['username']

admin.site.register(CustomUser, CustomUserAdmin)

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin

from .context_processors import clear_pending_count
from .models import CustomUser


class ApprovalFilter(admin.SimpleListFilter):
    title = '승인 상태'
    parameter_name = 'approval'

    def lookups(self, request, model_admin):
        return (('pending', '승인 대기'), ('approved', '승인됨'))

    def queryset(self, request, queryset):
        if self.value() == 'pending':
            return queryset.filter(is_approved=False, is_specially_approved=False)
        if self.value() == 'approved':
            return queryset.exclude(is_approved=False, is_specially_approved=False)
        return queryset


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'real_name', 'email', 'training_hospital', 'date_joined', 'is_approved', 'is_specially_approved', 'is_staff', 'is_active']
    list_filter = [ApprovalFilter, 'is_approved', 'is_specially_approved', 'is_staff', 'is_active', 'training_hospital']
    list_editable = ['is_approved']
    fieldsets = UserAdmin.fieldsets + (
        ('ANExuS', {'fields': ('real_name', 'training_hospital', 'is_approved', 'is_specially_approved')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('ANExuS', {'fields': ('email', 'real_name', 'training_hospital', 'is_approved', 'is_specially_approved')}),
    )
    search_fields = ['username', 'real_name', 'email']
    ordering = ['-date_joined']
    actions = ['approve_users', 'revoke_approval']

    @admin.action(description='선택한 회원 가입 승인')
    def approve_users(self, request, queryset):
        count = queryset.filter(is_approved=False).update(is_approved=True)
        clear_pending_count()
        self.message_user(request, f'{count}명을 승인했습니다.', messages.SUCCESS)

    @admin.action(description='선택한 회원 승인 취소')
    def revoke_approval(self, request, queryset):
        count = queryset.exclude(is_superuser=True).update(is_approved=False)
        clear_pending_count()
        self.message_user(request, f'{count}명의 승인을 취소했습니다.', messages.WARNING)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_pending_count()

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        clear_pending_count()       # 목록에서 체크박스로 승인한 경우에도 알림 숫자 갱신
        return response

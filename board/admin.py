from django.contrib import admin
from board.models import Board, Comment

class BoardAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'is_notice', 'created_date', 'modified_date')
    list_filter = ('is_notice', 'created_date', 'author')
    search_fields = ('title', 'contents', 'author__username')
    list_editable = ('is_notice',)  # 목록에서 바로 공지사항 설정 변경 가능
    ordering = ('-is_notice', '-id')  # 공지사항이 먼저, 그 다음 ID 역순
    
    fieldsets = (
        (None, {
            'fields': ('title', 'contents', 'author')
        }),
        ('설정', {
            'fields': ('is_notice',),
            'description': '공지사항으로 설정하면 게시판 상단에 고정됩니다.'
        }),
        ('날짜 정보', {
            'fields': ('created_date', 'modified_date'),
            'classes': ('collapse',)  # 접을 수 있는 섹션으로 만들기
        }),
    )
    readonly_fields = ('created_date', 'modified_date')

    def get_queryset(self, request):
        """관리자 페이지에서 공지사항을 먼저 보여주도록 정렬"""
        qs = super().get_queryset(request)
        return qs.order_by('-is_notice', '-id')

class CommentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'author', 'board', 'created_date')
    list_filter = ('created_date', 'board__is_notice')  # 공지사항의 댓글도 필터링 가능
    search_fields = ('content', 'author__username', 'board__title')
    ordering = ('-created_date',)

# 모델 등록
admin.site.register(Board, BoardAdmin)
admin.site.register(Comment, CommentAdmin)
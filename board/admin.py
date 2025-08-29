# board/admin.py
from django.contrib import admin
from board.models import Board, Comment

class BoardAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'created_date', 'modified_date')

class CommentAdmin(admin.ModelAdmin):
    list_display = ('board', 'author', 'content', 'created_date')
    list_filter = ('created_date', 'board')

admin.site.register(Board, BoardAdmin)
admin.site.register(Comment, CommentAdmin)
from django.contrib import admin
from board.models import Board

class BoardAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'created_date', 'modified_date')

admin.site.register(Board, BoardAdmin)
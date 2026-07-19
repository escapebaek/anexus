from django.contrib import admin
from .models import Journal, Issue, Paper


class PaperInline(admin.TabularInline):
    model = Paper
    extra = 1
    fields = ('title', 'authors', 'cover_image', 'pdf_file', 'short_summary', 'ai_summary', 'order')


class IssueInline(admin.TabularInline):
    model = Issue
    extra = 0
    fields = ('volume', 'number', 'publish_date')
    show_change_link = True


@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    inlines = [IssueInline]


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'journal', 'publish_date')
    list_filter = ('journal',)
    inlines = [PaperInline]


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ('title', 'issue', 'authors', 'created_date')
    list_filter = ('issue__journal',)
    search_fields = ('title', 'authors')

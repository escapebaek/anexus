from django.contrib import admin
from .models import Exam, Question, Category, ExamResult, Bookmark

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']

@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ['title', 'date_created']
    search_fields = ['title']
    list_filter = ['date_created']

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['question_text_preview', 'exam', 'category', 'order']
    list_filter = ['exam', 'category']
    search_fields = ['question_text', 'exam__title', 'category__name']
    ordering = ['exam', 'order']
    
    def question_text_preview(self, obj):
        return obj.question_text[:50] + "..." if len(obj.question_text) > 50 else obj.question_text
    question_text_preview.short_description = "문제 내용"

@admin.register(ExamResult)
class ExamResultAdmin(admin.ModelAdmin):
    list_display = ['user', 'exam_or_category', 'date_taken', 'num_correct', 'num_incorrect', 'num_unanswered']
    list_filter = ['date_taken', 'exam']
    search_fields = ['user__username', 'exam__title', 'category_name']
    readonly_fields = ['date_taken']
    
    def exam_or_category(self, obj):
        if obj.exam:
            return f"[시험] {obj.exam.title}"
        elif obj.category_name:
            return f"[카테고리] {obj.category_name}"
        return "알 수 없음"
    exam_or_category.short_description = "시험/카테고리"

@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ['user', 'question_preview', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'question__question_text']
    
    def question_preview(self, obj):
        return obj.question.question_text[:50] + "..." if len(obj.question.question_text) > 50 else obj.question.question_text
    question_preview.short_description = "문제 내용"
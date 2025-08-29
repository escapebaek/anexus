from django.urls import path, re_path
from . import views
from .views import exam_results, save_exam_results

urlpatterns = [
    path('', views.exam_list, name='exam_list'),
    path('<int:exam_id>/', views.exam_detail, name='exam_detail'),
    path('<int:exam_id>/questions/', views.question_list, name='question_list'),
    path('save_exam_results/', save_exam_results, name='save_exam_results'),
    path('exam_results/', exam_results, name='exam_results'),
    # category - 수정된 부분
    path('categories/', views.category_list, name='category_list'),
    re_path(r'^categories/(?P<category_name>[\w\s\(\)가-힣%-]+)/$', views.category_questions, name='category_questions'),
    # bookmark
    path('bookmarked/', views.bookmarked_questions, name='bookmarked_questions'),
    path('bookmark/<int:question_id>/', views.toggle_bookmark, name='toggle_bookmark'),
    path('question_home/', views.question_home, name='question_home')
]
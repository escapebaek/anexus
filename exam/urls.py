from django.urls import path, re_path
from . import views
from .views import exam_results, save_exam_results

urlpatterns = [
    path('', views.exam_list, name='exam_list'),
    path('<int:exam_id>/', views.exam_detail, name='exam_detail'),
    path('<int:exam_id>/questions/', views.question_list, name='question_list'),
    path('save_exam_results/', save_exam_results, name='save_exam_results'),
    path('exam_results/', exam_results, name='exam_results'),
    path('question/<int:question_id>/partial/', views.question_detail_partial, name='question_detail_partial'),
    
    # results history and analytics
    path('my_results/', views.my_results, name='my_results'),
    path('analytics/exam/<int:exam_id>/', views.exam_analytics, name='exam_analytics'),
    path('analytics/overview/', views.analytics_overview, name='analytics_overview'),
    path('analytics/result/<int:result_id>/', views.result_analytics, name='result_analytics'),
    path('result/<int:result_id>/delete/', views.delete_result, name='delete_result'),
    
    # Export functionality
    path('analytics/export/csv/', views.export_analytics_csv, name='export_analytics_csv'),
    
    # category
    path('categories/', views.category_list, name='category_list'),
    re_path(r'^categories/(?P<category_name>[\w\s\(\)가-힣%-]+)/$', views.category_questions, name='category_questions'),
    
    # bookmark
    path('bookmarked/', views.bookmarked_questions, name='bookmarked_questions'),
    path('bookmark/<int:question_id>/', views.toggle_bookmark, name='toggle_bookmark'),
    path('question_home/', views.question_home, name='question_home')
]
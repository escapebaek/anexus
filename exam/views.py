from django.shortcuts import render, get_object_or_404, reverse
from .models import Exam, Question, ExamResult, Category
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from accounts.decorators import user_is_specially_approved
import json
from django.views.decorators.http import require_POST
from .models import Question,Bookmark
from urllib.parse import unquote
from django.db.models import Prefetch
from django.core.paginator import Paginator

@login_required
@user_is_specially_approved
def exam_landing_page(request):
    return render(request, 'exam/landing_page.html')

@login_required
@user_is_specially_approved
def exam_list(request):
    exams = Exam.objects.all()
    return render(request, 'exam/exam_list.html', {'exams': exams})

@login_required
@user_is_specially_approved
def exam_detail(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    return render(request, 'exam/exam_detail.html', {'exam': exam})

@login_required
@user_is_specially_approved
def question_list(request, exam_id):
    exam = get_object_or_404(Exam.objects.select_related(), pk=exam_id)
    
    # Use prefetch_related to optimize bookmark queries
    bookmarked_questions = set(Bookmark.objects.filter(
        user=request.user
    ).values_list('question_id', flat=True))
    
    # Paginate questions
    page_number = request.GET.get('page', 1)
    questions_per_page = 101  # Adjust based on your needs
    
    questions = exam.questions.all().select_related('category').order_by('order')
    paginator = Paginator(questions, questions_per_page)
    page_obj = paginator.get_page(page_number)
    
    # Add bookmark status to paginated questions
    for question in page_obj:
        question.is_bookmarked = question.id in bookmarked_questions
    
    return render(request, 'exam/question_list.html', {
        'exam': exam,
        'questions': page_obj,
        'page_obj': page_obj,
    })

# Updated save_exam_results view
@login_required
@user_is_specially_approved
def save_exam_results(request):
    if request.method == 'POST':
        data = json.loads(request.body)

        exam_id = data.get('exam_id', None)
        category_name = data.get('category_name', None)
        num_correct = data.get('num_correct', 0)
        num_incorrect = data.get('num_incorrect', 0)
        num_unanswered = data.get('num_unanswered', 0)
        num_noanswer = data.get('num_noanswer', 0)
        detailed_results = data.get('detailed_results', [])
        
        # Create a lookup dictionary for questions
        questions_lookup = {}
        all_questions = Question.objects.select_related('category').all()
        
        for q in all_questions:
            question_text = str(q.question_text).strip()
            
            # Store question info under multiple keys for better matching
            keys_to_try = [
                question_text,
                question_text[:50],
                question_text[:100],
                question_text.replace('\n', ' ').replace('\r', ''),
                question_text.replace('\n', ' ').replace('\r', '')[:50]
            ]
            
            question_info = {
                'id': q.id,
                'category_name': q.category.name if q.category else 'N/A'
            }
            
            for key in keys_to_try:
                if key and key not in questions_lookup:
                    questions_lookup[key] = question_info
        
        # Process detailed_results to add question_id and category info
        for detail in detailed_results:
            question_text = str(detail.get('question', '')).strip()
            question_info = None
            
            # Try different matching strategies
            matching_strategies = [
                question_text,  # Exact match
                question_text[:100],  # Truncated to 100 chars
                question_text[:50],   # Truncated to 50 chars
                question_text.replace('\n', ' ').replace('\r', '').strip(),  # Cleaned text
                question_text.replace('\n', ' ').replace('\r', '').strip()[:50]  # Cleaned and truncated
            ]
            
            for strategy in matching_strategies:
                if strategy in questions_lookup:
                    question_info = questions_lookup[strategy]
                    break
            
            # Fallback: try partial matching
            if not question_info and len(question_text) > 20:
                for key, info in questions_lookup.items():
                    if question_text[:20] in key or key[:20] in question_text:
                        question_info = info
                        break
            
            # Set the results
            if question_info:
                detail['question_id'] = question_info['id']
                detail['category'] = question_info['category_name']
            else:
                detail['question_id'] = None
                detail['category'] = 'N/A'

        user = request.user
        exam_instance = None

        if exam_id is not None:
            exam_instance = get_object_or_404(Exam, id=exam_id)

        result = ExamResult.objects.create(
            user=user,
            exam=exam_instance,
            category_name=category_name,
            num_correct=num_correct,
            num_incorrect=num_incorrect,
            num_unanswered=num_unanswered,
            num_noanswer=num_noanswer,
            detailed_results=detailed_results,
        )

        return JsonResponse({'status': 'ok', 'result_id': result.id})
    else:
        return JsonResponse({'status': 'error'}, status=400)


# Updated exam_results view
@login_required
@user_is_specially_approved
def exam_results(request):
    result_id = request.GET.get('result_id')
    result = get_object_or_404(ExamResult, id=result_id, user=request.user)

    # Get bookmarked questions
    bookmarked_questions = set(
        Bookmark.objects.filter(user=request.user).values_list('question_id', flat=True)
    )

    # Create a more comprehensive lookup dictionary for questions
    questions_lookup = {}
    
    # Get all questions with their category information
    all_questions = Question.objects.select_related('category').all()
    
    for q in all_questions:
        # Use multiple keys to match questions more reliably
        question_text = str(q.question_text).strip()
        
        # Create multiple possible keys for matching
        keys_to_try = [
            question_text,
            question_text[:50],
            question_text[:100],
            question_text.replace('\n', ' ').replace('\r', ''),
            question_text.replace('\n', ' ').replace('\r', '')[:50]
        ]
        
        question_info = {
            'id': q.id,
            'category_name': q.category.name if q.category else 'N/A'
        }
        
        # Store under all possible keys
        for key in keys_to_try:
            if key and key not in questions_lookup:
                questions_lookup[key] = question_info

    # Process the detailed results
    updated_results = []
    for detail in result.detailed_results:
        question_text = str(detail.get('question', '')).strip()
        
        # Try to find question info using various matching strategies
        question_info = None
        
        # Strategy 1: Exact match
        if question_text in questions_lookup:
            question_info = questions_lookup[question_text]
        
        # Strategy 2: Try truncated versions
        if not question_info:
            for length in [100, 50]:
                truncated = question_text[:length]
                if truncated in questions_lookup:
                    question_info = questions_lookup[truncated]
                    break
        
        # Strategy 3: Try with cleaned text (no line breaks)
        if not question_info:
            cleaned_text = question_text.replace('\n', ' ').replace('\r', '').strip()
            if cleaned_text in questions_lookup:
                question_info = questions_lookup[cleaned_text]
            elif cleaned_text[:50] in questions_lookup:
                question_info = questions_lookup[cleaned_text[:50]]
        
        # Strategy 4: Fuzzy matching as last resort
        if not question_info:
            # Try to find a question that starts with the same text
            for key, info in questions_lookup.items():
                if len(question_text) > 20 and question_text[:20] in key:
                    question_info = info
                    break
        
        # Default if still not found
        if not question_info:
            question_info = {'id': None, 'category_name': 'N/A'}
        
        updated_detail = detail.copy()
        updated_detail['question_id'] = question_info['id']
        updated_detail['is_bookmarked'] = question_info['id'] in bookmarked_questions if question_info['id'] else False
        
        # Use category from detail first, then from database lookup
        if detail.get('category') and detail.get('category') != 'N/A':
            updated_detail['category'] = detail.get('category')
        else:
            updated_detail['category'] = question_info['category_name']
        
        updated_results.append(updated_detail)

    result.detailed_results = updated_results

    return render(request, 'exam/exam_results.html', {
        'result': result,
    })

@login_required
@user_is_specially_approved
def category_list(request):
    categories = Category.objects.all()
    return render(request, 'exam/category_list.html', {'categories': categories})

@login_required
@user_is_specially_approved
def category_questions(request, category_name):
    decoded_category_name = unquote(category_name)
    try:
        category = get_object_or_404(Category, name=decoded_category_name)
        
        # Bookmark 상태를 prefetch로 가져옴
        questions = Question.objects.filter(
            category=category
        ).prefetch_related(
            Prefetch(
                'bookmark_set',
                queryset=Bookmark.objects.filter(user=request.user),
                to_attr='user_bookmarks'
            )
        ).order_by('order')
        
        # 각 질문의 북마크 상태 설정
        for question in questions:
            question.is_bookmarked = bool(getattr(question, 'user_bookmarks', []))
            
        return render(request, 'exam/category_questions.html', {
            'category_name': category.name,
            'questions': questions
        })
    except Category.DoesNotExist:
        raise Http404(f"Category not found: {decoded_category_name}")
    
@login_required
@user_is_specially_approved
def bookmarked_questions(request):
    # 현재 사용자의 북마크된 질문들을 가져옴
    bookmarked = Question.objects.filter(
        bookmark__user=request.user
    ).select_related('exam', 'category').order_by('exam__title', 'order')
    
    return render(request, 'exam/bookmarked_questions.html', {
        'questions': bookmarked
    })
    
@require_POST
@login_required
@user_is_specially_approved
def toggle_bookmark(request, question_id):
    try:
        question = get_object_or_404(Question, id=question_id)
        bookmark = Bookmark.objects.filter(
            user=request.user,  # 현재 사용자의 북마크만 조회
            question=question
        ).first()
        
        if bookmark:  # 이미 북마크가 존재하면 삭제
            bookmark.delete()
            is_bookmarked = False
        else:  # 새로 북마크 생성
            Bookmark.objects.create(
                user=request.user,
                question=question
            )
            is_bookmarked = True
            
        return JsonResponse({
            'status': 'ok',
            'is_bookmarked': is_bookmarked
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)
        
@login_required
@user_is_specially_approved
def question_home(request):
    sections = [
        {
            "title": "Question Bank",
            "text": "ITE, 전문의 시험별 문제 은행",
            "url": reverse('exam_list'),  # Changed to always point to exam_list
            "icon_class": "fas fa-book",  # Optional: if you want to add icons
        },
        {
            "title": "Question Categories",
            "text": "단원별 문제 은행",
            "url": reverse('category_list'),
            "icon_class": "fas fa-folder",
        },
        {
            "title": "Bookmarked Questions",
            "text": "개인 북마크 문제 은행",
            "url": reverse('bookmarked_questions'),
            "icon_class": "fas fa-bookmark",
        },
    ]

    return render(request, 'exam/question_home.html', {
        'sections': sections
    })
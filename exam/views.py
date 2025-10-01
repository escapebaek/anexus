from django.shortcuts import render, get_object_or_404, reverse, redirect
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
from collections import defaultdict

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

@login_required
@user_is_specially_approved
def question_detail_partial(request, question_id):
    """Return a single question as an HTML fragment for modal display."""
    question = get_object_or_404(Question.objects.select_related('category', 'exam'), pk=question_id)

    # Determine bookmark status for current user
    is_bookmarked = Bookmark.objects.filter(user=request.user, question=question).exists()

    return render(request, 'exam/question_detail_partial.html', {
        'question': question,
        'is_bookmarked': is_bookmarked,
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
        
        # Bookmark ?곹깭瑜?prefetch濡?媛?몄샂
        questions = Question.objects.filter(
            category=category
        ).prefetch_related(
            Prefetch(
                'bookmark_set',
                queryset=Bookmark.objects.filter(user=request.user),
                to_attr='user_bookmarks'
            )
        ).order_by('order')
        
        # 媛?吏덈Ц??遺곷쭏???곹깭 ?ㅼ젙
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
    # Get all bookmarked questions for the user
    bookmarked_queryset = Question.objects.filter(
        bookmark__user=request.user
    ).select_related('exam', 'category').order_by('exam__title', 'order', 'id')

    # Get filter parameters from GET request
    selected_exam_ids = [int(x) for x in request.GET.getlist('exam') if x.isdigit()]
    selected_category_ids = [int(x) for x in request.GET.getlist('category') if x.isdigit()]

    # Count total bookmarked questions before filtering
    total_bookmarked_count = bookmarked_queryset.count()

    # Apply filters
    filtered_bookmarks = bookmarked_queryset
    if selected_exam_ids:
        filtered_bookmarks = filtered_bookmarks.filter(exam_id__in=selected_exam_ids)
    if selected_category_ids:
        filtered_bookmarks = filtered_bookmarks.filter(category_id__in=selected_category_ids)

    # Get available filters (only exams/categories that have bookmarked questions)
    available_exam_filters = Exam.objects.filter(
        questions__bookmark__user=request.user
    ).order_by('title').distinct()

    available_category_filters = Category.objects.filter(
        question__bookmark__user=request.user
    ).order_by('name').distinct()

    # Get selected objects for display
    selected_exam_objects = Exam.objects.filter(id__in=selected_exam_ids).order_by('title') if selected_exam_ids else []
    selected_category_objects = Category.objects.filter(id__in=selected_category_ids).order_by('name') if selected_category_ids else []

    # Convert to list and count
    filtered_bookmarks_list = list(filtered_bookmarks)
    filtered_count = len(filtered_bookmarks_list)
    has_active_filters = bool(selected_exam_ids or selected_category_ids)

    return render(request, 'exam/bookmarked_questions.html', {
        'questions': filtered_bookmarks_list,
        'exam_filters': available_exam_filters,
        'category_filters': available_category_filters,
        'selected_exam_ids': selected_exam_ids,
        'selected_category_ids': selected_category_ids,
        'selected_exam_objects': selected_exam_objects,
        'selected_category_objects': selected_category_objects,
        'filtered_count': filtered_count,
        'total_bookmarked_count': total_bookmarked_count,
        'has_active_filters': has_active_filters,
    })

@require_POST
@login_required
@user_is_specially_approved
def toggle_bookmark(request, question_id):
    try:
        question = get_object_or_404(Question, id=question_id)
        bookmark = Bookmark.objects.filter(
            user=request.user,  # ?꾩옱 ?ъ슜?먯쓽 遺곷쭏?щ쭔 議고쉶
            question=question
        ).first()
        
        if bookmark:  # ?대? 遺곷쭏?ш? 議댁옱?섎㈃ ??젣
            bookmark.delete()
            is_bookmarked = False
        else:  # ?덈줈 遺곷쭏???앹꽦
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
            "text": "Practice exams and question banks",
            "url": reverse('exam_list'),
            "icon_class": "book",
        },
        {
            "title": "Question Categories",
            "text": "Browse questions by category",
            "url": reverse('category_list'),
            "icon_class": "folder",
        },
        {
            "title": "Bookmarked Questions",
            "text": "Your saved questions",
            "url": reverse('bookmarked_questions'),
            "icon_class": "bookmark",
        },
        {
            "title": "My Results",
            "text": "View your saved results",
            "url": reverse('my_results'),
            "icon_class": "chart-line",
        },
        {
            "title": "Overall Analytics",
            "text": "Category accuracy across all attempts",
            "url": reverse('analytics_overview'),
            "icon_class": "chart-bar",
        },
    ]

    return render(request, 'exam/question_home.html', {
        'sections': sections
    })


# ============ Results History & Analytics ============
@login_required
@user_is_specially_approved
def my_results(request):
    """List the current user's saved results with quick links to view and analyze."""
    results = (
        ExamResult.objects
        .filter(user=request.user)
        .select_related('exam')
        .order_by('-date_taken')
    )

    # Build quick display info
    display = []
    for r in results:
        total = (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
        pct = round((r.num_correct / total) * 100, 1) if total else 0
        display.append({
            'id': r.id,
            'title': r.exam.title if r.exam else (r.category_name or 'N/A'),
            'is_exam': bool(r.exam_id),
            'exam_id': r.exam_id,
            'date_taken': r.date_taken,
            'score_text': f"{r.num_correct} / {total} ({pct}%)",
        })

    return render(request, 'exam/my_results.html', {
        'results': display,
    })


@login_required
@user_is_specially_approved
def exam_analytics(request, exam_id:int):
    """Aggregate analytics for a specific exam for the current user."""
    exam = get_object_or_404(Exam, pk=exam_id)
    results = (
        ExamResult.objects
        .filter(user=request.user, exam_id=exam_id)
        .order_by('-date_taken')
    )
    if not results:
        return render(request, 'exam/exam_analytics.html', {
            'exam': exam,
            'has_data': False,
        })

    attempts = len(results)
    best_pct = 0.0
    sum_pct = 0.0

    # Per-category aggregate across attempts
    category_stats = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'unanswered': 0, 'noanswer': 0})

    for r in results:
        total = (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
        pct = (r.num_correct / total) * 100 if total else 0
        sum_pct += pct
        if pct > best_pct:
            best_pct = pct

        # Drill into detailed results for category accuracy
        for d in r.detailed_results or []:
            cat = d.get('category') or 'N/A'
            res = d.get('result')
            if res == 'correct':
                category_stats[cat]['correct'] += 1
            elif res == 'incorrect':
                category_stats[cat]['incorrect'] += 1
            elif res == 'unanswered':
                category_stats[cat]['unanswered'] += 1
            elif res == 'noanswer':
                category_stats[cat]['noanswer'] += 1

    avg_pct = round(sum_pct / attempts, 1) if attempts else 0
    best_pct = round(best_pct, 1)

    # Prepare data for charts
    labels = []
    correct_data = []
    incorrect_data = []
    unanswered_data = []
    noanswer_data = []
    accuracy_pct = []

    for cat, s in sorted(category_stats.items()):
        labels.append(cat)
        correct_data.append(s['correct'])
        incorrect_data.append(s['incorrect'])
        unanswered_data.append(s['unanswered'])
        noanswer_data.append(s['noanswer'])
        denom = (s['correct'] + s['incorrect'])
        acc = (s['correct'] / denom * 100) if denom else 0
        accuracy_pct.append(round(acc, 1))

    return render(request, 'exam/exam_analytics.html', {
        'has_data': True,
        'exam': exam,
        'attempts': attempts,
        'avg_pct': avg_pct,
        'best_pct': best_pct,
        'labels': labels,
        'correct_data': correct_data,
        'incorrect_data': incorrect_data,
        'unanswered_data': unanswered_data,
        'noanswer_data': noanswer_data,
        'accuracy_pct': accuracy_pct,
        'latest_result_id': results[0].id,
    })


@login_required
@user_is_specially_approved
def analytics_overview(request):
    """Aggregate analytics across ALL exams for the current user."""
    results = (
        ExamResult.objects
        .filter(user=request.user)
        .order_by('-date_taken')
    )
    if not results:
        return render(request, 'exam/overall_analytics.html', {
            'has_data': False,
        })

    attempts = len(results)
    best_pct = 0.0
    sum_pct = 0.0
    category_stats = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'unanswered': 0, 'noanswer': 0})

    for r in results:
        total = (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
        pct = (r.num_correct / total) * 100 if total else 0
        sum_pct += pct
        if pct > best_pct:
            best_pct = pct

        for d in r.detailed_results or []:
            cat = d.get('category') or 'N/A'
            res = d.get('result')
            if res == 'correct':
                category_stats[cat]['correct'] += 1
            elif res == 'incorrect':
                category_stats[cat]['incorrect'] += 1
            elif res == 'unanswered':
                category_stats[cat]['unanswered'] += 1
            elif res == 'noanswer':
                category_stats[cat]['noanswer'] += 1

    avg_pct = round(sum_pct / attempts, 1) if attempts else 0
    best_pct = round(best_pct, 1)

    # Combined (all exams) dataset
    labels_all = []
    correct_all = []
    incorrect_all = []
    unanswered_all = []
    noanswer_all = []
    acc_all = []

    for cat, s in sorted(category_stats.items()):
        labels_all.append(cat)
        correct_all.append(s['correct'])
        incorrect_all.append(s['incorrect'])
        unanswered_all.append(s['unanswered'])
        noanswer_all.append(s['noanswer'])
        denom = (s['correct'] + s['incorrect'])
        acc = (s['correct'] / denom * 100) if denom else 0
        acc_all.append(round(acc, 1))

    # Per-exam rollups across all attempts
    exams_qs = (Exam.objects
                .filter(id__in=[r.exam_id for r in results if r.exam_id])
                .order_by('title'))
    exam_cards = []
    exam_data = {}

    for ex in exams_qs:
        ex_results = [r for r in results if r.exam_id == ex.id]
        ex_attempts = len(ex_results)
        ex_best = 0.0
        ex_sum = 0.0
        ex_cat = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'unanswered': 0, 'noanswer': 0})
        for r in ex_results:
            total = (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
            pct = (r.num_correct / total) * 100 if total else 0
            ex_sum += pct
            if pct > ex_best:
                ex_best = pct
            for d in r.detailed_results or []:
                cat = d.get('category') or 'N/A'
                rs = d.get('result')
                if rs == 'correct':
                    ex_cat[cat]['correct'] += 1
                elif rs == 'incorrect':
                    ex_cat[cat]['incorrect'] += 1
                elif rs == 'unanswered':
                    ex_cat[cat]['unanswered'] += 1
                elif rs == 'noanswer':
                    ex_cat[cat]['noanswer'] += 1

        ex_avg = round(ex_sum / ex_attempts, 1) if ex_attempts else 0
        ex_best = round(ex_best, 1)

        # Pack time-invariant summary card
        exam_cards.append({
            'id': ex.id,
            'title': ex.title,
            'attempts': ex_attempts,
            'avg_pct': ex_avg,
            'best_pct': ex_best,
        })

        ex_labels, ex_correct, ex_incorrect, ex_unanswered, ex_noanswer, ex_acc = [], [], [], [], [], []
        for cat, s in sorted(ex_cat.items()):
            ex_labels.append(cat)
            ex_correct.append(s['correct'])
            ex_incorrect.append(s['incorrect'])
            ex_unanswered.append(s['unanswered'])
            ex_noanswer.append(s['noanswer'])
            denom = (s['correct'] + s['incorrect'])
            acc = (s['correct'] / denom * 100) if denom else 0
            ex_acc.append(round(acc, 1))

        exam_data[str(ex.id)] = {
            'labels': ex_labels,
            'correct': ex_correct,
            'incorrect': ex_incorrect,
            'unanswered': ex_unanswered,
            'noanswer': ex_noanswer,
            'accuracy': ex_acc,
        }

    return render(request, 'exam/overall_analytics.html', {
        'has_data': True,
        'attempts': attempts,
        'avg_pct': avg_pct,
        'best_pct': best_pct,
        # All
        'labels_all': labels_all,
        'correct_all': correct_all,
        'incorrect_all': incorrect_all,
        'unanswered_all': unanswered_all,
        'noanswer_all': noanswer_all,
        'acc_all': acc_all,
        # Per exam
        'exam_cards': exam_cards,
        'exam_data': exam_data,
    })

@login_required
@user_is_specially_approved
def result_analytics(request, result_id:int):
    """Analytics for a single result attempt only."""
    r = get_object_or_404(ExamResult, pk=result_id, user=request.user)
    total = (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
    pct_total = round(((r.num_correct or 0) / total) * 100, 1) if total else 0

    cat = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'unanswered': 0, 'noanswer': 0})
    for d in r.detailed_results or []:
        c = d.get('category') or 'N/A'
        res = d.get('result')
        if res == 'correct':
            cat[c]['correct'] += 1
        elif res == 'incorrect':
            cat[c]['incorrect'] += 1
        elif res == 'unanswered':
            cat[c]['unanswered'] += 1
        elif res == 'noanswer':
            cat[c]['noanswer'] += 1

    labels, correct, incorrect, unanswered, noanswer, acc = [], [], [], [], [], []
    for k, s in sorted(cat.items()):
        labels.append(k)
        correct.append(s['correct'])
        incorrect.append(s['incorrect'])
        unanswered.append(s['unanswered'])
        noanswer.append(s['noanswer'])
        denom = (s['correct'] + s['incorrect'])
        pct = (s['correct'] / denom * 100) if denom else 0
        acc.append(round(pct, 1))

    return render(request, 'exam/result_analytics.html', {
        'result': r,
        'exam': r.exam,
        'total': total,
        'pct_total': pct_total,
        'labels': labels,
        'correct_data': correct,
        'incorrect_data': incorrect,
        'unanswered_data': unanswered,
        'noanswer_data': noanswer,
        'accuracy_pct': acc,
    })

@require_POST
@login_required
@user_is_specially_approved
def delete_result(request, result_id: int):
    r = get_object_or_404(ExamResult, pk=result_id, user=request.user)
    r.delete()
    return redirect('my_results')




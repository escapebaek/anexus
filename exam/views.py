from django.shortcuts import render, get_object_or_404, reverse, redirect
from .models import Exam, Question, ExamResult, Category
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from accounts.decorators import user_is_approved
import json
import csv
from django.views.decorators.http import require_POST
from .models import Question, Bookmark
from urllib.parse import unquote
from django.db.models import Prefetch
from django.core.paginator import Paginator
from collections import defaultdict
from datetime import datetime, timedelta
from .grading import grade, MAX_QUESTIONS_PER_RESULT


def visible_exams(user):
    """특별 시험(is_special)은 특별 승인 사용자에게만 보인다."""
    if getattr(user, 'is_specially_approved', False):
        return Exam.objects.all()
    return Exam.objects.filter(is_special=False)


def visible_questions(user):
    if getattr(user, 'is_specially_approved', False):
        return Question.objects.all()
    return Question.objects.filter(exam__is_special=False)

@login_required
@user_is_approved
def exam_list(request):
    exams = visible_exams(request.user).order_by('display_order', 'date_created')
    attempted_exam_ids = set(
        ExamResult.objects.filter(user=request.user, exam__isnull=False)
        .values_list('exam_id', flat=True)
        .distinct()
    )
    return render(request, 'exam/exam_list.html', {
        'exams': exams,
        'attempted_exam_ids': attempted_exam_ids,
    })

@login_required
@user_is_approved
def exam_detail(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if exam.is_special and not request.user.is_specially_approved:
        return redirect('exam_list')
    has_attempts = ExamResult.objects.filter(user=request.user, exam=exam).exists()
    return render(request, 'exam/exam_detail.html', {
        'exam': exam,
        'has_attempts': has_attempts,
    })

@login_required
@user_is_approved
def question_list(request, exam_id):
    exam = get_object_or_404(Exam.objects.select_related(), pk=exam_id)
    if exam.is_special and not request.user.is_specially_approved:
        return redirect('exam_list')
    
    bookmarked_questions = set(Bookmark.objects.filter(
        user=request.user
    ).values_list('question_id', flat=True))
    
    page_number = request.GET.get('page', 1)
    questions_per_page = 101
    
    questions = exam.questions.all().select_related('category').order_by('order')
    paginator = Paginator(questions, questions_per_page)
    page_obj = paginator.get_page(page_number)
    
    for question in page_obj:
        question.is_bookmarked = question.id in bookmarked_questions
    
    return render(request, 'exam/quiz_unified.html', {
        'exam': exam,
        'questions': page_obj,
        'page_obj': page_obj,
    })

@require_POST
@login_required
@user_is_approved
def save_exam_results(request):
    """브라우저가 보낸 '문제 ID → 고른 선택지 번호'를 서버에서 채점해 저장."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON format'}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({'status': 'error', 'message': 'Invalid data'}, status=400)

    question_ids = []
    for value in data.get('question_ids') or []:
        try:
            qid = int(value)
        except (TypeError, ValueError):
            continue
        if qid not in question_ids:
            question_ids.append(qid)
    if not question_ids or len(question_ids) > MAX_QUESTIONS_PER_RESULT:
        return JsonResponse({'status': 'error', 'message': '채점할 문제가 없습니다.'}, status=400)
    answers = data.get('answers') if isinstance(data.get('answers'), dict) else {}

    exam_instance = None
    category_name = None
    questions = visible_questions(request.user).filter(id__in=question_ids).select_related('category')
    if data.get('exam_id'):
        if not str(data.get('exam_id')).isdigit():
            return JsonResponse({'status': 'error', 'message': 'Invalid exam'}, status=400)
        exam_instance = get_object_or_404(visible_exams(request.user), id=int(data.get('exam_id')))
        questions = questions.filter(exam=exam_instance)
    else:
        category_name = str(data.get('category_name') or '북마크된 문제')[:100]

    by_id = {q.id: q for q in questions}
    ordered = [by_id[qid] for qid in question_ids if qid in by_id]
    if not ordered:
        return JsonResponse({'status': 'error', 'message': '채점할 문제가 없습니다.'}, status=400)

    counts, details = grade(ordered, answers)
    result = ExamResult.objects.create(
        user=request.user,
        exam=exam_instance,
        category_name=category_name,
        num_correct=counts['correct'],
        num_incorrect=counts['incorrect'],
        num_unanswered=counts['unanswered'],
        num_noanswer=counts['noanswer'],
        detailed_results=details,
    )
    return JsonResponse({'status': 'ok', 'result_id': result.id})

def result_title(result):
    return result.exam.title if result.exam else (result.category_name or '기타')


def result_counts(result):
    """(맞음, 전체, 점수%) — 점수는 맞은 문제 / 전체 문제."""
    total = (result.num_correct or 0) + (result.num_incorrect or 0) + (result.num_unanswered or 0) + (result.num_noanswer or 0)
    pct = round((result.num_correct or 0) / total * 100, 1) if total else 0
    return result.num_correct or 0, total, pct


def _selected_number(detail, question):
    """고른 선택지 번호. 예전 기록엔 번호가 없어 고른 선택지 글자로 찾는다."""
    if detail.get('selected'):
        return detail['selected']
    chosen = (detail.get('selected_answer') or '').strip()
    if not chosen or question is None:
        return None
    for i in range(1, 6):
        if (getattr(question, f'option{i}') or '').strip() == chosen:
            return i
    return None


@login_required
@user_is_approved
def exam_results(request):
    """채점 결과: 점수 요약 + 틀린 문제부터 보는 문제 목록(펼치면 선택지·해설) + 카테고리별 정답률."""
    result = get_object_or_404(ExamResult.objects.select_related('exam'), id=request.GET.get('result_id'), user=request.user)
    details = [d for d in (result.detailed_results or []) if isinstance(d, dict)]
    question_ids = [d.get('question_id') for d in details if d.get('question_id')]
    questions = {q.id: q for q in visible_questions(request.user).filter(id__in=question_ids).select_related('category', 'exam')}
    bookmarked = set(Bookmark.objects.filter(user=request.user, question_id__in=question_ids).values_list('question_id', flat=True))

    items = []
    by_category = defaultdict(lambda: {'correct': 0, 'graded': 0})
    for number, detail in enumerate(details, 1):
        question = questions.get(detail.get('question_id'))
        outcome = detail.get('result') or 'noanswer'
        selected = _selected_number(detail, question)
        answer = question.answer_number() if question else None
        options = []
        if question:
            for num, label, text in question.option_list():
                options.append({'num': num, 'label': label, 'text': text,
                                'is_selected': num == selected, 'is_answer': num == answer})
        items.append({
            'number': number,
            'result': outcome,
            'question': question,
            'text': detail.get('question') or '',
            'category': detail.get('category') if detail.get('category') not in (None, '', 'N/A') else (question.category.name if question and question.category else ''),
            'selected_answer': detail.get('selected_answer') or '',
            'correct_answer': detail.get('correct_answer') or '',
            'options': options,
            'is_bookmarked': question is not None and question.id in bookmarked,
        })
        if outcome != 'noanswer':
            row = by_category[items[-1]['category'] or '미분류']
            row['graded'] += 1
            row['correct'] += outcome == 'correct'

    categories = sorted(
        ({'name': name, 'correct': row['correct'], 'graded': row['graded'],
          'pct': round(row['correct'] / row['graded'] * 100) if row['graded'] else 0}
         for name, row in by_category.items()),
        key=lambda c: (c['pct'], -c['graded'], c['name']))
    correct, total, pct = result_counts(result)
    wrong_count = (result.num_incorrect or 0) + (result.num_unanswered or 0)
    return render(request, 'exam/exam_results.html', {
        'result': result,
        'title': result_title(result),
        'items': items,
        'categories': categories,
        'correct': correct,
        'total': total,
        'pct': pct,
        'wrong_count': wrong_count,
        'retry_possible': any(i['question'] for i in items),
    })


@login_required
@user_is_approved
def retry_result(request, result_id):
    """응시 기록의 문제를 다시 푼다. 기본은 틀리거나 안 푼 문제만, ?only=all 이면 전체."""
    result = get_object_or_404(ExamResult.objects.select_related('exam'), id=result_id, user=request.user)
    only_all = request.GET.get('only') == 'all'
    wanted = [d.get('question_id') for d in (result.detailed_results or [])
              if isinstance(d, dict) and d.get('question_id')
              and (only_all or d.get('result') in ('incorrect', 'unanswered'))]
    if not wanted:
        return redirect(f"{reverse('exam_results')}?result_id={result.id}")
    by_id = {q.id: q for q in visible_questions(request.user).filter(id__in=wanted).select_related('category', 'exam')}
    bookmarked = set(Bookmark.objects.filter(user=request.user, question_id__in=by_id).values_list('question_id', flat=True))
    questions = []
    for qid in dict.fromkeys(wanted):
        if qid in by_id:
            by_id[qid].is_bookmarked = qid in bookmarked
            questions.append(by_id[qid])
    label = '다시 풀기' if only_all else '틀린 문제 다시 풀기'
    return render(request, 'exam/quiz_unified.html', {
        'category_name': f'{label} · {result_title(result)}'[:100],
        'retry_of': result,
        'questions': questions,
    })


def result_analytics(request, result_id):
    """예전 '응시 분석' 주소 — 채점 화면에 모두 합쳐졌다."""
    return redirect(f"{reverse('exam_results')}?result_id={result_id}")


@login_required
@user_is_approved
def category_list(request):
    categories = Category.objects.all()
    return render(request, 'exam/category_list.html', {'categories': categories})

@login_required
@user_is_approved
def category_questions(request, category_name):
    category = get_object_or_404(Category, name=unquote(category_name))
    questions = visible_questions(request.user).filter(
        category=category
    ).select_related('category', 'exam').prefetch_related(
        Prefetch(
            'bookmark_set',
            queryset=Bookmark.objects.filter(user=request.user),
            to_attr='user_bookmarks'
        )
    ).order_by('order')
    for question in questions:
        question.is_bookmarked = bool(question.user_bookmarks)
    return render(request, 'exam/quiz_unified.html', {
        'category_name': category.name,
        'questions': questions
    })

@login_required
@user_is_approved
def bookmarked_questions(request):
    bookmarked_queryset = visible_questions(request.user).filter(
        bookmark__user=request.user
    ).select_related('exam', 'category').order_by('exam__title', 'order', 'id')
    selected_exam_ids = [int(x) for x in request.GET.getlist('exam') if x.isdigit()]
    selected_category_ids = [int(x) for x in request.GET.getlist('category') if x.isdigit()]
    total_bookmarked_count = bookmarked_queryset.count()
    filtered_bookmarks = bookmarked_queryset
    if selected_exam_ids:
        filtered_bookmarks = filtered_bookmarks.filter(exam_id__in=selected_exam_ids)
    if selected_category_ids:
        filtered_bookmarks = filtered_bookmarks.filter(category_id__in=selected_category_ids)
    available_exam_filters = visible_exams(request.user).filter(
        questions__bookmark__user=request.user
    ).order_by('title').distinct()
    available_category_filters = Category.objects.filter(
        question__in=visible_questions(request.user).filter(bookmark__user=request.user)
    ).order_by('name').distinct()
    selected_exam_objects = Exam.objects.filter(id__in=selected_exam_ids).order_by('title') if selected_exam_ids else []
    selected_category_objects = Category.objects.filter(id__in=selected_category_ids).order_by('name') if selected_category_ids else []
    filtered_bookmarks_list = list(filtered_bookmarks)
    filtered_count = len(filtered_bookmarks_list)
    has_active_filters = bool(selected_exam_ids or selected_category_ids)
    return render(request, 'exam/quiz_unified.html', {
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
@user_is_approved
def toggle_bookmark(request, question_id):
    try:
        question = get_object_or_404(visible_questions(request.user), id=question_id)
        bookmark = Bookmark.objects.filter(
            user=request.user,
            question=question
        ).first()
        if bookmark:
            bookmark.delete()
            is_bookmarked = False
        else:
            Bookmark.objects.create(user=request.user, question=question)
            is_bookmarked = True
        return JsonResponse({'status': 'ok', 'is_bookmarked': is_bookmarked})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        
@login_required
@user_is_approved
def question_home(request):
    sections = [
        {"title": "Question Bank", "text": "Practice exams and question banks",
         "url": reverse('exam_list'), "icon_class": "book"},
        {"title": "Question Categories", "text": "Browse questions by category",
         "url": reverse('category_list'), "icon_class": "folder"},
        {"title": "Bookmarked Questions", "text": "Your saved questions",
         "url": reverse('bookmarked_questions'), "icon_class": "bookmark"},
        {"title": "My Results", "text": "View your saved results",
         "url": reverse('my_results'), "icon_class": "list-alt"},
        {"title": "Exam Analytics", "text": "Statistics by exam round",
         "url": reverse('exam_stats_list'), "icon_class": "chart-bar"},
        {"title": "Overall Analytics", "text": "Category accuracy across all attempts",
         "url": reverse('analytics_overview'), "icon_class": "chart-pie"},
    ]
    return render(request, 'exam/question_home.html', {'sections': sections})

@login_required
@user_is_approved
def exam_stats_list(request):
    """Per-exam statistics overview — lists every exam the user has attempted"""
    results = (
        ExamResult.objects
        .filter(user=request.user, exam__isnull=False)
        .select_related('exam')
        .order_by('exam__display_order', 'exam__title', '-date_taken')
    )

    exam_data = {}
    order_key = {}
    for r in results:
        eid = r.exam_id
        if eid not in exam_data:
            exam_data[eid] = {
                'exam': r.exam,
                'attempts': 0,
                'scores': [],
                'last_taken': r.date_taken,
            }
            order_key[eid] = (r.exam.display_order, r.exam.title)
        total = (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
        pct = round((r.num_correct / total) * 100, 1) if total else 0
        exam_data[eid]['attempts'] += 1
        exam_data[eid]['scores'].append(pct)

    exam_list = []
    for eid, data in sorted(exam_data.items(), key=lambda kv: order_key[kv[0]]):
        scores = data['scores']
        avg = round(sum(scores) / len(scores), 1) if scores else 0
        exam_list.append({
            'exam': data['exam'],
            'attempts': data['attempts'],
            'avg_score': avg,
            'best_score': round(max(scores), 1) if scores else 0,
            'last_taken': data['last_taken'],
        })

    return render(request, 'exam/exam_stats_list.html', {
        'exam_list': exam_list,
        'has_data': bool(exam_list),
    })

# ============ Helper Functions ============
def calculate_improvement_rate(results):
    """Calculate score improvement between first half and second half of attempts"""
    if len(results) < 2:
        return 0
    scores = []
    for r in results:
        total = (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
        pct = (r.num_correct / total) * 100 if total else 0
        scores.append(pct)
    scores.reverse()  # chronological order
    mid = len(scores) // 2
    first_half_avg = sum(scores[:mid]) / mid if mid > 0 else 0
    second_half_avg = sum(scores[mid:]) / (len(scores) - mid) if (len(scores) - mid) > 0 else 0
    return round(second_half_avg - first_half_avg, 1)

def identify_weak_categories(category_stats, threshold=70):
    """Identify categories with accuracy below threshold"""
    weak = []
    for cat, s in category_stats.items():
        denom = (s['correct'] + s['incorrect'])
        if denom > 0:
            acc = (s['correct'] / denom * 100)
            if acc < threshold:
                weak.append({'name': cat, 'accuracy': round(acc, 1), 'total': denom})
    return sorted(weak, key=lambda x: x['accuracy'])

def identify_strong_categories(category_stats, threshold=70):
    """Identify categories with accuracy above threshold"""
    strong = []
    for cat, s in category_stats.items():
        denom = (s['correct'] + s['incorrect'])
        if denom > 0:
            acc = (s['correct'] / denom * 100)
            if acc >= threshold:
                strong.append({'name': cat, 'accuracy': round(acc, 1), 'total': denom})
    return sorted(strong, key=lambda x: x['accuracy'], reverse=True)

def calculate_moving_average(scores, window=3):
    """Calculate moving average for trend smoothing"""
    if len(scores) < window:
        return [round(s, 1) for s in scores]
    moving_avg = []
    for i in range(len(scores)):
        if i < window - 1:
            moving_avg.append(round(scores[i], 1))
        else:
            avg = sum(scores[i-window+1:i+1]) / window
            moving_avg.append(round(avg, 1))
    return moving_avg

def calculate_recent_vs_overall(scores, recent_count=3):
    """Compare recent N attempts average vs overall average"""
    if len(scores) < 2:
        return {'recent_avg': scores[0] if scores else 0, 'overall_avg': scores[0] if scores else 0, 'diff': 0}
    overall_avg = sum(scores) / len(scores) if scores else 0
    recent = scores[-recent_count:] if len(scores) >= recent_count else scores
    recent_avg = sum(recent) / len(recent) if recent else 0
    return {
        'recent_avg': round(recent_avg, 1),
        'overall_avg': round(overall_avg, 1),
        'diff': round(recent_avg - overall_avg, 1)
    }

def calculate_target_gap(avg_pct, target=60):
    """Calculate gap to target score"""
    gap = target - avg_pct
    return {
        'target': target,
        'gap': round(max(0, gap), 1),
        'reached': avg_pct >= target,
        'progress_pct': round(min(100, (avg_pct / target) * 100), 1) if target > 0 else 100
    }

def generate_study_recommendation(weak_categories, avg_pct, target=60):
    """Generate personalized study recommendation"""
    # Filter out N/A categories as they can't be linked
    valid_weak_categories = [c for c in weak_categories if c.get('name') and c.get('name') != 'N/A']
    
    if not valid_weak_categories:
        if avg_pct >= target:
            return {
                'message': '축하합니다! 목표 점수에 도달했습니다. 현재 실력을 유지하세요!',
                'priority_category': None,
                'priority_categories': [],
                'icon': 'trophy',
                'type': 'success'
            }
        return {
            'message': '훌륭합니다! 모든 카테고리에서 좋은 성적을 보이고 있습니다.',
            'priority_category': None,
            'priority_categories': [],
            'icon': 'star',
            'type': 'info'
        }
    
    # Sort by accuracy (lowest first) to find the weakest categories
    sorted_weak = sorted(valid_weak_categories, key=lambda x: x.get('accuracy', 0))
    
    # Get top 3 weakest categories for display
    top_weak = sorted_weak[:3]
    priority = sorted_weak[0]  # The weakest one
    
    gap_to_target = target - avg_pct
    
    # Estimate questions needed (rough calculation)
    estimated_questions = max(5, int(gap_to_target * 2))
    
    # Build message with multiple categories if available
    if len(top_weak) > 1:
        category_list = ', '.join([f"'{c['name']}' ({c['accuracy']}%)" for c in top_weak])
        message = f"다음 카테고리들의 정확도가 가장 낮습니다: {category_list}. '{priority['name']}' 카테고리부터 집중 연습해보세요!"
    else:
        message = f"'{priority['name']}' 카테고리의 정확도가 {priority['accuracy']}%로 가장 낮습니다. 이 카테고리를 집중 연습해보세요!"
    
    return {
        'message': message,
        'priority_category': priority['name'],
        'priority_accuracy': priority['accuracy'],
        'priority_categories': top_weak,  # List of top 3 weakest categories
        'estimated_practice': estimated_questions,
        'icon': 'lightbulb',
        'type': 'warning'
    }

def get_performance_grade(pct):
    """Get grade and color based on percentage"""
    if pct >= 90:
        return {'grade': 'A+', 'label': 'Excellent', 'label_kr': '우수',   'color': '#27ae60'}
    elif pct >= 80:
        return {'grade': 'A',  'label': 'Great',     'label_kr': '훌륭',   'color': '#2ecc71'}
    elif pct >= 70:
        return {'grade': 'B+', 'label': 'Good',      'label_kr': '양호',   'color': '#2b5876'}
    elif pct >= 60:
        return {'grade': 'B',  'label': 'Fair',      'label_kr': '보통',   'color': '#d69e2e'}
    elif pct >= 50:
        return {'grade': 'C',  'label': 'Needs Work','label_kr': '노력필요','color': '#e67e22'}
    else:
        return {'grade': 'D',  'label': 'Keep Trying','label_kr': '분발',  'color': '#e53e3e'}

def calculate_total_questions_answered(results):
    """Calculate total number of questions answered across all results"""
    total = 0
    for r in results:
        total += (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
    return total

# ============ Results History & Analytics ============
@login_required
@user_is_approved
def my_results(request):
    results = (
        ExamResult.objects
        .filter(user=request.user)
        .select_related('exam')
        .order_by('-date_taken')
    )
    display = []
    for r in results:
        correct, total, pct = result_counts(r)
        display.append({
            'id': r.id,
            'title': result_title(r),
            'is_exam': bool(r.exam_id),
            'exam_id': r.exam_id,
            'date_taken': r.date_taken,
            'correct': correct,
            'total': total,
            'score_percent': pct,
            'wrong': (r.num_incorrect or 0) + (r.num_unanswered or 0),
        })
    return render(request, 'exam/my_results.html', {'results': display})

@login_required
@user_is_approved
def exam_analytics(request, exam_id:int):
    """Enhanced analytics for a specific exam"""
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
    category_stats = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'unanswered': 0, 'noanswer': 0})
    
    # Progress data for line chart
    attempt_dates = []
    attempt_scores = []
    
    for r in reversed(results):  # chronological order
        total = (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
        pct = (r.num_correct / total) * 100 if total else 0
        sum_pct += pct
        if pct > best_pct:
            best_pct = pct
        attempt_dates.append(r.date_taken.strftime('%m/%d'))
        attempt_scores.append(round(pct, 1))
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
    
    # Calculate improvement rate and trends
    improvement_rate = calculate_improvement_rate(results)
    moving_avg = calculate_moving_average(attempt_scores, window=min(3, len(attempt_scores)))
    
    # Identify weak and strong categories
    weak_categories = identify_weak_categories(category_stats)
    strong_categories = identify_strong_categories(category_stats)
    
    # NEW: Enhanced statistics
    recent_comparison = calculate_recent_vs_overall(attempt_scores)
    target_gap = calculate_target_gap(avg_pct)
    study_recommendation = generate_study_recommendation(weak_categories, avg_pct)
    performance_grade = get_performance_grade(avg_pct)
    total_questions = calculate_total_questions_answered(results)
    
    # Category data
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
        'improvement_rate': improvement_rate,
        'weak_categories': weak_categories,
        'strong_categories': strong_categories,
        'labels': labels,
        'correct_data': correct_data,
        'incorrect_data': incorrect_data,
        'unanswered_data': unanswered_data,
        'noanswer_data': noanswer_data,
        'accuracy_pct': accuracy_pct,
        'latest_result_id': results[0].id,
        'attempt_dates': attempt_dates,
        'attempt_scores': attempt_scores,
        'moving_avg': moving_avg,
        # NEW: Enhanced statistics
        'recent_comparison': recent_comparison,
        'target_gap': target_gap,
        'study_recommendation': study_recommendation,
        'performance_grade': performance_grade,
        'total_questions': total_questions,
    })

@login_required
@user_is_approved
def analytics_overview(request):
    """Enhanced aggregate analytics across ALL exams"""
    results = list(
        ExamResult.objects
        .filter(user=request.user)
        .order_by('-date_taken')
    )
    if not results:
        return render(request, 'exam/overall_analytics.html', {'has_data': False})

    attempts = len(results)
    best_pct = 0.0
    sum_pct = 0.0
    category_stats = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'unanswered': 0, 'noanswer': 0})
    
    # Progress tracking
    attempt_dates = []
    attempt_scores = []

    for r in reversed(results):  # chronological order
        total = (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
        pct = (r.num_correct / total) * 100 if total else 0
        sum_pct += pct
        if pct > best_pct:
            best_pct = pct
        attempt_dates.append(r.date_taken.strftime('%m/%d'))
        attempt_scores.append(round(pct, 1))
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
    
    # Enhanced analytics
    improvement_rate = calculate_improvement_rate(results)
    moving_avg = calculate_moving_average(attempt_scores, window=min(3, len(attempt_scores)))
    weak_categories = identify_weak_categories(category_stats)
    strong_categories = identify_strong_categories(category_stats)
    
    # NEW: Enhanced statistics
    recent_comparison = calculate_recent_vs_overall(attempt_scores)
    target_gap = calculate_target_gap(avg_pct)
    study_recommendation = generate_study_recommendation(weak_categories, avg_pct)
    performance_grade = get_performance_grade(avg_pct)
    total_questions = calculate_total_questions_answered(results)

    # Combined dataset
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

    # Per-exam rollups
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
        'improvement_rate': improvement_rate,
        'weak_categories': weak_categories,
        'strong_categories': strong_categories,
        'labels_all': labels_all,
        'correct_all': correct_all,
        'incorrect_all': incorrect_all,
        'unanswered_all': unanswered_all,
        'noanswer_all': noanswer_all,
        'acc_all': acc_all,
        'exam_cards': exam_cards,
        'exam_data': exam_data,
        'attempt_dates': attempt_dates,
        'attempt_scores': attempt_scores,
        'moving_avg': moving_avg,
        # NEW: Enhanced statistics
        'recent_comparison': recent_comparison,
        'target_gap': target_gap,
        'study_recommendation': study_recommendation,
        'performance_grade': performance_grade,
        'total_questions': total_questions,
    })

@require_POST
@login_required
@user_is_approved
def delete_result(request, result_id: int):
    r = get_object_or_404(ExamResult, pk=result_id, user=request.user)
    r.delete()
    return redirect('my_results')

@login_required
@user_is_approved
def export_analytics_csv(request):
    """Export analytics data as CSV"""
    results = ExamResult.objects.filter(user=request.user).select_related('exam').order_by('-date_taken')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="exam_analytics.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Date', 'Exam/Category', 'Correct', 'Incorrect', 'Unanswered', 'No Answer', 'Total', 'Score %'])
    
    for r in results:
        total = (r.num_correct or 0) + (r.num_incorrect or 0) + (r.num_unanswered or 0) + (r.num_noanswer or 0)
        pct = round((r.num_correct / total) * 100, 1) if total else 0
        exam_name = r.exam.title if r.exam else (r.category_name or 'N/A')
        writer.writerow([
            r.date_taken.strftime('%Y-%m-%d %H:%M'),
            exam_name,
            r.num_correct,
            r.num_incorrect,
            r.num_unanswered,
            r.num_noanswer,
            total,
            pct
        ])
    
    return response
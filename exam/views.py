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
from django.db.models import Count, Prefetch
from django.core.paginator import Paginator
from collections import defaultdict
from datetime import datetime, timedelta
import re

from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timezone import localtime

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
    # 볼 수 있는 문제가 하나도 없는 카테고리(특별 시험에만 있는 카테고리 등)는 목록에서 뺀다
    categories = Category.objects.filter(question__in=visible_questions(request.user)).distinct().order_by('name')
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
    selected_exam_objects = visible_exams(request.user).filter(id__in=selected_exam_ids).order_by('title') if selected_exam_ids else []
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
    """문제은행 홈: 내 요약(응시·평균·푼 문제) + 이어서 하기(최근 응시·약한 파트·오답) + 메뉴 + 회차 바로가기."""
    user = request.user
    results = list(ExamResult.objects.filter(user=user).select_related('exam').order_by('date_taken', 'id'))
    exams = list(visible_exams(user).annotate(n=Count('questions')).order_by('display_order', 'date_created'))
    scores = [result_counts(r)[2] for r in results]
    latest_by_exam = {}
    for r, pct in zip(results, scores):
        if r.exam_id:
            latest_by_exam[r.exam_id] = {'pct': pct, 'date': r.date_taken, 'count': latest_by_exam.get(r.exam_id, {}).get('count', 0) + 1}
    for e in exams:
        e.mine = latest_by_exam.get(e.id)
    categories, _ = category_stats(results)
    weak = [c for c in categories if not c['few'] and c['pct'] < GOOD_PCT]
    wrong_total = len(still_wrong_questions(user)) if results else 0
    bookmarks = Bookmark.objects.filter(user=user, question__in=visible_questions(user)).count()
    category_count = Category.objects.filter(question__in=visible_questions(user)).distinct().count()
    menu = [
        {'title': '회차별 풀기', 'en': 'Question Bank', 'text': '기출 회차를 실제 시험처럼', 'url': reverse('exam_list'),
         'icon': 'book-open', 'count': f'{len(exams)}개 회차'},
        {'title': '카테고리별 풀기', 'en': 'Categories', 'text': '파트 하나만 골라 집중해서', 'url': reverse('category_list'),
         'icon': 'layer-group', 'count': f'{category_count}개 파트'},
        {'title': '오답노트', 'en': 'Wrong Answers', 'text': '마지막에 틀린 문제만 다시', 'url': reverse('review_wrong'),
         'icon': 'redo', 'count': f'{wrong_total}문제 남음' if wrong_total else '남은 오답 없음'},
        {'title': '북마크', 'en': 'Bookmarks', 'text': '표시해 둔 문제 복습', 'url': reverse('bookmarked_questions'),
         'icon': 'bookmark', 'count': f'{bookmarks}문제'},
        {'title': '내 기록', 'en': 'My Records', 'text': '응시 기록 · 점수 추이 · 약한 파트', 'url': reverse('analytics_overview'),
         'icon': 'chart-line', 'count': f'{len(results)}회 응시'},
    ]
    context = {
        'menu': menu, 'exams': exams,
        'attempts': len(results),
        'avg_pct': round(sum(scores) / len(scores)) if scores else None,
        'answered': sum((r.num_correct or 0) + (r.num_incorrect or 0) for r in results),
        'latest': results[-1] if results else None,
        'latest_pct': scores[-1] if scores else None,
        'weak': weak[0] if weak else None,
        'wrong_total': wrong_total,
    }
    return render(request, 'exam/question_home.html', context)

# ============ Results History & Analytics ============
@login_required
@user_is_approved
def my_results(request):
    """예전 '응시 기록' 주소 — '내 기록'(통계와 합친 화면)의 응시 기록으로."""
    return redirect(f"{reverse('analytics_overview')}#history")


def history_rows(results):
    """응시 기록 목록 (최근 순)."""
    rows = []
    for r in sorted(results, key=lambda r: (r.date_taken, r.id), reverse=True):
        correct, total, pct = result_counts(r)
        rows.append({
            'id': r.id, 'title': result_title(r), 'exam_id': r.exam_id, 'date_taken': r.date_taken,
            'correct': correct, 'total': total, 'score_percent': pct,
            'wrong': (r.num_incorrect or 0) + (r.num_unanswered or 0),
        })
    return rows


WEAK_PCT = 60       # 이보다 낮으면 약함 (빨강)
GOOD_PCT = 80       # 이 이상이면 잘함 (남색), 그 사이는 보통
MIN_SAMPLE = 5      # 이보다 적게 푼 카테고리는 '표본 적음' (약한 파트 순위에서 뺌)
RECENT_N = 10       # 최근 변화: 마지막 N문제 정답률 vs 그 전


def category_stats(results):
    """카테고리별 정답률 + 최근 변화. 정답 미정 문제 제외, 안 푼 문제는 틀린 것으로.
    results 는 시간순이어야 함 (최근 변화 계산)."""
    outcomes = defaultdict(list)
    for r in results:
        for d in r.detailed_results or []:
            if not isinstance(d, dict) or d.get('result') == 'noanswer':
                continue
            name = d.get('category') if d.get('category') not in (None, '', 'N/A') else '미분류'
            outcomes[name].append(d.get('result') == 'correct')
    # 카테고리 풀기 링크는 실제 카테고리이고 주소 패턴(urls.py)에 맞는 이름에만 단다
    category_names = {n for n in Category.objects.filter(name__in=outcomes).values_list('name', flat=True)
                      if re.fullmatch(r'[\w\s\(\)가-힣%-]+', n)}
    rows = []
    for name, seq in outcomes.items():
        graded, correct = len(seq), sum(seq)
        pct = round(correct / graded * 100)
        delta = None
        before = seq[:-RECENT_N]
        if len(seq) >= RECENT_N and len(before) >= MIN_SAMPLE:
            recent_pct = sum(seq[-RECENT_N:]) / RECENT_N * 100
            delta = round(recent_pct - sum(before) / len(before) * 100)
        rows.append({
            'name': name, 'correct': correct, 'graded': graded, 'pct': pct, 'delta': delta,
            'level': 'weak' if pct < WEAK_PCT else 'good' if pct >= GOOD_PCT else 'mid',
            'few': graded < MIN_SAMPLE, 'can_practice': name in category_names,
        })
    rows.sort(key=lambda c: (c['pct'], -c['graded'], c['name']))
    total_graded = sum(c['graded'] for c in rows)
    overall = round(sum(c['correct'] for c in rows) / total_graded * 100) if total_graded else 0
    return rows, overall


WRONG_RESULTS = ('incorrect', 'unanswered')


def question_history(user):
    """문제별 풀이 기록 {문제ID: {'seen', 'wrong', 'last', 'last_date'}} — 모든 응시 기록을 시간순으로 훑는다.
    'last' 가 틀림·안 풂이면 아직 못 맞힌 문제(오답노트)."""
    history = {}
    results = ExamResult.objects.filter(user=user).order_by('date_taken', 'id').only('date_taken', 'detailed_results')
    for r in results:
        for d in r.detailed_results or []:
            if not isinstance(d, dict) or not d.get('question_id') or d.get('result') == 'noanswer':
                continue
            h = history.setdefault(d['question_id'], {'seen': 0, 'wrong': 0, 'last': None, 'last_date': None})
            h['seen'] += 1
            h['wrong'] += d.get('result') in WRONG_RESULTS
            h['last'] = d.get('result')
            h['last_date'] = r.date_taken
    return history


def still_wrong_questions(user, exam=None):
    """마지막으로 풀었을 때 틀리거나 안 푼 문제 — 많이 틀린 순, 최근 순."""
    history = question_history(user)
    wrong_ids = [qid for qid, h in history.items() if h['last'] in WRONG_RESULTS]
    questions = visible_questions(user).filter(id__in=wrong_ids).select_related('category', 'exam')
    if exam is not None:
        questions = questions.filter(exam=exam)
    questions = list(questions)
    for q in questions:
        q.history = history[q.id]
    questions.sort(key=lambda q: (-q.history['wrong'], -q.history['last_date'].timestamp()))
    return questions


@login_required
@user_is_approved
def analytics_overview(request):
    """내 기록: 전체 또는 회차 하나를 골라 점수 추이·약한 파트·카테고리 정답률·오답노트·응시 기록을 한 화면에."""
    all_results = list(ExamResult.objects.filter(user=request.user).select_related('exam').order_by('date_taken', 'id'))
    exam_ids = {r.exam_id for r in all_results if r.exam_id}
    exams = list(visible_exams(request.user).filter(id__in=exam_ids).order_by('display_order', 'date_created'))
    exam = None
    if request.GET.get('exam', '').isdigit():
        exam = next((e for e in exams if e.id == int(request.GET['exam'])), None)
        if exam is None:
            return redirect('analytics_overview')
    results = [r for r in all_results if exam is None or r.exam_id == exam.id]

    context = {'exams': exams, 'exam': exam, 'has_data': bool(results)}
    if not results:
        return render(request, 'exam/stats.html', context)

    scores = [result_counts(r)[2] for r in results]
    latest = results[-1]
    context.update({
        'attempts': len(results),
        'latest_pct': scores[-1],
        'latest': latest,
        'avg_pct': round(sum(scores) / len(scores), 1),
        'best_pct': max(scores),
        'best': results[scores.index(max(scores))],
        'answered': sum((r.num_correct or 0) + (r.num_incorrect or 0) for r in results),
    })

    categories, overall_pct = category_stats(results)
    context['categories'] = categories
    context['overall_pct'] = overall_pct
    # 약한 파트: 충분히 푼(표본 5문제 이상) 카테고리 중 80% 미만, 낮은 순 3개
    context['weak_top'] = [c for c in categories if not c['few'] and c['pct'] < GOOD_PCT][:3]
    context['history'] = history_rows(results)
    # 점수 추이 (전체·회차 모두): 응시마다 점수, 전체는 최근 5회 이동평균도
    trend = [{'x': localtime(r.date_taken).strftime('%m/%d'), 'y': result_counts(r)[2],
              'label': f"{localtime(r.date_taken).strftime('%Y.%m.%d %H:%M')} · {result_title(r)}",
              'score': f'{result_counts(r)[0]}/{result_counts(r)[1]}'} for r in results]
    for i, t in enumerate(trend):
        window = trend[max(0, i - 4):i + 1]
        t['avg'] = round(sum(w['y'] for w in window) / len(window), 1)
    context['trend_json'] = json.dumps(trend)
    context['trend_count'] = len(trend)

    if exam is None:
        # 회차별 요약 (시험 회차가 아닌 카테고리·북마크·다시 풀기 기록은 합계에만 들어간다)
        rows = []
        for e in exams:
            er = [r for r in results if r.exam_id == e.id]
            if not er:
                continue
            ep = [result_counts(r)[2] for r in er]
            rows.append({'exam': e, 'attempts': len(er), 'latest_pct': ep[-1], 'best_pct': max(ep),
                         'avg_pct': round(sum(ep) / len(ep), 1), 'last_date': er[-1].date_taken})
        context['exam_rows'] = rows
        context['other_attempts'] = sum(1 for r in results if not r.exam_id)

    wrong = still_wrong_questions(request.user, exam)
    context['wrong_total'] = len(wrong)
    context['wrong_top'] = wrong[:12]
    return render(request, 'exam/stats.html', context)


def exam_analytics(request, exam_id):
    """예전 '회차별 통계' 주소 — 내 통계에서 회차를 고른 화면으로."""
    return redirect(f"{reverse('analytics_overview')}?exam={exam_id}")


def exam_stats_list(request):
    """예전 '회차 목록 통계' 주소 — 내 통계로."""
    return redirect('analytics_overview')


@login_required
@user_is_approved
def review_wrong(request):
    """오답노트 풀기: 마지막으로 풀었을 때 틀리거나 안 푼 문제들 (?exam= 로 회차 한정, 최대 100문제)."""
    exam = None
    if request.GET.get('exam', '').isdigit():
        exam = get_object_or_404(visible_exams(request.user), id=int(request.GET['exam']))
    questions = still_wrong_questions(request.user, exam)[:100]
    if not questions:
        return redirect(f"{reverse('analytics_overview')}{'?exam=%d' % exam.id if exam else ''}")
    bookmarked = set(Bookmark.objects.filter(user=request.user, question__in=questions).values_list('question_id', flat=True))
    for q in questions:
        q.is_bookmarked = q.id in bookmarked
    scope = exam.title if exam else '전체'
    return render(request, 'exam/quiz_unified.html', {
        'category_name': f'오답노트 · {scope}',
        'kicker': '오답노트',
        'quiz_key': f'review_{exam.id if exam else "all"}',
        'questions': questions,
    })


@require_POST
@login_required
@user_is_approved
def delete_result(request, result_id: int):
    r = get_object_or_404(ExamResult, pk=result_id, user=request.user)
    r.delete()
    next_url = request.POST.get('next', '')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect(f"{reverse('analytics_overview')}#history")

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
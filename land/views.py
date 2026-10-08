from datetime import timedelta

from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import is_member
from anhub.middleware import visit_totals


def _card(title, text, url, icon):
    # 외부 사이트는 새 탭으로 연다
    return {'title': title, 'text': text, 'url': url, 'icon': icon, 'external': url.startswith('http')}


def surgery_summary(user):
    """수술 현황판 요약 (현황판을 쓰는 특별 승인 회원만): 진행 중 수술 목록과 상태별 수.
    현황판(build_board)과 같은 기준으로 센다."""
    if not (user.is_authenticated and user.is_specially_approved):
        return None
    from schedule.models import SurgerySchedule
    from schedule.views import _room_sort_key, status_group

    counts = {'ongoing': 0, 'pending': 0, 'finished': 0}
    ongoing = []
    for case in SurgerySchedule.objects.filter(user=user).only(
            'room', 'surgery_name', 'status', 'duration', 'started_at', 'hold'):
        group = status_group(case.status)
        counts[group] += 1
        if group == 'ongoing':
            end = case.started_at + timedelta(minutes=case.duration) if case.started_at and case.duration else None
            ongoing.append({
                'room': case.room,
                'surgery_name': case.surgery_name,
                'expected_end': timezone.localtime(end) if end else None,
                'overdue': bool(end and end < timezone.now()),
            })
    if not sum(counts.values()):
        return None
    ongoing.sort(key=lambda c: _room_sort_key(c['room']))
    return {'counts': counts, 'ongoing': ongoing}


def home(request):
    sections = [
        {
            'id': 'anexus',
            'cols': 3,  # 넓은 화면에서 한 줄 카드 수 (6장 = 3장씩 두 줄)
            'title': 'ANExUS',
            'subtitle': 'Built-in tools for daily practice and study.',
            'cards': [
                _card('Board', 'Join discussions and share knowledge.', reverse('board_index'), 'fas fa-comments'),
                _card('Schedule', 'Surgery schedule for today.', reverse('schedule_dashboard'), 'fas fa-calendar-alt'),
                _card('Record', 'Anesthesia record for today.', reverse('anesthesia_record'), 'fas fa-pencil-alt'),
                _card('Anes Chat', 'Chat with other anesthesiologists.', 'https://escapebaek.github.io/chat/', 'fas fa-user-friends'),
                _card('Questions', 'Practice questions for the board exam.', reverse('question_home'), 'fas fa-question-circle'),
                _card('Journal Stand', 'Read the latest issues from our curated journals.', reverse('journal:journal_stand'), 'fas fa-book-open'),
            ],
        },
        {
            'id': 'tools',
            'cols': 3,  # 넓은 화면에서 한 줄 카드 수 (6장 = 3장씩 두 줄)
            'title': 'Calculators & Simulators',
            'subtitle': 'Quick calculations and hands-on learning.',
            'cards': [
                _card('Drug Calculator', 'Accurate drug dosage calculations.', reverse('calculator_drug'), 'fas fa-calculator'),
                _card('Pediatric Calculator', 'Accurate calculations for pediatric anesthesia.', reverse('calculator_pediatric'), 'fas fa-baby'),
                _card('Coagulation Guideline', 'Find the latest coagulation guidelines.', reverse('coag_index'), 'fas fa-vial'),
                _card('Drug Dictionary', 'Find the latest drug information.', reverse('drugdictionary:drug_info'), 'fas fa-pills'),
                _card('Virtual TEE', 'Virtual TEE for education.', 'https://pie.med.utoronto.ca/TEE/TEE_content/TEE_standardViews_intro.html', 'fas fa-heartbeat'),
                _card('Virtual FOB', 'Virtual FOB for education.', 'https://pie.med.utoronto.ca/VB/VB_content/simulation.html', 'fas fa-lungs'),
            ],
        },
        {
            'id': 'resources',
            'cols': 5,  # 넓은 화면에서 한 줄 카드 수 (끝줄이 한두 장만 남지 않게)
            'title': 'Resources',
            'subtitle': 'Societies, references and learning materials.',
            'cards': [
                _card('KSA', 'Korean Society of Anesthesiologists.', 'https://www.anesthesia.or.kr/', 'fas fa-user-md'),
                _card('SNUH Anesthesia', 'More information for alumni.', 'https://dept.snuh.org/dept/AN/index.do', 'fas fa-hospital'),
                _card('NYSORA', 'Renowned educational organization in anesthesiology.', 'https://www.nysora.com/', 'fas fa-book-medical'),
                _card('OrphanAnesthesia', 'Anesthesia care for rare diseases.', 'https://www.orphananesthesia.eu/en/rare-diseases/published-guidelines.html', 'fas fa-dna'),
                _card('ACCRAC', 'Podcast for board examination.', 'https://accrac.com/', 'fas fa-podcast'),
            ],
        },
    ]
    return render(request, 'land/home.html', {
        'sections': sections,
        'is_member': is_member(request.user),
        'surgeries': surgery_summary(request.user),
        'visits': _visits(),
    })


def _visits():
    try:
        total, today = visit_totals()
    except Exception:           # 방문 수를 못 읽어도 첫 화면은 떠야 함
        return None
    return {'total': total, 'today': today}

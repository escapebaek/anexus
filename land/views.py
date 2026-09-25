from django.shortcuts import render
from django.urls import reverse

from accounts.decorators import is_member


def _card(title, text, url, icon):
    # 외부 사이트는 새 탭으로 연다
    return {'title': title, 'text': text, 'url': url, 'icon': icon, 'external': url.startswith('http')}


def home(request):
    sections = [
        {
            'id': 'anexus',
            'cols': 4,  # 넓은 화면에서 한 줄 카드 수 (끝줄이 한두 장만 남지 않게)
            'title': 'ANExuS',
            'subtitle': 'Built-in tools for daily practice and study.',
            'cards': [
                _card('Board', 'Join discussions and share knowledge.', reverse('board_index'), 'fas fa-comments'),
                _card('Questions', 'Practice questions for the board exam.', reverse('question_home'), 'fas fa-question-circle'),
                _card('Schedule', 'Surgery schedule for today.', reverse('schedule_dashboard'), 'fas fa-calendar-alt'),
                _card('Record', 'Anesthesia record for today.', reverse('anesthesia_record'), 'fas fa-pencil-alt'),
                _card('Journal Stand', 'Read the latest issues from our curated journals.', reverse('journal:journal_stand'), 'fas fa-book-open'),
                _card('Drug Dictionary', 'Find the latest drug information.', reverse('drugdictionary:drug_info'), 'fas fa-pills'),
                _card('Coagulation Guideline', 'Find the latest coagulation guidelines.', reverse('coag_index'), 'fas fa-vial'),
            ],
        },
        {
            'id': 'tools',
            'cols': 5,  # 넓은 화면에서 한 줄 카드 수 (끝줄이 한두 장만 남지 않게)
            'title': 'Calculators & Simulators',
            'subtitle': 'Quick calculations and hands-on learning.',
            'cards': [
                _card('Drug Calculator', 'Accurate drug dosage calculations.', 'https://escapebaek.github.io/anesthesia-calculator/', 'fas fa-calculator'),
                _card('Pediatric Calculator', 'Accurate calculations for pediatric anesthesia.', 'https://escapebaek.github.io/pediatric-anesthesia-calculator/', 'fas fa-baby'),
                _card('Anes Chat', 'Chat with other anesthesiologists.', 'https://escapebaek.github.io/chat/', 'fas fa-user-friends'),
                _card('Virtual TEE', 'Virtual TEE for education.', 'https://pie.med.utoronto.ca/TEE/TEE_content/TEE_standardViews_intro.html', 'fas fa-heartbeat'),
                _card('Virtual FOB', 'Virtual FOB for education.', 'https://pie.med.utoronto.ca/VB/VB_content/simulation.html', 'fas fa-lungs'),
            ],
        },
        {
            'id': 'resources',
            'cols': 6,  # 넓은 화면에서 한 줄 카드 수 (끝줄이 한두 장만 남지 않게)
            'title': 'Resources',
            'subtitle': 'Societies, references and learning materials.',
            'cards': [
                _card('Trends in Anesthesia', 'Recent anesthesia trends in major journals.', 'https://escapebaek.github.io/trends_anesthesia/', 'fas fa-chart-line'),
                _card('KSA', 'Korean Society of Anesthesiologists.', 'https://www.anesthesia.or.kr/', 'fas fa-user-md'),
                _card('SNUH Anesthesia', 'More information for alumni.', 'https://dept.snuh.org/dept/AN/index.do', 'fas fa-hospital'),
                _card('NYSORA', 'Renowned educational organization in anesthesiology.', 'https://www.nysora.com/', 'fas fa-book-medical'),
                _card('OrphanAnesthesia', 'Anesthesia care for rare diseases.', 'https://www.orphananesthesia.eu/en/rare-diseases/published-guidelines.html', 'fas fa-dna'),
                _card('ACCRAC', 'Podcast for board examination.', 'https://accrac.com/', 'fas fa-podcast'),
            ],
        },
    ]
    return render(request, 'land/home.html', {'sections': sections, 'is_member': is_member(request.user)})

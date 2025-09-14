from django.shortcuts import render, reverse

def home(request):
    cards = [
        {"title": "Board", "text": "Join discussions and share knowledge.", "url": reverse('board_index'), "icon": "fas fa-comments"},
        {"title": "Drug Calculator", "text": "Accurate drug dosage calculations.", "url": "https://escapebaek.github.io/anesthesia-calculator/", "icon": "fas fa-calculator"},
        {"title": "Pediatric Calculator", "text": "Accurate calculations for pediatric anesthesia.", "url": "https://escapebaek.github.io/pediatric-anesthesia-calculator/", "icon": "fas fa-baby"},
        {"title": "Coagulation Guideline", "text": "Find the latest coagulation guidelines.", "url": reverse('coag_index'), "icon": "fas fa-vial"},
        {"title": "Questions", "text": "More information about board exam.", "url": reverse('question_home'), "icon": "fas fa-question-circle"},
        {"title": "Schedule", "text": "Surgery schedule for today.", "url": reverse('schedule_dashboard'), "icon": "fas fa-calendar-alt"},
        {"title": "Anes Chat", "text": "Chat with other anesthesiologists.", "url": "https://escapebaek.github.io/chat/", "icon": "fas fa-comments"},
        {"title": "Record", "text": "Anesthesia record for today.", "url": reverse('anesthesia_record'), "icon": "fas fa-pencil-alt"},
        {"title": "Drug Dictionary", "text": "Find the latest drug information.", "url": reverse('drugdictionary:drug_info'), "icon": "fas fa-pills"},
        {"title": "Trends in Anesthesia", "text": "Recents anesthesia trends in major journals.", "url": "https://escapebaek.github.io/trends_anesthesia/", "icon": "fas fa-link"},
        {"title": "SNUH Anesthesia", "text": "More information for alumni.", "url": "https://dept.snuh.org/dept/AN/index.do", "icon": "fas fa-hospital"},
        {"title": "KSA", "text": "Korean Society of Anesthesiologists.", "url": "https://www.anesthesia.or.kr/", "icon": "fas fa-user-md"},
        {"title": "NYSORA", "text": "World-wide renowned educational organization with focus in anesthesiology.", "url": "https://www.nysora.com/", "icon": "fas fa-book-medical"},
        {"title": "OrphanAnesthesia", "text": "Anesthesia care for rare diseases.", "url": "https://www.orphananesthesia.eu/en/rare-diseases/published-guidelines.html", "icon": "fas fa-dna"},
        {"title": "Virtual TEE", "text": "Virtual TEE for education.", "url": "https://pie.med.utoronto.ca/TEE/TEE_content/TEE_standardViews_intro.html", "icon": "fas fa-heartbeat"},
        {"title": "Virtual FOB", "text": "Virtual FOB for education.", "url": "https://pie.med.utoronto.ca/VB/VB_content/simulation.html", "icon": "fas fa-lungs"},
        {"title": "ACCRAC", "text": "Podcast for board examination.", "url": "https://accrac.com/", "icon": "fas fa-podcast"},
    ]
    return render(request, 'land/home.html', {'cards': cards})

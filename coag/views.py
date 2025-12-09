from django.shortcuts import render
from coag.models import Coag
from accounts.decorators import user_is_approved

@user_is_approved
def coag_landing_page(request):
    return render(request, 'coag/landing_page.html')

# Create your views here.
@user_is_approved
def coag_index(request):
    # Coag 객체들을 drugName을 기준으로 알파벳 순서로 정렬
    coags = Coag.objects.all().order_by('drugName')
    context = {
        'coags': coags,
    }
    return render(request, 'coag/coag_index.html', context)

@user_is_approved
def coag_detail(request, drugName):
    coag = Coag.objects.get(drugName=drugName)
    context = {
        'coag': coag,
    }
    return render(request, 'coag/coag_detail.html', context)

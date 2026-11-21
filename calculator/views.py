from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.decorators import user_is_approved

MODES = ('adult', 'ped')


# 예전에는 github.io 의 별도 사이트였던 계산기 - 계산은 모두 브라우저(static/js/calculator)에서 함.
# 성인·소아를 한 화면에 두고 토글로 바꿈 (?mode=adult|ped, 없으면 브라우저가 마지막 모드를 기억).
@user_is_approved
def calculator(request):
    mode = request.GET.get('mode')
    return render(request, 'calculator/calculator.html', {'mode': mode if mode in MODES else 'adult'})


# 예전 주소 (즐겨찾기·외부 링크) → 한 화면 계산기의 해당 모드로
def drug_calculator(request):
    return redirect(f"{reverse('calculator')}?mode=adult", permanent=True)


def pediatric_calculator(request):
    return redirect(f"{reverse('calculator')}?mode=ped", permanent=True)

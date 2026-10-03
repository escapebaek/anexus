from django.shortcuts import render

from accounts.decorators import user_is_approved


# 예전에는 github.io 의 별도 사이트였던 계산기 - 계산은 모두 브라우저(static/js/calculator)에서 함
@user_is_approved
def drug_calculator(request):
    return render(request, 'calculator/drug.html')


@user_is_approved
def pediatric_calculator(request):
    return render(request, 'calculator/pediatric.html')

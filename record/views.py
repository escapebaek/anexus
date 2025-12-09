from django.shortcuts import render, redirect, get_object_or_404
from .models import AnesthesiaRecord, FreeTextNote
from .forms import AnesthesiaRecordForm, FreeTextNoteForm
from django.utils.timezone import now
from django.contrib.auth.decorators import login_required
from accounts.decorators import user_is_approved

@login_required
@user_is_approved
def anesthesia_record_view(request):
    # 현재 로그인한 사용자에 해당하는 Free Text Note 가져오기
    free_text_note = FreeTextNote.objects.filter(user=request.user).first()
    
    if request.method == "POST":
        # 두 개의 폼이 같은 URL로 POST될 때 submit 버튼 이름으로 구분합니다.
        if "save_free_text" in request.POST:
            form_free = FreeTextNoteForm(request.POST, instance=free_text_note)
            if form_free.is_valid():
                note = form_free.save(commit=False)
                note.user = request.user
                note.save()
                return redirect('anesthesia_record')
        else:
            record_id = request.POST.get('record_id', None)
            if record_id:
                # 해당 record가 현재 로그인한 사용자의 record인지 확인
                record = get_object_or_404(AnesthesiaRecord, pk=record_id, user=request.user)
                form = AnesthesiaRecordForm(request.POST, instance=record)
            else:
                form = AnesthesiaRecordForm(request.POST)
            if form.is_valid():
                record = form.save(commit=False)
                record.user = request.user  # 로그인한 사용자로 지정
                if not record.timestamp:
                    record.timestamp = now()
                record.extra_vitals = form.cleaned_data.get('extra_vitals', {})
                record.save()
                return redirect('anesthesia_record')
    else:
        form = AnesthesiaRecordForm()
        form_free = FreeTextNoteForm(instance=free_text_note)
    
    # 현재 로그인한 사용자의 레코드만 조회
    records = AnesthesiaRecord.objects.filter(user=request.user).order_by('-timestamp')
    return render(request, 'record/anesthesia_record.html', {
        'form': form,
        'records': records,
        'form_free': form_free,
    })

@login_required
@user_is_approved
def delete_record(request, record_id):
    record = get_object_or_404(AnesthesiaRecord, pk=record_id, user=request.user)
    record.delete()
    return redirect('anesthesia_record')

@login_required
@user_is_approved
def reset_all(request):
    if request.method == "POST":
        AnesthesiaRecord.objects.filter(user=request.user).delete()
        FreeTextNote.objects.filter(user=request.user).delete()
    return redirect('anesthesia_record')

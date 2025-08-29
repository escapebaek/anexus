from django import forms
from .models import AnesthesiaRecord, FreeTextNote
import json

class AnesthesiaRecordForm(forms.ModelForm):
    # 동적으로 추가한 extra vital 값들을 JSON 문자열로 전송
    extra_vitals_json = forms.CharField(widget=forms.HiddenInput(), required=False)
    # 사용자가 timestamp를 입력할 수 있도록 (입력하지 않으면 뷰에서 현재 시간 할당)
    timestamp = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'})
    )
    
    class Meta:
        model = AnesthesiaRecord
        fields = ['patient_id', 'timestamp', 'hr', 'sbp', 'dbp', 'spo2', 'extra_vitals_json', 'additional_notes']
        widgets = {
            'additional_notes': forms.Textarea(attrs={'rows': 3, 'cols': 50}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        extra_json = cleaned_data.get('extra_vitals_json', '')
        if extra_json:
            try:
                extra_vitals = json.loads(extra_json)
                cleaned_data['extra_vitals'] = extra_vitals
            except json.JSONDecodeError:
                self.add_error('extra_vitals_json', 'Invalid JSON format for extra vitals.')
        else:
            cleaned_data['extra_vitals'] = {}
        return cleaned_data

class FreeTextNoteForm(forms.ModelForm):
    class Meta:
        model = FreeTextNote
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 5, 'cols': 60}),
        }

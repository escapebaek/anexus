from django import forms

ALLOWED_EXTENSIONS = (".xlsx", ".xls", ".csv", ".txt")


class ScheduleUploadForm(forms.Form):
    file = forms.FileField()

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        name = uploaded_file.name.lower()
        if not name.endswith(ALLOWED_EXTENSIONS):
            raise forms.ValidationError(
                "지원하지 않는 파일 형식입니다. (지원 형식: .xlsx, .xls, .csv, .txt)"
            )
        return uploaded_file

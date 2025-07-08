from django import forms


class DeleteAccountReasonForm(forms.Form):
    application_id = forms.IntegerField(
        label="Appliction id:",
        required=True,
        widget=forms.NumberInput(attrs={'placeholder': 'Cari...', 'required': True}),
    )

    reason = forms.CharField(
        required=True,
        widget=forms.Textarea(
            attrs={
                'required': True,
                'placeholder': 'Contoh: Akun tidak diberikan limit, jadi ingin menghapus akun.',
                'class': 'form-control',
                'rows': 6,
            }
        ),
    )

    def clean_application_id(self):
        data = self.cleaned_data["application_id"]
        return data

    def clean_reason(self):
        data = self.cleaned_data["reason"]
        return data

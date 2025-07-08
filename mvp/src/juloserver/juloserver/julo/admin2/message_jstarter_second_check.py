from django import forms
from juloserver.julo.models import FeatureSetting
from juloserver.julo_starter.constants import NotificationSetJStarter


class SettingMessageJStarterForm(forms.ModelForm):

    dukcapil_true_heimdall_true = forms.CharField(
        widget=forms.TextInput(attrs={'style': 'display:none;'}),
        required=False, label='Dukcapil True & Heimdall True Partial Limit')
    title_case_ok = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Title')
    body_case_ok = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Body')
    destination_case_ok = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Destination page (Android)')

    # for case offering to J1
    dukcapil_true_heimdall_false = forms.CharField(
        widget=forms.TextInput(attrs={'style': 'display:none'}),
        required=False, label='Dukcapil True & Heimdall False')
    title_case_offer = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Title')
    body_case_offer = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Body')
    destination_case_offer = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Destination page (Android)')

    # for case rejected
    dukcapil_false = forms.CharField(
        widget=forms.TextInput(attrs={'style': 'display:none'}),
        required=False, label='Dukcapil False')
    title_case_rejected = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Title')
    body_case_rejected = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Body')
    destination_case_rejected = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Destination page (Android)')

    # Full DV
    dukcapil_true_heimdall_true_full_dv = forms.CharField(
        widget=forms.TextInput(attrs={'style': 'display:none;'}),
        required=False, label='Dukcapil True & Heimdall True Full DV'
    )
    title_case_ok_full_dv = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Title'
    )
    body_case_ok_full_dv = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Body'
    )
    destination_case_ok_full_dv = forms.CharField(
        widget=forms.TextInput(attrs={'size': 70}),
        required=True, label='Destination page (Android)'
    )

    def __init__(self, *args, **kwargs):
        super(SettingMessageJStarterForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            if instance.parameters:
                param = instance.parameters
                self.set_value_from_param(param)

    class Meta:
        model = FeatureSetting
        exclude = ['id', 'parameters']

    def clean(self):
        data = super(SettingMessageJStarterForm, self).clean()
        error_message = validate_param(data)
        if error_message:
            raise forms.ValidationError(error_message)

        return data

    def set_value_from_param(self, param):

        if param:
            # Set alias for looping target
            matrix_target = {
                NotificationSetJStarter.KEY_MESSAGE_OK: 'ok',
                NotificationSetJStarter.KEY_MESSAGE_OK_FULL_DV: 'ok_full_dv',
                NotificationSetJStarter.KEY_MESSAGE_OFFER: 'offer',
                NotificationSetJStarter.KEY_MESSAGE_REJECTED: 'rejected'
            }

            prefix_key = '_case_'
            title = NotificationSetJStarter.KEY_TITLE
            body = NotificationSetJStarter.KEY_BODY
            destination = NotificationSetJStarter.KEY_DESTINATION

            for key in param:
                if key in matrix_target:
                    self.fields[title + prefix_key + matrix_target[key]].initial = param[key][title]
                    self.fields[body + prefix_key + matrix_target[key]].initial = param[key][body]
                    self.fields[destination + prefix_key + matrix_target[key]].initial = param[key][destination]


def validate_param(parameters):

    if not parameters:
        return 'This parameters cannot empty.'

    if not parameters['is_active']:
        return 'This configuration need to active.'

    if 'category' not in parameters:
        return 'Please fill out the category.'

    if 'description' not in parameters:
        return 'Please fill out the description.'


def default_param():
    return {
        "dukcapil_true_heimdall_true": {
            "title": "Selamat Akun Kamu Sudah Aktif!",
            "body": "Limitmu sudah tersedia dan bisa langsung kamu gunakan untuk transaksi, lho!",
            "destination": "julo_starter_second_check_ok"
        },
        "dukcapil_false": {
            "title": "Pembuatan Akun JULO Starter Gagal",
            "body": "Kamu belum memenuhi kriteria JULO Starter",
            "destination": "julo_starter_second_check_rejected"
        },
        "dukcapil_true_heimdall_false": {
            "title": "Pembuatan Akun JULO Starter Gagal",
            "body": "Kamu belum memenuhi kriteria. Tapi kamu masih bisa ajukan pembuatan akun JULO Kredit Digital, kok!",
            "destination": "julo_starter_eligbility_j1_offer"
        },
        "dukcapil_true_heimdall_true_full_dv": {
            "title": "Limitmu Sedang Dihitung, Nih!",
            "body": "Prosesnya sebentar banget, kok! Udah nggak sabar mau tau limit kamu, ya?",
            "destination": "julo_starter_second_check_ok_full_dv"
        },
    }


def binding_param(param):

    parameter = default_param()
    if param:
        for key in parameter:
            if key == NotificationSetJStarter.KEY_MESSAGE_OK:
                parameter[key]['title'] = param['title_case_ok']
                parameter[key]['body'] = param['body_case_ok']
                parameter[key]['destination'] = param['destination_case_ok']
            elif key == NotificationSetJStarter.KEY_MESSAGE_OFFER:
                parameter[key]['title'] = param['title_case_offer']
                parameter[key]['body'] = param['body_case_offer']
                parameter[key]['destination'] = param['destination_case_offer']
            elif key == NotificationSetJStarter.KEY_MESSAGE_REJECTED:
                parameter[key]['title'] = param['title_case_rejected']
                parameter[key]['body'] = param['body_case_rejected']
                parameter[key]['destination'] = param['destination_case_rejected']
            elif key == NotificationSetJStarter.KEY_MESSAGE_OK_FULL_DV:
                parameter[key]['title'] = param['title_case_ok_full_dv']
                parameter[key]['body'] = param['body_case_ok_full_dv']
                parameter[key]['destination'] = param['destination_case_ok_full_dv']

    return parameter


def save_model_setup_message_jstarter(obj, form):
    data = form.data

    # prepare data field for update
    obj.is_active = True
    obj.category = data.get('category')
    obj.description = data.get('description')
    obj.parameters = binding_param(data)

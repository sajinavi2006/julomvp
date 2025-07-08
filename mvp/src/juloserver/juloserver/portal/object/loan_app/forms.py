from builtins import object
from django import forms
from django.forms import ModelForm

from django.contrib.admin.widgets import AdminFileWidget
from django.forms.widgets import Textarea, TextInput, SelectMultiple
from django.forms.widgets import RadioSelect, PasswordInput, Select
# from django.forms.models import BaseInlineFormSet, inlineformset_factory

from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.models import User

from multiupload.fields import MultiMediaField

from juloserver.julo.models import Image, StatusLookup
from juloserver.julo.services import get_allowed_application_statuses_for_ops
from julo_status.models import StatusAppSelection, ReasonStatusAppSelection

from .constants import ImageUploadType


class HorizontalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'&nbsp;&nbsp;&nbsp;\n'.join([u'%s\n' % w for w in self]))


class ImageUploadForm(ModelForm):
    """ User ask for resetting password and change to default password,
        then suggest to change it after login
    """
    class Meta(object):
        # 'image_source', 'url' , 
        fields = ('image_type' , 'image',)
        model = Image
        widgets = {
            # 'image_source':TextInput(attrs={
            #     'size':model._meta.get_field('image_source').max_length,
            #     'class': 'form-control',
            #     'required': "",
            #     'maxlength':model._meta.get_field('image_source').max_length,
            #     'placeholder':'ApplicationID for this image'}),
            'image' : AdminFileWidget(attrs={
                'class':'form-control',
                }),
            'image_type': Select(choices = ImageUploadType.get_choices(),
                attrs={
                'class': 'form-control',
                'required': "",
                'placeholder':'Tipe Dokumen'}),
        }

    def clean_image(self):
        if 'image' in self.cleaned_data:
            # check if they not null each other
            image = self.cleaned_data['image']
            if image:
                return image
        raise forms.ValidationError("Upload Dokumen Tidak Boleh Kosong !!!")
 



class MultiImageUploadForm(forms.Form):
    image_type_choices = ImageUploadType.get_choices()

    # attachments = MultiFileField(min_num=1, max_num=3, max_file_size=1024*1024*5)
    # If you need to upload media files, you can use this:
    attachments = MultiMediaField(
        min_num=1, 
        max_num=10, 
        max_file_size=1024*1024*10,
        media_type='image'  # 'audio', 'video' or 'image'
    )
    image_type_1 = forms.ChoiceField(required = False,
        choices = image_type_choices,
        widget  = Select(attrs={
                'required': False,
                'class':'form-control',
                }),
    )
    image_type_2 = forms.ChoiceField(required = False,
        choices = image_type_choices
    )
    image_type_3 = forms.ChoiceField(required = False,
        choices = image_type_choices
    )
    image_type_4 = forms.ChoiceField(required = False,
        choices = image_type_choices
    )
    image_type_5 = forms.ChoiceField(required = False,
        choices = image_type_choices
    )
    image_type_6 = forms.ChoiceField(required = False,
        choices = image_type_choices
    )
    image_type_7 = forms.ChoiceField(required = False,
        choices = image_type_choices
    )
    image_type_8 = forms.ChoiceField(required = False,
        choices = image_type_choices
    )
    image_type_9 = forms.ChoiceField(required = False,
        choices = image_type_choices
    )
    image_type_10 = forms.ChoiceField(required = False,
        choices = image_type_choices
    )
    # For images (requires Pillow for validation):
    # attachments = MultiImageField(min_num=1, max_num=3, max_file_size=1024*1024*5)


class StatusChangesForm(forms.Form):
    """
        please use ModelChoiceField instead of ChoiceField if using queryset
    """

    status_to = forms.ModelChoiceField(required = True,
        # choices = [],
        queryset = StatusLookup.objects.all(),
        widget  = Select(attrs={
                'required': "",
                'class':'form-control',
                }),
    )
    reason = forms.ModelMultipleChoiceField(required = True,
        queryset = ReasonStatusAppSelection.objects.all(),
        widget  = SelectMultiple(attrs={
                'required': "",
                'class':'form-control',
                'style': 'height: 220px;'
                }),
    )
    notes = forms.CharField(required = True,
        widget  = Textarea(attrs={ 'rows': 10,
                    'class': 'form-control',
                    'required': "",
                    'placeholder':'Masukan catatan pada perubahana status aplikasi ini'}),
    )

    def __init__(self, status_code, application_id, *args, **kwargs):
        super(StatusChangesForm, self).__init__(*args, **kwargs)
        # print "status_code: ", status_code

        #get allow status from julo core service
        status_choices = []
        allowed_statuses = get_allowed_application_statuses_for_ops(
            int(status_code.status_code), application_id)
        if allowed_statuses:
            status_choices = [
                [status.code, "%s - %s" % (status.code, status.desc)] for status in allowed_statuses
            ]
        # else:
        #     status_queryset = StatusAppSelection.objects.filter(
        #         status_from=status_code).order_by('status_to__status_code')
        #     status_choices = [[item.status_to.status_code, item] for item in status_queryset]
        
        status_choices.insert(0,[None, '-- Pilih --'])
        # print "status_choices: ", status_choices
        self.fields['status_to'].choices = status_choices

        # self.fields['status_to'].queryset = StatusAppSelection.objects.filter(
        #     status_from=status_code).order_by('status_to__status_code')

    def clean_status_to(self):
        if 'status_to' in self.cleaned_data:
            status_to_data = self.cleaned_data['status_to']
            if status_to_data:
                return status_to_data

        raise forms.ValidationError("Status Perpindahan belum dipilih!!!")

    def clean_reason(self):
        if 'reason' in self.cleaned_data:
            reason_data = self.cleaned_data['reason']
            if reason_data:
                return reason_data

        raise forms.ValidationError("Alasan Perpindahan belum dipilih!!!")


class ValidationCheckForm(forms.Form):

    YES_NO_NULL_CHOICES = [(1, 'Ya'), (0, 'Tidak'), (2, 'Blum Cek')]

    UNSELECTED = 0
    LESS_THEN_100M = 1
    BETWEEN_100_500_M = 2
    BETWEEN_500_1000_M = 3
    GREATER_THAN_1000M = 4
    
    GPS_RANGE = (
        (UNSELECTED, '----------'),
        (LESS_THEN_100M, '< 100 meter'),
        (BETWEEN_100_500_M, '100-500 meter'),
        (BETWEEN_500_1000_M, '500-1000 meter'),
        (GREATER_THAN_1000M, '> 1000 meter'),
    )

    check_1  = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
            attrs={
            'name':'radio4',
            },
         renderer=HorizontalRadioRenderer))
    check_2  = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_3  = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_4  = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_5  = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_6  = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_7  = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_8  = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_9  = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_10 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_11 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_12 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_13 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_14 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_15 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_16 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_17 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))

    check_18  = forms.CharField(required = False, max_length=15,
            widget=TextInput(attrs={
                'class':"mask tch3" ,'data-bts-button-down-class':"btn btn-default btn-outline",
                'data-bts-button-up-class':"btn btn-default btn-outline"
                }))
    check_19 = forms.CharField(required = False, max_length=15,
            widget=TextInput(attrs={
                'class':"mask tch3" ,'data-bts-button-down-class':"btn btn-default btn-outline",
                'data-bts-button-up-class':"btn btn-default btn-outline"
                }))
    check_20 = forms.CharField(required = False, max_length=15,
            widget=TextInput(attrs={
                'class':"mask tch3" ,'data-bts-button-down-class':"btn btn-default btn-outline",
                'data-bts-button-up-class':"btn btn-default btn-outline"
                }))
    check_21 = forms.CharField(required = False, max_length=15,
            widget=TextInput(attrs={
                'class':"mask tch3" ,'data-bts-button-down-class':"btn btn-default btn-outline",
                'data-bts-button-up-class':"btn btn-default btn-outline"
                }))
    check_22 = forms.CharField(required = False, max_length=15,
            widget=TextInput(attrs={
                'class':"mask tch3" ,'data-bts-button-down-class':"btn btn-default btn-outline",
                'data-bts-button-up-class':"btn btn-default btn-outline"
                }))
    check_23 = forms.CharField(required = False, max_length=15,
            widget=TextInput(attrs={
                'class':"mask tch3" ,'data-bts-button-down-class':"btn btn-default btn-outline",
                'data-bts-button-up-class':"btn btn-default btn-outline"
                }))
    check_24 = forms.CharField(required = False, max_length=15,
            widget=TextInput(attrs={
                'class':"mask tch3" ,'data-bts-button-down-class':"btn btn-default btn-outline",
                'data-bts-button-up-class':"btn btn-default btn-outline"
                }))
    check_25 = forms.CharField(required = False, max_length=15,
            widget=TextInput(attrs={
                'class':"mask tch3" ,'data-bts-button-down-class':"btn btn-default btn-outline",
                'data-bts-button-up-class':"btn btn-default btn-outline"
                }))

    check_26 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_27 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_28 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_29 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_30 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_31 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_32 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_33 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_34 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_35 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_36 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_37 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_38 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_39 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_40 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_41 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_42 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_43 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_44 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_45 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_46 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_47 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_48 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_49 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_50 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_51 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_52 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))

    check_53 = forms.CharField(required = False, max_length=15,
            widget=TextInput(attrs={
                'class':"mask tch3" ,'data-bts-button-down-class':"btn btn-default btn-outline",
                'data-bts-button-up-class':"btn btn-default btn-outline"
                }))

    check_54 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_55 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))

    check_56 = forms.IntegerField(required = False,
        widget=Select(choices=GPS_RANGE,
        attrs={
            'class': 'form-control',
        }))
    check_57 = forms.IntegerField(required = False,
        widget=Select(choices=GPS_RANGE,
        attrs={
            'class': 'form-control',
        }))

    check_58 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))

    check_59 = forms.CharField(required = False, max_length=150,
        widget=TextInput(attrs={
            'class':"form-control mask",
        }))

    check_60 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))

    check_61 = forms.CharField(required = False, max_length=150,
        widget=TextInput(attrs={
            'class':"form-control mask",
        }))
    check_62 = forms.CharField(required = False, max_length=150,
        widget=TextInput(attrs={
            'class':"form-control mask",
        }))
    check_63 = forms.CharField(required = False, max_length=150,
        widget=TextInput(attrs={
            'class':"form-control mask",
        }))
    check_64 = forms.CharField(required = False, max_length=150,
        widget=TextInput(attrs={
            'class':"form-control mask",
        }))

    check_65 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_66 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_67 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_68 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_69 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_70 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_71 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_72 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_73 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_74 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_75 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))
    check_76 = forms.NullBooleanField(required = False,
         widget=RadioSelect(choices=YES_NO_NULL_CHOICES,
         renderer=HorizontalRadioRenderer))


    def __init__(self, app_check_queryset, *args, **kwargs):
        super(ValidationCheckForm, self).__init__(*args, **kwargs)

        for check_obj in app_check_queryset:
            _field_check = 'check_%d' % check_obj.sequence
            if check_obj.check_type == 1:
                _choice_value = 3
                if(check_obj.is_okay == True):
                    _choice_value = 1
                elif(check_obj.is_okay == False):
                    _choice_value = 0
                else:
                    _choice_value = 2
                self.fields[_field_check].initial = _choice_value
                # print '%s: %s' % (_field_check, check_obj.is_okay)
            elif check_obj.check_type == 2:
                self.fields[_field_check].initial = check_obj.text_value
            elif check_obj.check_type == 3:
                self.fields[_field_check].initial = check_obj.number_value
            else:
                self.fields[_field_check].initial = check_obj.number_value

class NoteForm(forms.Form):

    notes = forms.CharField(required = True,
        widget  = Textarea(attrs={ 'rows': 15,
                    'class': 'form-control',
                    'required': True,
                    'placeholder':'Masukan catatan pada aplikasi ini'}),
    )

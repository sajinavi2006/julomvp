from __future__ import unicode_literals
from builtins import str
from builtins import object

import os
from datetime import timedelta
from uuid import uuid4
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone

# Create your models here.
from django.contrib.postgres.fields import (
    JSONField,
    ArrayField,
)
from django.dispatch import receiver

from juloserver.julocore.data.models import (
    JuloModelManager,
    TimeStampedModel,
    GetInstanceMixin,
)
from juloserver.account.models import Account
from juloserver.julo.models import (
    Image,
    Customer,
    Payment,
    Application,
)
from juloserver.julocore.customized_psycopg2.models import (
    BigForeignKey,
    BigAutoField,
)
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    CardProperty,
    SmsTspVendorConstants,
    StreamlinedCommCampaignConstants,
    CommsUserSegmentConstants,
)
from juloserver.julo.constants import NexmoRobocallConst
from cuser.fields import CurrentUserField
from phonenumber_field.modelfields import PhoneNumberField

from juloserver.julo.models import CommsProviderLookup


def voice_message_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    filename = '{}.{}'.format(uuid4().hex, ext)

    # return the whole path to the file
    return os.path.join('voice_upload', filename)


class StreamlinedMessage(TimeStampedModel):
    id = models.AutoField(db_column='stream_lined_message_id', primary_key=True)
    message_content = models.TextField()
    parameter = ArrayField(models.CharField(max_length=100), default=list)
    info_card_property = models.ForeignKey(
        'InfoCardProperty', models.DO_NOTHING, db_column='info_card_property_id', null=True)

    class Meta(object):
        db_table = 'stream_lined_message'


class StreamlinedCommunicationManager(GetInstanceMixin, JuloModelManager):
    pass


class StreamlinedCommunication(TimeStampedModel):
    id = models.AutoField(db_column='stream_lined_communication_id', primary_key=True)
    status_code = models.ForeignKey(
        'julo.StatusLookup', models.DO_NOTHING, db_column='status_code', blank=True, null=True
    )
    status = models.TextField(blank=True, null=True)
    dpd = models.IntegerField(blank=True, null=True)
    communication_platform = models.CharField(max_length=50,
                                              choices=CommunicationPlatform.CHOICES)
    message = models.ForeignKey(
        StreamlinedMessage, models.DO_NOTHING, db_column='message_id')
    description = models.TextField(blank=True, null=True)
    criteria = JSONField(default=None, blank=True, null=True)
    template_code = models.CharField(max_length=100, blank=True, null=True)
    moengage_template_code = models.CharField(max_length=100, blank=True, null=True)
    ptp = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=False)
    product = models.TextField(blank=True, null=True)
    type = models.TextField(blank=True, null=True)
    attempts = models.IntegerField(blank=True, null=True)
    time_sent = models.TextField(blank=True, null=True)
    call_hours = ArrayField(models.CharField(max_length=100), default=list)
    function_name = ArrayField(models.CharField(max_length=100), default=list)
    is_automated = models.BooleanField(default=True, blank=True)
    time_out_duration = models.IntegerField(default=NexmoRobocallConst.TIME_OUT_DURATION,
                                            blank=True, null=True)
    heading_title = models.CharField(max_length=100, blank=True, null=True)
    subject = models.TextField(blank=True, null=True)
    pre_header = models.TextField(blank=True, null=True)
    exclude_risky_customer = models.BooleanField(
        default=False, verbose_name='Exclude isrisky dpd- ?')
    extra_conditions = models.TextField(
        default=None, blank=True, null=True, choices=CardProperty.EXTRA_CONDITION
    )
    dpd_lower = models.IntegerField(blank=True, null=True, default=None)
    dpd_upper = models.IntegerField(blank=True, null=True, default=None)
    until_paid = models.BooleanField(blank=True, default=False)
    expiration_option = models.TextField(blank=True, null=True, default=None)
    expiry_period = models.IntegerField(blank=True, null=True, default=None)
    expiry_period_unit = models.TextField(blank=True, null=True, default=None)
    show_in_web = models.BooleanField(default=True)
    show_in_android = models.BooleanField(default=True)
    partner = models.ForeignKey(
        'julo.partner', models.DO_NOTHING, db_column='partner_id', blank=True, null=True)
    partner_selection_list = ArrayField(models.CharField(max_length=150), default=list)
    partner_selection_action = models.CharField(max_length=100, blank=True, null=True)
    bottom_sheet_destination = models.CharField(max_length=250, blank=True, null=True)
    payment_widget_properties = JSONField(blank=True, null=True, default=None)
    slik_notification_properties = JSONField(blank=True, null=True, default=None)
    julo_gold_status = models.CharField(max_length=50, blank=True, null=True)
    objects = StreamlinedCommunicationManager()

    class Meta(object):
        db_table = 'stream_lined_communication'


class StreamlinedCommunicationParameterList(TimeStampedModel):
    id = models.AutoField(db_column='parameter_list_id', primary_key=True)
    parameter_name = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    platform = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=CommunicationPlatform.CHOICES)
    example = models.TextField(blank=True, null=True)
    is_ptp = models.BooleanField(default=False)
    parameter_model_value = JSONField(default=None, blank=True, null=True)

    objects = StreamlinedCommunicationManager()

    class Meta(object):
        db_table = 'streamlined_communication_parameter_list'

    @property
    def replace_symbols(self):
        """
        replace symbols {,}
        """
        parameter_name = self.parameter_name.replace('{', '').replace('}', '')
        return parameter_name


class StreamlinedCommunicationFunctionList(TimeStampedModel):
    id = models.AutoField(db_column='function_list_id', primary_key=True)
    function_name = models.CharField(max_length=100, blank=True, null=True, unique=True)
    description = models.TextField(blank=True, null=True)
    communication_platform = models.CharField(max_length=50,
                                              choices=CommunicationPlatform.CHOICES)
    product = models.TextField(blank=True, null=True)
    objects = StreamlinedCommunicationManager()

    class Meta(object):
        db_table = 'streamlined_communication_function_list'


class StreamlinedVoiceMessage(TimeStampedModel):
    id = models.AutoField(db_column='streamlined_voice_message_id', primary_key=True)
    title = models.CharField(max_length=100, unique=True)
    audio_file = models.FileField(upload_to=voice_message_upload_path)
    objects = StreamlinedCommunicationManager()

    class Meta(object):
        db_table = 'streamlined_voice_message'

    def __str__(self):
        return self.title

    def audio_file_player(self):
        if self.audio_file:
            return '<audio src="{}" controls>Your browser does not support the audio element.</audio>'.format(
                settings.BASE_URL + "/" + settings.MEDIA_URL + str(self.audio_file)
            )

    def audio_file_url(self):
        if self.audio_file:
            return settings.BASE_URL + "/" + settings.MEDIA_URL + str(self.audio_file)

    audio_file_player.allow_tags = True
    audio_file_player.short_description = 'Audio file player'


class PnAction(TimeStampedModel):
    id = models.AutoField(db_column='pn_action_id', primary_key=True)
    streamlined_communication = models.ForeignKey(
        StreamlinedCommunication, models.DO_NOTHING, db_column='streamlined_communication_id')
    order = models.IntegerField()
    title = models.TextField()
    action = models.TextField()
    target = models.TextField()

    class Meta(object):
        db_table = 'pn_action'


class InfoCardButtonProperty(TimeStampedModel):
    id = models.AutoField(db_column='button_info_card_id', primary_key=True)
    info_card_property = models.ForeignKey(
        'InfoCardProperty',
        models.DO_NOTHING,
        db_column='info_card_property_id')
    # L / R / M Button
    button_name = models.TextField()
    text = models.TextField()
    text_color = models.CharField(max_length=10, null=True)
    button_color = models.CharField(max_length=10, blank=True, null=True)
    action_type = models.CharField(
        max_length=50, choices=CardProperty.CARD_ACTION_CHOICES, null=True)
    destination = models.TextField(null=True)

    class Meta(object):
        db_table = 'info_card_button_property'

    @property
    def background_image(self):
        # we will use Image object so if you want to add image
        # then create data into Image table
        return Image.objects.filter(
            image_source=self.id,
            image_type=CardProperty.IMAGE_TYPE.button_background_image).last()

    @property
    def background_image_url(self):
        # we will use Image object so if you want to add image
        # then create data into Image table
        image = Image.objects.filter(
            image_source=self.id,
            image_type=CardProperty.IMAGE_TYPE.button_background_image).last()
        if image:
            return image.public_image_url

        return None


class InfoCardProperty(TimeStampedModel):
    id = models.AutoField(db_column='info_card_property_id', primary_key=True)
    card_type = models.CharField(
        max_length=3, choices=CardProperty.CARD_TYPE_CHOICES)
    card_action = models.CharField(
        max_length=50, choices=CardProperty.CARD_ACTION_CHOICES, null=True)
    card_destination = models.TextField(null=True)
    card_order_number = models.IntegerField()
    title = models.TextField()
    title_color = models.CharField(max_length=10, null=True)
    text_color = models.CharField(max_length=10, null=True)
    youtube_video_id = models.CharField(max_length=100, null=True)

    # button_format will be like this

    class Meta(object):
        db_table = 'info_card_property'

    @property
    def card_background_image(self):
        # we will use Image object so if you want to add image
        # then create data into Image table
        return Image.objects.filter(
            image_source=self.id,
            image_type=CardProperty.IMAGE_TYPE.card_background_image).last()

    @property
    def card_background_image_url(self):
        # we will use Image object so if you want to add image
        # then create data into Image table
        image = Image.objects.filter(
            image_source=self.id,
            image_type=CardProperty.IMAGE_TYPE.card_background_image).last()
        if image:
            return image.public_image_url

        return None

    @property
    def card_optional_image_url(self):
        # we will use Image object so if you want to add image
        # then create data into Image table
        image = Image.objects.filter(
            image_source=self.id,
            image_type=CardProperty.IMAGE_TYPE.card_optional_image).last()
        if image:
            return image.public_image_url

        return None

    @property
    def button_list(self):
        return InfoCardButtonProperty.objects.filter(
            info_card_property_id=self.id
        ).order_by('button_name')


class InAppNotificationHistory(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='inapp_notification_id')
    customer_id = models.TextField()
    source = models.TextField(blank=True, null=True)
    template_code = models.TextField(blank=True, null=True)
    status = models.TextField(blank=True)

    class Meta(object):
        db_table = 'inapp_notification_history'


class PushNotificationPermission(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='push_notification_permission_id')
    customer = BigForeignKey(
        'julo.Customer', models.DO_NOTHING, db_column='customer_id')
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id',
        null=True
    )
    is_pn_permission = models.BooleanField(default=False)
    is_do_not_disturb = models.BooleanField(default=False)
    feature_name = models.CharField(max_length=255, blank=True, null=True)

    class Meta(object):
        db_table = 'push_notification_permission'


class Holiday(TimeStampedModel):
    id = models.AutoField(primary_key=True)
    holiday_date = models.DateField(unique=True)
    is_annual = models.BooleanField(default=False)
    is_religious_holiday = models.NullBooleanField(default=False, null=True, blank=True)

    class Meta(object):
        db_table = 'holiday'

    @classmethod
    def check_is_holiday_today(cls, date=None):
        """
        To check if the given date is a holiday.
        If no date is passed, it checks for today
        """
        date = date or timezone.localtime(timezone.now()).date()
        if date.strftime("%A") == 'Sunday':
            return True

        return cls.objects.filter(holiday_date=date).exists()

    @classmethod
    def check_is_religious_holiday(cls, date=None):
        """
        To check if the given date is a religious holiday.
        If no date is passed, it checks for today
        """
        date = date or timezone.now().date()
        return cls.objects.filter(holiday_date=date, is_religious_holiday=True).exists()


class SmsTspVendorConfig(TimeStampedModel):
    id = models.AutoField(primary_key=True)
    tsp = models.CharField(max_length=50, choices=SmsTspVendorConstants.CHOICES,
                           default=SmsTspVendorConstants.OTHERS)
    primary = models.CharField(
        max_length=50, blank=True, null=True,
        choices=SmsTspVendorConstants.NON_OTP_SMS_VENDOR_CHOICES)
    backup = models.CharField(
        max_length=50, blank=True, null=True,
        choices=SmsTspVendorConstants.NON_OTP_SMS_VENDOR_CHOICES)
    is_otp = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'sms_tsp_vendor_config'


class TelcoServiceProvider(TimeStampedModel):
    id = models.AutoField(primary_key=True)
    provider_name = models.CharField(max_length=100, blank=True, null=True)
    telco_code = ArrayField(models.CharField(max_length=50), default=list)

    class Meta(object):
        db_table = 'telco_service_provider'


class NeoBannerCard(TimeStampedModel):
    BADGE_COLOR_CHOICES = [
        ('yellow', 'Yellow'),
        ('red', 'Red'),
        ('green', 'Green'),
        ('blue', 'Blue'),
        ('grey', 'Grey'),
    ]

    id = models.AutoField(db_column='neo_banner_card_id', primary_key=True)
    product = models.TextField(blank=True, null=True)
    statuses = models.TextField(default='[]')
    template_card = models.TextField(blank=True, null=True)
    top_image = models.TextField(blank=True, null=True)
    top_title = models.TextField(blank=True, null=True)
    top_message = models.TextField(blank=True, null=True)
    badge_icon = models.TextField(blank=True, null=True)
    badge_color = models.TextField(
        choices=BADGE_COLOR_CHOICES,
        blank=True,
        null=True,
    )
    button_text = models.TextField(blank=True, null=True)
    button_action = models.TextField(blank=True, null=True)
    button_action_type = models.TextField(blank=True, null=True)
    extended_image = models.TextField(blank=True, null=True)
    extended_title = models.TextField(blank=True, null=True)
    extended_message = models.TextField(blank=True, null=True)
    extended_button_text = models.TextField(blank=True, null=True)
    extended_button_action = models.TextField(blank=True, null=True)
    top_info_icon = models.TextField(blank=True, null=True)
    top_info_title = models.TextField(blank=True, null=True)
    top_info_message = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'neo_banner_card'
        managed = False


class NeoInfoCard(TimeStampedModel):
    id = models.AutoField(db_column='neo_info_card_id', primary_key=True)
    product = models.TextField(blank=True, null=True)
    statuses = models.TextField(default='[]')
    image_url = models.TextField(blank=True, null=True)
    action_type = models.TextField(blank=True, null=True)
    action_destination = models.TextField(blank=True, null=True)
    priority = models.IntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'neo_info_card'
        managed = False


class StreamlinedCommunicationSegment(TimeStampedModel):
    id = models.AutoField(primary_key=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='uploaded_by', null=True
    )
    csv_file_url = models.CharField(max_length=200, null=True)
    csv_file_name = models.TextField(blank=True, null=True)
    csv_file_type = models.TextField(blank=True, null=True)
    segment_count = models.IntegerField(blank=True, null=True)
    segment_name = models.TextField(blank=True, null=True)
    chunk_count = models.IntegerField(blank=True, null=True)
    status = models.TextField(blank=True, null=True)
    error_list = JSONField(default=None, blank=True, null=True)

    class Meta(object):
        db_table = 'streamlined_communication_segment'


class CommsUserSegmentChunk(TimeStampedModel):

    STATUS_CHOICES = (
        (CommsUserSegmentConstants.ChunkStatus.START, 'Start'),
        (CommsUserSegmentConstants.ChunkStatus.ON_GOING, 'on_going'),
        (CommsUserSegmentConstants.ChunkStatus.FINISH, 'Finish'),
        (CommsUserSegmentConstants.ChunkStatus.FAILED, 'Failed'),
    )

    id = models.AutoField(primary_key=True, db_column='comms_user_segment_chunk_id')
    chunk_csv_file_url = models.CharField(max_length=200, null=True)
    chunk_csv_file_name = models.TextField(blank=True, null=True)
    chunk_number = models.IntegerField(blank=True, null=True)
    streamlined_communication_segment = models.ForeignKey(
        StreamlinedCommunicationSegment,
        models.DO_NOTHING,
        db_column='streamlined_communication_segment_id',
        null=True,
    )
    process_status = models.IntegerField(
        blank=True,
        null=True,
        choices=STATUS_CHOICES,
        default=CommsUserSegmentConstants.ChunkStatus.START,
    )
    process_id = models.IntegerField(blank=True, null=True)
    chunk_data_count = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'comms_user_segment_chunk'


class AppDeepLink(TimeStampedModel):
    id = models.AutoField(db_column='app_deep_link_id', primary_key=True)
    deeplink = models.CharField(max_length=200)
    label = models.CharField(max_length=200)

    class Meta(object):
        db_table = 'app_deep_link'

    def __str__(self):
        """Visual identification"""
        return self.label


class StreamlinedCampaignDepartment(TimeStampedModel):
    id = models.AutoField(db_column='streamlined_campaign_department_id', primary_key=True)
    name = models.TextField(blank=True, null=True)
    department_code = models.CharField(
        max_length=10,
        unique=True,
        null=True,
        help_text='Enter the department code (uppercase letters and numbers only).',
    )

    class Meta(object):
        db_table = 'streamlined_campaign_department'

    def clean(self):
        super().clean()

        if not self.department_code.isalnum() or not self.department_code.isupper():
            raise ValidationError(
                {
                    'department_code': 'Department code can only contain uppercase letters and numbers.'
                },
                code='invalid_department_code',
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        """Visual identification"""
        return self.name


class StreamlinedCampaignSquad(TimeStampedModel):
    id = models.AutoField(db_column='streamlined_campaign_squad_id', primary_key=True)
    name = models.TextField(unique=True)

    class Meta(object):
        db_table = 'streamlined_campaign_squad'

    def __str__(self):
        """Visual identification"""
        return self.name


class StreamlinedCommunicationCampaign(TimeStampedModel):
    id = models.AutoField(db_column='streamlined_communication_campaign_id', primary_key=True)
    created_by = CurrentUserField()
    name = models.TextField()
    department = models.ForeignKey(
        StreamlinedCampaignDepartment, models.DO_NOTHING, db_column='campaign_department_id'
    )
    campaign_type = models.TextField(default=StreamlinedCommCampaignConstants.CampaignType.SMS)
    user_segment = models.ForeignKey(
        StreamlinedCommunicationSegment, models.DO_NOTHING, db_column='segment_id'
    )
    status = models.TextField(blank=True, null=True)
    content = models.ForeignKey(
        StreamlinedMessage, models.DO_NOTHING, db_column='message_id', null=True
    )
    schedule_mode = models.CharField(max_length=160, null=True, blank=True)
    squad = models.ForeignKey(
        StreamlinedCampaignSquad, models.DO_NOTHING, db_column='squad_id', null=True
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        blank=True,
        null=True,
        db_column='confirmed_by_id',
        related_name='%(class)s_confirmed_by',
    )

    class Meta(object):
        db_table = 'streamlined_communication_campaign'

    def __str__(self):
        """Visual identification"""
        return self.name


class CampaignSmsHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class CommsCampaignSmsHistory(TimeStampedModel):
    id = models.AutoField(db_column='comms_campaign_sms_history_id', primary_key=True)

    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', blank=True, null=True
    )
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', blank=True, null=True
    )
    status = models.CharField(max_length=30, default='sent_to_provider')
    delivery_error_code = models.IntegerField(blank=True, null=True)
    message_id = models.CharField(max_length=50, blank=True, null=True)
    message_content = models.TextField(blank=True, null=True)
    template_code = models.CharField(max_length=50, null=True, blank=True)
    to_mobile_phone = PhoneNumberField()
    phone_number_type = models.CharField(max_length=50, null=True, blank=True)
    comms_provider = models.ForeignKey(
        CommsProviderLookup, models.DO_NOTHING, blank=True, null=True, db_column='comms_provider_id'
    )
    tsp = models.TextField(blank=True, null=True)
    account = models.ForeignKey(
        Account, models.DO_NOTHING, db_column='account_id', blank=True, null=True
    )
    campaign = models.ForeignKey(
        StreamlinedCommunicationCampaign,
        models.DO_NOTHING,
        db_column='campaign_id',
        blank=True,
        null=True,
    )
    objects = CampaignSmsHistoryManager()

    class Meta(object):
        db_table = 'comms_campaign_sms_history'



class SmsVendorRequest(TimeStampedModel):
    id = BigAutoField(db_column='sms_vendor_request_id', primary_key=True)
    vendor_identifier = models.TextField()
    phone_number = models.TextField(blank=True, null=True)
    payload = JSONField()
    comms_provider_lookup_id = models.TextField(blank=False, null=False)

    @property
    def comms_provider_lookup(self):
        from juloserver.julo.models import CommsProviderLookup

        try:
            return CommsProviderLookup.objects.get(id=self.comms_provider_lookup_id)
        except CommsProviderLookup.DoesNotExist:
            return None

    def save(self, *args, **kwargs):
        from juloserver.julo.models import CommsProviderLookup

        # As CommsProviderLookup.id is a predetermined string value, there is a consideration to
        # use const instead of DB access.
        if not CommsProviderLookup.objects.filter(id=self.comms_provider_lookup_id).exists():
            raise ValidationError(
                f"Related CommsProviderLookup with ID {self.comms_provider_lookup_id} does not exist."
            )
        super(SmsVendorRequest, self).save(*args, **kwargs)

    class Meta(object):
        db_table = 'sms_vendor_request'
        managed = False

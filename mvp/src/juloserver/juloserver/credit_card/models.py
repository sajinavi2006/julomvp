from django.db import models
from cuser.fields import CurrentUserField
from django.contrib.postgres.fields import ArrayField

from juloserver.julocore.data.models import (
    TimeStampedModel,
    GetInstanceMixin,
    JuloModelManager,
)
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from ckeditor.fields import RichTextField

from juloserver.account.models import (
    Address,
    Account
)

from juloserver.julo.models import (
    Image,
    StatusLookup,
    Loan,
    Application,
)


class CreditCardApplicationManager(GetInstanceMixin, JuloModelManager):
    pass


class CreditCardApplication(TimeStampedModel):
    id = models.AutoField(db_column='credit_card_application_id', primary_key=True)
    virtual_card_name = models.TextField(blank=True, null=True)
    virtual_account_number = models.TextField(blank=True, null=True, db_index=True)
    status = models.ForeignKey(StatusLookup, models.DO_NOTHING, db_column='status_code')
    shipping_number = models.TextField(blank=True, null=True)
    address = models.OneToOneField(Address, models.DO_NOTHING, db_column='address_id')
    account = models.ForeignKey(Account, models.DO_NOTHING, db_column='account_id')
    image = models.OneToOneField(Image, models.DO_NOTHING, db_column='image_id')
    expedition_company = models.TextField(blank=True, null=True)

    objects = CreditCardApplicationManager()

    class Meta(object):
        db_table = 'credit_card_application'

    def __str__(self):
        return "{} - {}".format(self.id, self.virtual_card_name)


class CreditCardStatus(TimeStampedModel):
    id = models.AutoField(db_column='credit_card_status_id', primary_key=True)
    description = models.TextField(db_index=True)

    class Meta(object):
        db_table = 'credit_card_status'

    def __str__(self):
        return "{} - {}".format(self.id, self.description)


class CreditCard(TimeStampedModel):
    id = models.AutoField(db_column='credit_card_id', primary_key=True)
    card_number = models.TextField(unique=True, db_index=True)
    credit_card_status = models.ForeignKey(CreditCardStatus, models.DO_NOTHING,
                                           db_column='credit_card_status_id')
    expired_date = models.TextField()
    credit_card_application = models.ForeignKey(CreditCardApplication, models.DO_NOTHING,
                                                blank=True, null=True,
                                                db_column='credit_card_application_id')

    class Meta(object):
        db_table = 'credit_card'

    def __str__(self):
        return "{} - {}".format(self.id, self.card_number)


class CreditCardApplicationHistory(TimeStampedModel):
    id = models.AutoField(db_column='credit_card_application_history_id', primary_key=True)
    status_old = models.ForeignKey(
        StatusLookup,
        models.DO_NOTHING,
        db_column='status_old',
        null=True,
        blank=True,
        related_name='credit_card_application_status_history_old'
    )
    status_new = models.ForeignKey(
        StatusLookup,
        models.DO_NOTHING,
        db_column='status_new',
        related_name='credit_card_application_status_history_new'
    )
    changed_by = CurrentUserField()
    change_reason = models.TextField()
    credit_card_application = models.ForeignKey(CreditCardApplication, models.DO_NOTHING,
                                                blank=True, null=True,
                                                db_column='credit_card_application_id')
    block_reason = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'credit_card_application_history'

    def __str__(self):
        return str(self.id)


class CreditCardTransaction(TimeStampedModel):
    id = models.AutoField(db_column='credit_card_transaction_id', primary_key=True)
    amount = models.BigIntegerField()
    fee = models.BigIntegerField()
    transaction_date = models.DateTimeField(blank=True, null=True)
    reference_number = models.TextField()
    bank_reference = models.TextField()
    terminal_type = models.TextField()
    terminal_id = models.TextField()
    terminal_location = models.TextField()
    merchant_id = models.TextField()
    acquire_bank_code = models.TextField()
    destination_bank_code = models.TextField(blank=True, null=True)
    destination_account_number = models.TextField(blank=True, null=True)
    destination_account_name = models.TextField(blank=True, null=True)
    biller_code = models.TextField(blank=True, null=True)
    biller_name = models.TextField(blank=True, null=True)
    customer_id = models.TextField(blank=True, null=True)
    hash_code = models.TextField(blank=True, null=True)
    transaction_status = models.TextField(blank=True, null=True)
    transaction_type = models.TextField(blank=True, null=True)
    credit_card_application = models.ForeignKey(CreditCardApplication, models.DO_NOTHING,
                                                db_column='credit_card_application_id',
                                                blank=True, null=True)
    loan = BigForeignKey(Loan, models.DO_NOTHING,
                         db_column='loan_id', blank=True, null=True)
    tenor_options = ArrayField(models.IntegerField(), blank=True, null=True)

    class Meta(object):
        db_table = 'credit_card_transaction'

    def __str__(self):
        return str(self.id)


class CreditCardMobileContentSetting(TimeStampedModel):
    id = models.AutoField(db_column='credit_card_mobile_content_setting_id', primary_key=True)

    content_name = models.CharField(max_length=100)
    description = models.CharField(max_length=200)
    content = RichTextField(blank=True, null=True)
    is_active = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'credit_card_mobile_content_setting'


class CreditCardApplicationNote(TimeStampedModel):
    id = models.AutoField(db_column='credit_card_application_note_id', primary_key=True)
    note_text = models.TextField()
    added_by = CurrentUserField()
    credit_card_application = models.ForeignKey(CreditCardApplication, models.DO_NOTHING,
                                                blank=True, null=True,
                                                db_column='credit_card_application_id')
    credit_card_application_history = models.ForeignKey(CreditCardApplicationHistory,
                                                        models.DO_NOTHING,
                                                        blank=True, null=True,
                                                        db_column='credit_card_'
                                                                  'application_history_id')

    class Meta(object):
        db_table = 'credit_card_application_note'

    def __str__(self):
        return str(self.id)


class JuloCardWhitelistUser(TimeStampedModel):
    id = models.AutoField(db_column='julo_card_whitelist_user_id', primary_key=True)
    application = BigForeignKey(Application, models.DO_NOTHING, db_column='application_id',
                                db_index=True, unique=True)

    class Meta(object):
        db_table = 'julo_card_whitelist_user'


class JuloCardBanner(TimeStampedModel):
    BANNER_TYPE = (
        ('DEEP_LINK', 'DEEP_LINK'),
        ('WEB_VIEW', 'WEB_VIEW'))

    id = models.AutoField(db_column='julo_card_banner_id', primary_key=True)
    name = models.CharField(max_length=100)
    click_action = models.TextField(blank=True, null=True)
    banner_type = models.CharField(max_length=100, choices=BANNER_TYPE)
    image = models.OneToOneField(Image, models.DO_NOTHING, db_column='image_id',
                                 blank=True, null=True)
    is_active = models.BooleanField(default=False)
    display_order = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'julo_card_banner'

    def __str__(self):
        return str(self.id)

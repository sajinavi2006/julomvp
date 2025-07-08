import logging
from copy import deepcopy

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Customer, CustomerFieldChange
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.pii_vault.services import detokenize_for_model_object, detokenize_value_lookup
from juloserver.pii_vault.constants import PiiSource, PIIType

sentry = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class ClaimError(Exception):
    pass


class ClaimerService:
    """
    Handle claiming customer because they are using different apk version when register.
    Possibility to have more than one customers record for one person must be handled
    appropriately.
    """

    _on_module = None

    ALLOWED_106_PREVIOUS = [
        ApplicationStatusCodes.NOT_YET_CREATED,
        ApplicationStatusCodes.FORM_CREATED,
    ]

    def __init__(self, customer: Customer):
        """
        Fill the constructor with new customer instance. In most cases current logged in customer.
        """

        self.customer = customer
        self.claimed_customers = None

    def claim_using(self, phone: str = None, nik: str = None, email: str = None):
        """
        Claim customer using desired attribute.

        Commonly using following combination:
            (ClaimerService(customer)).claim_using(phone=*****)
            (ClaimerService(customer)).claim_using(nik=*****)
            (ClaimerService(customer)).claim_using(email=*****)
            (ClaimerService(customer)).claim_using(nik=*****, email=*****)
        """

        if phone:
            self.claim_using_phone(phone)
        if nik or email:
            self.claim_using_nik_or_email(nik, email)

        return self

    def claim_using_phone(self, phone: str, is_login=False):
        """
        When customer register using new apk, which is only fill the phone number in customer table,
        then she register again using old apk, which is fill nik and email; then look at another
        customers that has same phone number. If all claimed customers candidate allow to be
        claimed then set false the claimed customers (phone number is not unique so it is not moved)
        """

        from django.db import transaction

        detokenize_value_lookup(phone, PIIType.CUSTOMER)
        self.claimed_customers = Customer.objects.filter(phone=phone, is_active=True).exclude(
            id=self.customer.id
        )

        if not is_login:
            self._validate_phone(phone)
            self._validate_application_status()

        with transaction.atomic():
            for claimed_customer in self.claimed_customers:

                detokenized_customers = detokenize_for_model_object(
                    PiiSource.CUSTOMER,
                    [
                        {
                            'customer_xid': claimed_customer.customer_xid,
                            'object': claimed_customer,
                        }
                    ],
                    force_get_local_data=True,
                )

                claimed_customer = detokenized_customers[0]

                _claimed_dirty = deepcopy(claimed_customer)
                claimed_customer.is_active = False
                claimed_customer.save()

                self._audit_log_customer(
                    old_model=_claimed_dirty,
                    new_model=claimed_customer,
                    fields=['is_active'],
                )

            origin = 'claim_using_phone'
            if not self._on_module:
                origin = '{}:{}'.format(origin, self._on_module)

            self._record_claim_log(origin=origin)
            self._change_username()

    def _change_username(self):
        # from django.contrib.auth.models import User
        from juloserver.julo.models import AuthUser as User
        from django.db.models import F, Value
        from django.db.models.functions import Concat

        user_ids = self.claimed_customers.values_list('user_id', flat=True)
        User.objects.filter(id__in=user_ids).update(
            is_active=False, username=Concat(Value("inactive"), F('username'))
        )

    def claim_using_nik_or_email(self, nik: str = None, email: str = None):
        """Claim customer using nik/ktp or email."""
        self._validate_nik_email(email, nik)
        if not nik and not email:
            __message = 'One or both between NIK and email must be filled.'
            logger.warning(
                {
                    'message': __message,
                    'customer_id': self.customer.id,
                }
            )
            raise ValueError(__message)

        _claimed_customers = Customer.objects.prefetch_related(
            'application_set__applicationhistory_set'
        ).exclude(id=self.customer.id)

        origin = None
        if nik and not email:
            self.claimed_customers = _claimed_customers.filter(nik=nik)
            origin = 'claim_using_nik'
        elif not nik and email:
            self.claimed_customers = _claimed_customers.filter(email=email)
            origin = 'claim_using_email'
        elif nik and email:
            from django.db.models import Q

            self.claimed_customers = _claimed_customers.filter(Q(nik=nik) | Q(email=email))
            origin = 'claim_using_nik_or_email'

        self._validate_application_status()

        # If existing customer that has same nik or email not exists
        # then make sure current customer is active.
        if not self.claimed_customers.exists():
            _customer_dirty = deepcopy(self.customer)
            self.customer.is_active = True
            self.customer.save()

            if _customer_dirty.is_active == self.customer.is_active:
                return self

            CustomerFieldChange.objects.create(
                customer=self.customer,
                field_name='is_active',
                old_value=_customer_dirty.is_active,
                new_value=self.customer.is_active,
            )
            return self

        # If customer exists and has no phone number, which mean he/she should be has no
        # application goes to 105, transfer the nik and email from existing customer into current
        # application customer. We must carefully move the nik and email because both has unique
        # constraint.
        from django.db import transaction

        with transaction.atomic():
            for claimed_customer in self.claimed_customers:

                # detokenize
                detokenized_customers = detokenize_for_model_object(
                    PiiSource.CUSTOMER,
                    [
                        {
                            'customer_xid': claimed_customer.customer_xid,
                            'object': claimed_customer,
                        }
                    ],
                    force_get_local_data=True,
                )

                claimed_customer = detokenized_customers[0]

                _claimed_dirty = deepcopy(claimed_customer)

                claimed_customer.nik = None
                claimed_customer.email = None
                claimed_customer.is_active = False
                claimed_customer.save()

                self._audit_log_customer(
                    old_model=_claimed_dirty,
                    new_model=claimed_customer,
                    fields=['nik', 'email', 'is_active'],
                )

            # Update the customer attribute
            _customer_dirty = deepcopy(self.customer)
            self.customer.nik = nik
            self.customer.email = email
            self.customer.is_active = True
            self.customer.save()
            self._audit_log_customer(
                old_model=_customer_dirty,
                new_model=self.customer,
                fields=['nik', 'email', 'is_active'],
            )

            # After transferring the nik and email, insert into claim history.
            if not self._on_module:
                origin = '{}:{}'.format(origin, self._on_module)
            self._record_claim_log(origin=origin)

            # Change the username of claimed customer to inactive
            self._change_username()

        return self

    @staticmethod
    def _audit_log_customer(old_model, new_model, fields):
        for field in fields:
            if getattr(old_model, field) == getattr(new_model, field):
                continue
            CustomerFieldChange.objects.create(
                customer=new_model,
                field_name=field,
                old_value=getattr(old_model, field),
                new_value=getattr(new_model, field),
            )

    def claim_using_nik(self, nik: str):
        """Alias for claim using nik"""
        return self.claim_using_nik_or_email(nik=nik)

    def claim_using_email(self, email: str):
        """Alias for claim using email"""
        return self.claim_using_nik_or_email(email=email)

    @sentry.capture_exceptions((ValueError))
    def _validate_nik_email(self, email, nik):
        """
        Check to the customer table if has existing nik and email with current application
        information, and make sure that existing customer is different from current application
        customer. ClaimError should be handled appropriately so not exposed in response.
        """
        if nik and self.customer.nik:
            __message = 'Current customer already has NIK, cannot replace it.'
            logger.warning(
                {
                    'message': __message,
                    'customer_id': self.customer.id,
                    'nik': nik,
                }
            )
            raise ClaimError(__message)

        if email and self.customer.email:
            __message = 'Current customer already has email, cannot replace it.'
            logger.warning(
                {
                    'message': __message,
                    'customer_id': self.customer.id,
                    'email': email,
                }
            )
            raise ClaimError(__message)

    def _validate_application_status(self):
        """
        Before process happening, check that customer has application that has no restriction.
        To make sure that single customer person only has one appropriate application.
        """
        for claimed_customer in self.claimed_customers:

            applications = claimed_customer.application_set.all()
            total_application = applications.count()
            if total_application == 0:
                continue
            elif total_application > 1:
                self._reapply_claim(claimed_customer)

            # Until here we get the candidate claimed customer only has 1 application.
            application = applications.last()
            self._check_application_status_in_x100_x106(application)

    def _reapply_claim(self, claimed_customer):
        """
        One of candidate claimed customer has application x100 or x106 more than one
        in old apk. Then she download short form apk, the previous customer should be claimed in
        new apk.
        """
        applications = claimed_customer.application_set.all()
        for application in applications:
            self._check_application_status_in_x100_x106(application)

    def _check_application_status_in_x100_x106(self, application):
        if application.status not in [
            ApplicationStatusCodes.FORM_CREATED,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ]:
            __message = (
                'One of candidate claimed customer comes from restricted '
                'application status code ' + str(application.status) + '.'
            )
            logger.warning(
                {
                    'message': __message,
                    'customer_id': self.customer.id,
                    'claimed_customer_id': application.customer.id,
                    'claimed_customer_application_id': application.id,
                }
            )
            raise ClaimError(__message)

        # If status 106, check the previous status. Only allow from 0 or 100.
        # Should automatically reject from [121, 120, 106, 105]
        elif application.status == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
            previous_statuses = application.applicationhistory_set.filter(
                status_new=106
            ).values_list('status_old', flat=True)
            diff = set(previous_statuses) - set(self.ALLOWED_106_PREVIOUS)
            if len(diff) > 0:
                __message = (
                    'One of candidate claimed customer comes from restricted '
                    'application status code ' + str(application.status) + '.'
                )
                logger.warning(
                    {
                        'message': __message,
                        'customer_id': self.customer.id,
                        'claimed_customer_id': application.customer.id,
                        'claimed_customer_application_id': application.id,
                    }
                )
                raise ClaimError(__message)

    def _record_claim_log(self, claimed_customers=None, origin=None):
        """Store claim process, who the claimer and who has been claimed."""
        from django.db.models import QuerySet

        from juloserver.application_form.models import CustomerClaim

        if claimed_customers is None:
            claimed_customers = self.claimed_customers
        if isinstance(claimed_customers, QuerySet):
            data = []
            for claimed_customer in claimed_customers:
                data.append(
                    CustomerClaim(
                        customer=self.customer, claimed_customer=claimed_customer, origin=origin
                    )
                )
            CustomerClaim.objects.bulk_create(data)
        else:
            CustomerClaim.objects.create(
                customer=self.customer, claimed_customer=claimed_customers, origin=origin
            )

    def _validate_phone(self, phone):
        if phone and self.customer.phone:
            __message = 'Current customer already has phone, cannot replace it.'
            logger.warning(
                {
                    'message': __message,
                    'customer_id': self.customer.id,
                    'nik': phone,
                }
            )
            raise ClaimError(__message)

    def on_module(self, module):
        self._on_module = module
        return self

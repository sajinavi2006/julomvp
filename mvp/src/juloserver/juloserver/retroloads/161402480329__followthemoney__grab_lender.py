# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-02-22 20:13
from __future__ import unicode_literals
from builtins import range
import random
import string

from django.db import migrations
from django.contrib.auth.models import User
from juloserver.followthemoney.models import (
    LenderCurrent,
    LenderBalanceCurrent,
    LenderBankAccount,
)
from juloserver.julo.models import (
    ProductProfile,
    LenderDisburseCounter,
    LenderCustomerCriteria,
    LenderProductCriteria,
    Partner,
)
from juloserver.julo.constants import ProductLineCodes


def create_grab_lender(apps, schema_editor):
    jtp = LenderCurrent.objects.filter(lender_name="jtp", lender_status="active").last()
    if not jtp:
        return
    jtp_partner = jtp.user.partner

    user = User.objects.filter(username='gfin').first()
    if not user:
        alphabet = string.ascii_letters + string.digits
        password = ''.join(random.choice(alphabet) for i in range(8))
        user = User.objects.create_user("gfin", "amrita.vir@grab.com", password)

    partner = Partner.objects.get_or_none(user=user)
    if not partner:
        partner = Partner.objects.create(
            user=user,
            name="gfin",
            type="lender",
            email=user.email,
            is_active=False,
            poc_name="Amrita Vir",
            poc_email=user.email,
            poc_phone="+6586021681",
            source_of_fund="lainnya",
            company_name="Grab Financial",
            company_address="Singapore",
            business_type="perusahaan_umum",
            agreement_letter_number=jtp_partner.agreement_letter_number,
        )
        lender = LenderCurrent.objects.create(
            user=user,
            lender_name="gfin",
            lender_address="Singapore",
            business_type="perusahaan_umum",
            poc_email=user.email,
            poc_name="Amrita Vir",
            poc_phone="+6586021681",
            poc_position="DAX Segment",
            source_of_fund="lainnya",
            lender_display_name='Grab Financial',
            service_fee=0,
            lender_status="inactive",
            addendum_number=jtp.addendum_number,
            insurance=jtp.insurance,
            pks_number=jtp.pks_number,
            xfers_token=jtp.xfers_token,
        )
        LenderDisburseCounter.objects.create(lender=lender,partner=partner)
        LenderBalanceCurrent.objects.create(lender=lender)
        LenderCustomerCriteria.objects.create(lender=lender, partner=partner)
        product_profiles = ProductProfile.objects.filter(
            code=ProductLineCodes.GRAB1).values_list('id', flat=True)
        LenderProductCriteria.objects.create(
            lender=lender,
            partner=partner,
            type='Product List',
            product_profile_list=list(product_profiles),
        )

        jtp_bank_accounts = jtp.lenderbankaccount_set.filter(bank_account_status="active")
        banks = []
        for bank_account in jtp_bank_accounts:
            bank_account.pk = None
            bank_account.lender = lender
            bank_account.name_bank_validation = None
            banks.append(bank_account)
        LenderBankAccount.objects.bulk_create(banks)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_grab_lender, migrations.RunPython.noop),
    ]

from bulk_update.helper import bulk_update
from django.utils import timezone

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.models import Partner, Application
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.partnership.models import PartnershipCustomerData
from juloserver.partnership.utils import generate_pii_filter_query_partnership


def retroload_old_customer_id_axiata_bau(optional_nik: list = None):
    pii_partner_filter_dict = generate_pii_filter_query_partnership(
        Partner, {'name': PartnerNameConstant.AXIATA_WEB}
    )
    partner = Partner.objects.filter(is_active=True, **pii_partner_filter_dict).last()
    list_nik_null_customer_id_old_query = PartnershipCustomerData.objects.filter(
        customer_id_old__isnull=True, partner=partner
    )
    if optional_nik:
        list_nik_null_customer_id_old_query = list_nik_null_customer_id_old_query.filter(
            nik__in=optional_nik
        )

    list_nik_null_customer_id_old = list(
        list_nik_null_customer_id_old_query.values_list('nik', flat=True)
    )

    pii_partner_filter_dict = generate_pii_filter_query_partnership(
        Partner, {'name': PartnerConstant.AXIATA_PARTNER}
    )
    partner_old_axiata = Partner.objects.filter(**pii_partner_filter_dict).last()

    existed_customers = (
        Application.objects.filter(
            ktp__in=list_nik_null_customer_id_old,
            partner=partner_old_axiata,
            application_status_id=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        )
        .distinct('customer_id')
        .values('customer_id', 'ktp')
    )
    mapped_customer_id_old = {}
    for existed_customer in existed_customers:
        mapped_customer_id_old[existed_customer['ktp']] = existed_customer['customer_id']

    update_partnership_customer_data = []
    for item in list_nik_null_customer_id_old_query.iterator():
        if mapped_customer_id_old.get(item.nik, None):
            item.customer_id_old = mapped_customer_id_old[item.nik]
            item.udate = timezone.localtime(timezone.now())
            update_partnership_customer_data.append(item)

    if len(update_partnership_customer_data) > 0:
        bulk_update(
            update_partnership_customer_data,
            update_fields=['customer_id_old', 'udate'],
            batch_size=100,
        )

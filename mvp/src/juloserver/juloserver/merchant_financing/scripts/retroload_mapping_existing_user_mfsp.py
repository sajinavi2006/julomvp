from bulk_update.helper import bulk_update
from django.utils import timezone

from juloserver.julo.models import Partner, Customer, Application
from juloserver.partnership.models import PartnershipCustomerData
from juloserver.partnership.utils import generate_pii_filter_query_partnership
from juloserver.portal.object.bulk_upload.constants import MerchantFinancingCSVUploadPartner

MF_STANDARD_PRODUCT_PARTNERS = {
    MerchantFinancingCSVUploadPartner.GAJIGESA,
    MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_REGULER,
    MerchantFinancingCSVUploadPartner.EFISHERY_JAWARA,
    MerchantFinancingCSVUploadPartner.EFISHERY_INTI_PLASMA,
    MerchantFinancingCSVUploadPartner.AGRARI,
    MerchantFinancingCSVUploadPartner.KARGO,
    MerchantFinancingCSVUploadPartner.RABANDO,
    MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE,
    MerchantFinancingCSVUploadPartner.FISHLOG,
    MerchantFinancingCSVUploadPartner.DAGANGAN,
    MerchantFinancingCSVUploadPartner.EFISHERY,
}


def retroload_mapping_existing_user_mfsp(partner_name: str) -> None:
    """Mapping existing MFSP users to old customer id from MF"""

    if partner_name not in MF_STANDARD_PRODUCT_PARTNERS:
        print('Not merchant financing partner')
        return

    pii_partner_filter_dict = generate_pii_filter_query_partnership(Partner, {'name': partner_name})
    partner = Partner.objects.filter(is_active=True, **pii_partner_filter_dict).values('id').last()
    if not partner:
        print('Partner not found')
        return

    partner_id = partner.get('id')
    exists_partnership_customer_data = PartnershipCustomerData.objects.filter(
        customer_id_old__isnull=True, partner_id=partner_id
    )

    print(
        "Found {} exists partnership customer data with customer_id_old is null".format(
            len(exists_partnership_customer_data)
        )
    )

    nik_list = []
    if exists_partnership_customer_data:
        nik_list = exists_partnership_customer_data.values_list('nik', flat=True)

    # Get old customer id
    old_customers = (
        Application.objects.filter(
            ktp__in=nik_list,
            partner_id=partner_id,
        )
        .distinct('customer_id')
        .values('customer_id', 'ktp')
    )

    mapped_customer_id_old = {}
    for customer in old_customers:
        mapped_customer_id_old[customer['ktp']] = customer['customer_id']

    update_partnership_customer_data = []
    for item in exists_partnership_customer_data.iterator():
        if mapped_customer_id_old.get(item.nik, None):
            item.customer_id_old = mapped_customer_id_old[item.nik]
            item.udate = timezone.localtime(timezone.now())
            update_partnership_customer_data.append(item)

    print("Mapping {} old customer id".format(len(update_partnership_customer_data)))

    if len(update_partnership_customer_data) > 0:
        bulk_update(
            update_partnership_customer_data,
            update_fields=['customer_id_old', 'udate'],
            batch_size=100,
        )

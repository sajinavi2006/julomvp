from django.conf import settings
from juloserver.digisign.services.digisign_document_services import get_digisign_document_success
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.loan.services.views_v3_related import LoanAgreementDetailsV3Service


class LoanAgreementDetailsV4Service(LoanAgreementDetailsV3Service):
    """
    Service for /api/loan/v4/agreement/loan/{{loan_xid}}
    """

    @property
    def loan_agreement(self):
        success_digisign = get_digisign_document_success(self.loan.id)

        default_img = '{}{}'.format(
            settings.STATIC_ALICLOUD_BUCKET_URL,
            'loan_agreement/default_document_logo.png'
        )

        types = [{
            "type": LoanAgreementType.TYPE_RIPLAY,
            "displayed_title": LoanAgreementType.TYPE_RIPLAY.upper(),
            "text": LoanAgreementType.TEXT_RIPLAY,
            "image": default_img,
        }]

        main_title = "Lihat Dokumen SKRTP dan RIPLAY"
        if success_digisign:
            types.append({
                "type": LoanAgreementType.TYPE_DIGISIGN_SKRTP,
                "displayed_title": LoanAgreementType.TYPE_SKRTP.upper(),
                "text": LoanAgreementType.TEXT_SKRTP,
                "image": default_img,
            })
        else:
            types.append({
                "type": LoanAgreementType.TYPE_SKRTP,
                "displayed_title": LoanAgreementType.TYPE_SKRTP.upper(),
                "text": LoanAgreementType.TEXT_SKRTP,
                "image": default_img,
            })

        return {
            "title": main_title,
            "types": types,
        }

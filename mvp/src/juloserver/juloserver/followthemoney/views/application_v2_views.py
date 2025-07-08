from __future__ import division
import pdfkit
import logging
from django.conf import settings
from django.http import StreamingHttpResponse
from django.http.response import HttpResponse
from datetime import datetime
from xhtml2pdf import pisa

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND
)
from juloserver.dana.tasks import get_dana_loan_agreement_template

from juloserver.grab.constants import GRAB_ACCOUNT_LOOKUP_NAME
from juloserver.julo.utils import get_file_from_oss
from juloserver.followthemoney.tasks import (
    generate_summary_lender_loan_agreement,
)

from juloserver.julo.models import (
    Loan,
    Application,
    Document,
)
from juloserver.followthemoney.models import (
    LenderBucket,
    LenderCurrent,
)
from juloserver.followthemoney.tasks import (
    get_summary_loan_agreement_template,
)
from juloserver.followthemoney.serializers import LenderAgreementSerializer

from juloserver.followthemoney.services import get_skrtp_or_sphp_pdf
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.services.agreement_related import get_loan_agreement_template_julo_one
from juloserver.partnership.services.services import get_mf_std_loan_agreement_template

logger = logging.getLogger(__name__)


class LenderPreviewAgreement(APIView):
    def get(self, request):
        lender = LenderCurrent.objects.get_or_none(user=request.user)
        if not lender:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"success": False, "content": {}, "error_message": "User is not a Lender"},
            )

        list_params = request.query_params.getlist('approved_loan_ids[]')
        data = {
            'approved_loan_ids': list_params
        }
        serializer = LenderAgreementSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        approved_loan_ids = data["approved_loan_ids"]

        approved_loans = Loan.objects.filter(id__in=approved_loan_ids, lender=lender)
        if len(approved_loan_ids) != len(approved_loans):
            # Loan not found or belong to another lender
            loan_ids = [approved_loan.id for approved_loan in approved_loans]
            loan_not_founds = set(approved_loan_ids) - set(loan_ids)
            error_msg = "Loan {} not found or belong to another lender".format(loan_not_founds)
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"success": False, "content": {}, "error_message": error_msg},
            )

        body = get_summary_loan_agreement_template(None, lender, False, approved_loan_ids)
        response = HttpResponse(body, content_type='application/json')
        return response


class LenderSphp(APIView):
    def get(self, request, application_xid):
        application = Application.objects.get_or_none(application_xid=application_xid)
        if not application:
            loan = Loan.objects.get_or_none(loan_xid=application_xid)
            filter_lender_bucket = dict(loan_ids__approved__contains=[loan.id])
            customer = loan.customer
        else:
            loan = Loan.objects.get_or_none(application_id=application.id)
            filter_lender_bucket = dict(application_ids__approved__contains=[application.id])
            customer = application.customer

        if loan and loan.loan_status_id == LoanStatusCodes.LENDER_REJECT:
            return Response(
                status=HTTP_404_NOT_FOUND,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "P3BTI not exist since loan is rejected"
                },
            )

        lender_bucket = LenderBucket.objects.filter(**filter_lender_bucket).last()
        if not lender_bucket:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"success": False, "content": {}, "error_message": "lenderbucket Not Found"},
            )

        document = Document.objects.filter(
            document_source=lender_bucket.id, document_type="summary_lender_sphp"
        ).last()

        if not document:
            generate_summary_lender_loan_agreement(lender_bucket.id)
            document = Document.objects.filter(
                document_source=lender_bucket.id, document_type="summary_lender_sphp"
            ).last()
            if not document:
                lender = loan.lender
                template = get_summary_loan_agreement_template(lender_bucket, lender, True)
                if not template:
                    return Response(
                        status=HTTP_400_BAD_REQUEST,
                        data={
                            "success": False,
                            "content": {},
                            "error_message": "Template P3BTI tidak ditemukan",
                        },
                    )

                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={"success": False, "content": {}, "error_message": "P3BTI tidak ditemukan"},
                )

        document_stream = get_file_from_oss(settings.OSS_MEDIA_BUCKET, document.url)
        response = StreamingHttpResponse(
            streaming_content=document_stream, content_type='application/pdf'
        )
        response['Content-Disposition'] = 'filename="' + document.filename + '"'
        return response


class CustomerSphp(APIView):
    def get(self, request, application_xid):
        application = Application.objects.get_or_none(application_xid=application_xid)

        if not application:
            loan = Loan.objects.get_or_none(loan_xid=application_xid)
        else:
            loan = Loan.objects.get_or_none(application_id=application.id)

        if not loan:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Loan Not Found",
                },
            )

        if (
            loan.loan_status_id == LoanStatusCodes.LENDER_REJECT
            or loan.loan_status_id < LoanStatusCodes.FUND_DISBURSAL_ONGOING
        ):
            # generate on the fly if rejected or haven't disbursed
            if not application:
                application = loan.get_application

            template, _ = get_loan_agreement_template_julo_one(
                loan.id, is_simulation=True
            )
            if not template:
                logger.error({
                    'action_view': 'generate_sphp_or_skrtp',
                    'data': {'loan_id': loan.id},
                    'errors': "Template tidak ditemukan."
                })
                return

            try:
                pdf = pdfkit.from_string(template, False)
            except Exception as e:
                logger.error(
                    {
                        'action_view': 'generate_sphp_or_skrtp',
                        'data': {'loan_id': loan.id},
                        'message': "Failed to create PDF",
                        'errors': str(e),
                    }
                )
                return
            response = HttpResponse(pdf, content_type='application/pdf')

            now = datetime.now()
            filename = '{}_{}_{}_{}.pdf'.format(
                application.fullname,
                application.application_xid,
                now.strftime("%Y%m%d"),
                now.strftime("%H%M%S")
            )
            response['Content-Disposition'] = 'filename="' + filename + '"'

            return response

        if loan.loan_status_id == LoanStatusCodes.FUND_DISBURSAL_ONGOING:
            temp_application = application if application else loan.get_application

            template, _ = get_loan_agreement_template_julo_one(loan.id, is_simulation=True)
            if not template:
                logger.error(
                    {
                        'action_view': 'generate_sphp_or_skrtp',
                        'data': {'loan_id': loan.id},
                        'errors': "Template tidak ditemukan.",
                    }
                )
                return

            if temp_application.is_dana_flow():
                doc_response = HttpResponse(content_type='application/pdf')
                pisa_status = pisa.CreatePDF(
                    template, dest=doc_response
                )
                if pisa_status.err:
                    return HttpResponse('We had some errors: {}'.format(pisa_status.err))
            else:
                try:
                    pdf = pdfkit.from_string(template, False)
                except Exception as e:
                    logger.error(
                        {
                            'action_view': 'generate_sphp_or_skrtp',
                            'data': {'loan_id': loan.id},
                            'message': "Failed to create PDF",
                            'errors': str(e),
                        }
                    )
                    return

                doc_response = HttpResponse(pdf, content_type='application/pdf')

            now = datetime.now()
            filename = '{}_{}_{}_{}.pdf'.format(
                temp_application.fullname,
                temp_application.application_xid,
                now.strftime("%Y%m%d"),
                now.strftime("%H%M%S"),
            )
            doc_response['Content-Disposition'] = 'filename="' + filename + '"'

            return doc_response

        document = None
        error_msg = None

        try:
            document = get_skrtp_or_sphp_pdf(loan, application)
        except Exception as e:
            # document not found and creation of document failed
            error_msg = str(e)
            logger.error({
                'action_view': 'FollowTheMoney - Generate SKRTP or SPHP pdf',
                'data': loan.id,
                'errors': str(e)
            })

        if not document:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": error_msg
                },
            )

        document_stream = get_file_from_oss(settings.OSS_MEDIA_BUCKET, document.url)
        response = StreamingHttpResponse(
            streaming_content=document_stream, content_type='application/pdf'
        )
        response['Content-Disposition'] = 'filename="' + document.filename + '"'

        return response

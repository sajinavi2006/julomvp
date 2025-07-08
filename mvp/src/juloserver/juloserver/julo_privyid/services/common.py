# Common services
from builtins import str
import os
import tempfile
from django.utils import timezone
from celery import task

import requests

from juloserver.julo.models import Document
from juloserver.julo.tasks import upload_document
from juloserver.julo.models import MobileFeatureSetting
from juloserver.julo.models import SignatureVendorLog
from juloserver.julo.models import Loan


def get_failover_feature():
    failover = MobileFeatureSetting.objects.filter(
        feature_name="digital_signature_failover", is_active=True
    ).last()

    if failover:
        return True

    return False


def get_privy_feature():
    privy_mode = MobileFeatureSetting.objects.filter(
        feature_name="privy_mode", is_active=True
    ).last()

    if privy_mode:
        return True

    return False


@task(name="store_privy_api_data")
def store_privy_api_data(loan_xid, api_data, application=None, document=None):
    if loan_xid is not None:
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
    else:
        loan = None
    application = application
    SignatureVendorLog.objects.create(
        loan=loan,
        application=application,
        vendor="PrivyID",
        event=api_data["request_path"],
        response_code=int(api_data["response_status_code"]),
        response_string=api_data["response_json"],
        request_string=api_data["request_params"],
        document=document,
    )


@task(name="upload_privy_sphp_document")
def upload_privy_sphp_document(url, loan_id, loan_xid, fullname):
    from juloserver.followthemoney.tasks import generate_julo_one_loan_agreement

    now = timezone.localtime(timezone.now())
    filename = "{}_{}_{}_{}.pdf".format(
        fullname, loan_xid, now.strftime("%Y%m%d"), now.strftime("%H%M%S")
    )
    file_path = os.path.join(tempfile.gettempdir(), filename)
    download_req = requests.get(url, allow_redirects=True)
    with open(file_path, "w") as f:
        f.write(str(download_req.content))

    document_types = ["sphp_privy", "sphp_julo"]
    document = Document.objects.filter(
        loan_xid=loan_xid, document_type__in=document_types
    ).last()
    if not document:
        generate_julo_one_loan_agreement(loan_id)
        document = Document.objects.filter(
            loan_xid=loan_xid, document_type__in=document_types
        ).last()

    if document:
        upload_document(document.id, file_path, is_loan=True)
        document.document_type = "sphp_privy"
        document.save()

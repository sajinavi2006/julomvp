import logging
from spyne import Application, rpc, ServiceBase, \
    Integer, Unicode, Array, String, DateTime
from spyne import Iterable

from spyne.model.complex import ComplexModel
from spyne.protocol.http import HttpRpc
from spyne.server.http import HttpTransportContext
from spyne.protocol.soap import Soap11
from spyne.protocol.json import JsonDocument
from spyne.protocol.xml import XmlDocument

from spyne.server.django import DjangoApplication

from django.views.decorators.csrf import csrf_exempt
from ..julo.models import PartnerLoan
from .services import store_partner_loan_to_db


class PartnerLoanService(ServiceBase):
    @rpc(Unicode, Unicode, Unicode, Unicode, DateTime,
        Unicode, Unicode, DateTime, DateTime, Unicode,
        Unicode, DateTime, Unicode, Integer, _returns=Iterable(Unicode),
        _out_variable_name='PartnerLoanResponse')
    def partner_loan(
        ctx, SubmissionID, AgreementNo, CustomerName, BFIBranch, TelePullDate,
        TeleAssignmentStatus, TeleAssignmentDetailStatus, SurveyorAssignmentDate, SurveyFinishDate,
        SurveyStatus, SurveyDetailStatus, ApprovalDate, ApprovalStatus, NTFAmount):
        if isinstance(ctx.transport, HttpTransportContext):
            headers = ctx.transport.resp_headers
            file_name = "{}.xml".format(ctx.descriptor.name)

            ctx.transport.set_mime_type("application/xml")
            headers['Content-Disposition'] = \
                                           'attachment; filename=%s' % file_name
        data = {}
        data['SubmissionID'] = SubmissionID
        data['AgreementNo'] = AgreementNo
        data['CustomerName'] = CustomerName
        data['BFIBranch'] = BFIBranch
        data['TelePullDate'] = TelePullDate
        data['TeleAssignmentStatus'] = TeleAssignmentStatus
        data['TeleAssignmentDetailStatus'] = TeleAssignmentDetailStatus
        data['SurveyorAssignmentDate'] = SurveyorAssignmentDate
        data['SurveyFinishDate'] = SurveyFinishDate
        data['SurveyStatus'] = SurveyStatus
        data['SurveyDetailStatus'] = SurveyDetailStatus
        data['ApprovalDate'] = ApprovalDate
        data['ApprovalStatus'] = ApprovalStatus
        data['NTFAmount'] = NTFAmount

        store_partner_loan_to_db(data)

        yield 'success'

application = Application([PartnerLoanService],
    tns='julosoap.service.partnerloan',
    in_protocol=Soap11(validator='soft'),
    out_protocol=Soap11()
)

julosoap = csrf_exempt(DjangoApplication(application))

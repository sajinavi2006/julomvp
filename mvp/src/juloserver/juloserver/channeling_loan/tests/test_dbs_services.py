import json
from datetime import timedelta

from unittest.mock import patch, MagicMock, Mock

from django.db.models import Sum
from django.test import TestCase
from django.test.client import RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from juloserver.account.tests.factories import AccountLimitFactory, AccountFactory
from juloserver.channeling_loan.constants import (
    ChannelingConst,
    ChannelingStatusConst,
)
from juloserver.channeling_loan.constants.dbs_constants import (
    DBSDisbursementConst,
    DBSApplicationTypeConst,
    JULO_ORG_ID_GIVEN_BY_DBS,
    DBSReconciliationConst,
    DBSRepaymentConst,
    DBSDisbursementDocumentConst,
    DBSChannelingUpdateLoanStatusConst,
)
from juloserver.channeling_loan.exceptions import (
    DBSApiError,
    ChannelingLoanStatusNotFound,
    ChannelingMappingNullValueError,
)
from juloserver.channeling_loan.models import ChannelingLoanPayment, ChannelingLoanStatus
from juloserver.channeling_loan.services.dbs_services import (
    DBSDisbursementServices,
    DBSMappingServices,
    DBSUpdateLoanStatusService,
    DBSDisbursementDocumentServices,
)
from juloserver.channeling_loan.tests.factories import (
    ChannelingLoanPaymentFactory,
    ChannelingLoanStatusFactory,
    DBSChannelingApplicationJobFactory,
)
from juloserver.channeling_loan.services.dbs_services import (
    DBSRepaymentServices,
    DBSReconciliationServices,
)
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from juloserver.julo.tests.factories import (
    CustomerFactory,
    LoanFactory,
    OcrKtpResultFactory,
    AuthUserFactory,
    ApplicationFactory,
)
from juloserver.followthemoney.factories import LenderCurrentFactory


class TestDBSDisbursementServices(TestCase):
    def setUp(self):
        self.service = DBSDisbursementServices()
        self.service.channeling_loan_config = {
            "general": {
                "INTEREST_PERCENTAGE": 0.4,
            }
        }
        self.loan = LoanFactory()

    @patch("juloserver.channeling_loan.services.dbs_services.get_credit_score_conversion")
    def test_construct_disbursement_request_body(self, mock_credit_score_conversion):
        mock_credit_score_conversion.return_value = "A"

        bank_account_destination = BankAccountDestinationFactory()
        application = ApplicationFactory(employment_status='kontrak')
        customer = CustomerFactory(
            mother_maiden_name='Test Mother Maiden Name',
            marital_status="Menikah",
            last_education="S1",
            job_type="Tidak bekerja",
            job_industry="Admin / Finance / HR",
            birth_place="Jakarta",
            nik="1234567890123456",
            company_name="PT Test",
            job_description="Admin",
            company_phone_number="+64123456789",
            address_street_num="Nomor 12AB"
        )
        loan = LoanFactory(
            loan_xid=1234567890,
            application=application,
            customer=customer,
            bank_account_destination=bank_account_destination,
            sphp_accepted_ts=timezone.localtime(timezone.now()),
        )
        ocr_ktp_result = OcrKtpResultFactory(
            application_id=loan.get_application.id, rt_rw="001/002"
        )
        DBSChannelingApplicationJobFactory(
            job_industry="Admin / Finance / HR",
            job_description="Admin",
            is_exclude=False,
            aml_risk_rating="High",
            job_code='06',
            job_industry_code='04',
        )
        account = AccountFactory(customer=customer)
        account_limit = AccountLimitFactory(
            account=account, available_limit=1_000_000, set_limit=2_000_000
        )

        payments = loan.payment_set.order_by("payment_number")
        for payment in payments:
            ChannelingLoanPaymentFactory(
                payment=payment,
                due_amount=payment.due_amount,
                interest_amount=payment.installment_interest,
                channeling_type=ChannelingConst.DBS,
            )

        x_dbs_uuid = 'test_dbs_uuid'
        contract_code = f'{DBSDisbursementConst.PROGRAM}{str(loan.loan_xid).zfill(12)}'

        data = self.service.construct_disbursement_request_body(loan=loan, x_dbs_uuid=x_dbs_uuid)
        self.assertIsNotNone(data)

        # CHECK SOME FIELDS THAT HAVE FUNCTION AFTER MAPPING IN DBSMappingServices

        header = data['header']
        self.assertEqual(header['msgId'], x_dbs_uuid)
        self.assertEqual(header['orgId'], JULO_ORG_ID_GIVEN_BY_DBS)
        self.assertEqual(
            header['timeStamp'],
            DBSMappingServices.get_time_stamp(current_ts=self.service.current_ts),
        )

        loan_application_request = data['data']['loanApplicationRequest']
        self.assertEqual(loan_application_request['applicationType'], DBSApplicationTypeConst.NEW)

        retail_demographic = loan_application_request['retailDemographic']
        self.assertEqual(retail_demographic['gender'], "2" if customer.gender == "Wanita" else "1")
        self.assertEqual(retail_demographic['maritalStatus'], "3")
        self.assertEqual(retail_demographic['educationLevel'], "1")

        employment_detl = loan_application_request['employmentDetl']
        self.assertEqual(employment_detl['employmentPeriod']['numberOfYears'], "00")
        self.assertEqual(employment_detl['employmentPeriod']['numberOfMonths'], "00")
        self.assertEqual(employment_detl['jobCode'], "06")
        self.assertEqual(employment_detl['industry'], "04")
        self.assertEqual(employment_detl['employerPhone'], "+64123456789")
        self.assertEqual(employment_detl['employerAddress']['addressLine1'], "Nomor 12AB")
        # self.assertEqual(employment_detl['employmentStatus'], "")

        dbs_installment_amount = (
            ChannelingLoanPayment.objects.filter(
                channeling_type=ChannelingConst.DBS,
                payment__in=payments,
            )
            .last()
            .due_amount
        )

        dbs_total_interest_amount = ChannelingLoanPayment.objects.filter(
            channeling_type=ChannelingConst.DBS,
            payment__in=payments,
        ).aggregate(Sum('interest_amount'))['interest_amount__sum']

        first_loan_offer_detl = loan_application_request['loanOfferDetl'][0]
        self.assertEqual(first_loan_offer_detl['interestRate'], 40)  # 0040
        self.assertEqual(
            first_loan_offer_detl['interestAmount']['amount'],
            dbs_total_interest_amount,
        )
        self.assertEqual(
            first_loan_offer_detl['instalmentAmount']['amount'],
            dbs_installment_amount,
        )

        contract_info = loan_application_request['contractInfo']
        self.assertEqual(
            contract_info['mfInterestRate'],
            DBSMappingServices().get_yearly_interest_rate(loan.interest_rate_monthly),
        )
        self.assertEqual(
            contract_info['bankInstallment'],
            dbs_installment_amount,
        )
        self.assertEqual(
            contract_info['bankInterest'],
            dbs_total_interest_amount,
        )
        self.assertEqual(contract_info['bankInterestRate'], 40)
        self.assertEqual(contract_info['contractCode'], contract_code)
        self.assertEqual(contract_info['creditLimit'], str(account_limit.set_limit))
        self.assertEqual(contract_info['creditScoring'], "A")

        self.assertEqual(loan_application_request['goodsInfo']['contractCode'], contract_code)

        # check construct loan schedule list
        loan_schedule_list = loan_application_request["loanScheduleList"]
        self.assertEqual(len(loan_schedule_list), payments.count())
        for i, loan_schedule in enumerate(loan_schedule_list):
            payment = payments[i]
            channeling_loan_payment = payment.channelingloanpayment_set.filter(
                channeling_type=ChannelingConst.DBS,
            ).last()
            self.assertEqual(loan_schedule['dueDate'], payment.due_date.strftime("%Y-%m-%d"))
            self.assertEqual(loan_schedule['contractCode'], contract_code)
            self.assertEqual(loan_schedule['installmentAmount'], channeling_loan_payment.due_amount)
            self.assertEqual(loan_schedule['installmentNumber'], str(payment.payment_number))
            self.assertEqual(loan_schedule['interest'], channeling_loan_payment.interest_amount)
            self.assertEqual(loan_schedule['principal'], channeling_loan_payment.principal_amount)
            self.assertEqual(loan_schedule['recordIndicator'], 'D')

        # TEST MISSING OCR KTP RESULT THAT IS ONE OF REQUIRED FIELDS
        ocr_ktp_result.delete()
        with self.assertRaises(ChannelingMappingNullValueError):
            self.service.construct_disbursement_request_body(loan=loan, x_dbs_uuid=x_dbs_uuid)

    def test_generate_x_dbs_uuid(self):
        result = self.service.generate_x_dbs_uuid(loan_xid=12345)
        self.assertEqual(result, f'{self.service.current_ts.strftime("%Y%m%d")}12345')

    @patch('juloserver.channeling_loan.services.dbs_services.get_dbs_channeling_client')
    @patch('juloserver.channeling_loan.services.dbs_services.create_channeling_loan_api_log')
    @patch('juloserver.channeling_loan.services.dbs_services.sentry_client')
    @patch('juloserver.channeling_loan.services.dbs_services.decrypt_dbs_data_with_gpg')
    @patch('juloserver.channeling_loan.services.dbs_services.encrypt_and_sign_dbs_data_with_gpg')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.'
        'DBSDisbursementServices.construct_disbursement_request_body'
    )
    def test_process_sending_loan_to_dbs(
        self,
        mock_construct_disbursement_request_body,
        mock_encrypt_and_sign_data_with_gpg,
        mock_decrypt_dbs_data_with_gpg,
        mock_sentry_client,
        mock_create_log,
        mock_get_client,
    ):
        # Test construct request body got ChannelingMappingNullValueError
        # => don't hit API, don't raise error
        mock_construct_disbursement_request_body.side_effect = ChannelingMappingNullValueError(
            "Value is null and not allowed to be null"
        )
        success, should_retry, response = self.service.process_sending_loan_to_dbs(loan=self.loan)
        self.assertFalse(success)
        self.assertFalse(should_retry)
        self.assertEqual(response, "field=None: Value is null and not allowed to be null")
        mock_get_client.assert_not_called()

        # Test construct request body other errors => don't hit API, raise error
        mock_construct_disbursement_request_body.side_effect = ValueError("Invalid data")
        with self.assertRaises(ValueError):
            self.service.process_sending_loan_to_dbs(loan=self.loan)
        mock_get_client.assert_not_called()

        # Test success => hit API, write API log, don't raise error
        mock_request_body = {'test_body': 123}
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "success"}'
        mock_decrypt_dbs_data_with_gpg.return_value = '{"status": "success"}'
        mock_client = Mock()
        mock_client.send_loan.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_encrypt_and_sign_data_with_gpg.return_value = 'encrypted_and_sign_body'
        mock_construct_disbursement_request_body.side_effect = None
        mock_construct_disbursement_request_body.return_value = mock_request_body
        success, should_retry, response = self.service.process_sending_loan_to_dbs(loan=self.loan)
        self.assertTrue(success)
        self.assertFalse(should_retry)
        self.assertEqual(response, {"status": "success"})
        mock_encrypt_and_sign_data_with_gpg.assert_called_once_with(data='{"test_body": 123}')
        mock_create_log.assert_called_once_with(
            channeling_type=ChannelingConst.DBS,
            application_id=self.loan.get_application.id,
            loan_id=self.loan.id,
            request_type=DBSDisbursementConst.REQUEST_TYPE_API_IN_LOG,
            request=json.dumps(mock_request_body),
            http_status_code=200,
            response='{"status": "success"}',
            error_message=None,
        )
        mock_sentry_client.captureException.assert_not_called()

        # Test calling API error => hit API, write API log, raise error
        mock_encrypt_and_sign_data_with_gpg.reset_mock()
        mock_decrypt_dbs_data_with_gpg.reset_mock()
        mock_error = DBSApiError("API Error")
        mock_error.response_status_code = 500
        mock_error.response_text = "Internal Server Error"
        mock_error.message = "API Error"
        mock_client = Mock()
        mock_client.send_loan.side_effect = mock_error
        mock_get_client.return_value = mock_client
        mock_create_log.reset_mock()
        mock_sentry_client.captureException.reset_mock()
        success, should_retry, response = self.service.process_sending_loan_to_dbs(loan=self.loan)
        self.assertFalse(success)
        self.assertTrue(should_retry)
        self.assertEqual(response, 'Failed to send loan to DBS')
        mock_encrypt_and_sign_data_with_gpg.assert_called_once_with(data='{"test_body": 123}')
        mock_decrypt_dbs_data_with_gpg.assert_not_called()
        mock_create_log.assert_called_once_with(
            channeling_type=ChannelingConst.DBS,
            application_id=self.loan.get_application.id,
            loan_id=self.loan.id,
            request_type=DBSDisbursementConst.REQUEST_TYPE_API_IN_LOG,
            request=json.dumps(mock_request_body),
            http_status_code=500,
            response="Internal Server Error",
            error_message="API Error",
        )
        mock_sentry_client.captureException.assert_called_once()

        # Test invalid json response => hit API, write API log, raise error
        mock_response = Mock()
        mock_response.status_code = 200
        mock_encrypt_and_sign_data_with_gpg.reset_mock()
        mock_decrypt_dbs_data_with_gpg.reset_mock()
        mock_decrypt_dbs_data_with_gpg.return_value = 'invalid json'
        mock_client = Mock()
        mock_client.send_loan.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_create_log.reset_mock()
        mock_sentry_client.captureException.reset_mock()
        success, should_retry, response = self.service.process_sending_loan_to_dbs(loan=self.loan)
        self.assertFalse(success)
        self.assertTrue(should_retry)
        self.assertEqual(response, 'Failed to send loan to DBS')
        mock_encrypt_and_sign_data_with_gpg.assert_called()
        mock_decrypt_dbs_data_with_gpg.assert_called()
        mock_create_log.assert_called_once_with(
            channeling_type=ChannelingConst.DBS,
            application_id=self.loan.get_application.id,
            loan_id=self.loan.id,
            request_type=DBSDisbursementConst.REQUEST_TYPE_API_IN_LOG,
            request=json.dumps(mock_request_body),
            http_status_code=200,
            response='invalid json',
            error_message=None,
        )
        mock_sentry_client.captureException.assert_called_once()

        # Test decrypt response failed => return None => hit API, write API log, raise error
        mock_response = Mock()
        mock_response.status_code = 200
        mock_encrypt_and_sign_data_with_gpg.reset_mock()
        mock_decrypt_dbs_data_with_gpg.reset_mock()
        mock_decrypt_dbs_data_with_gpg.return_value = None
        mock_client = Mock()
        mock_client.send_loan.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_create_log.reset_mock()
        mock_sentry_client.captureException.reset_mock()
        success, should_retry, response = self.service.process_sending_loan_to_dbs(loan=self.loan)
        self.assertFalse(success)
        self.assertTrue(should_retry)
        self.assertEqual(response, 'Failed to send loan to DBS')
        mock_encrypt_and_sign_data_with_gpg.assert_called()
        mock_decrypt_dbs_data_with_gpg.assert_called()
        mock_create_log.assert_called_once_with(
            channeling_type=ChannelingConst.DBS,
            application_id=self.loan.get_application.id,
            loan_id=self.loan.id,
            request_type=DBSDisbursementConst.REQUEST_TYPE_API_IN_LOG,
            request=json.dumps(mock_request_body),
            http_status_code=200,
            response='',
            error_message=None,
        )
        mock_sentry_client.captureException.assert_called_once()

    def test_parse_error_from_response(self):
        # Test when response has no error data
        response = {"data": {"status": "success"}}
        result = self.service.parse_error_from_response(channeling_response=response)
        self.assertIsNone(result)

        # Test when error contains errorList with message
        response = {
            "data": {
                "error": {
                    "errorList": [
                        {
                            "code": "S997",
                            "message": "Your request cannot be validated",
                            "moreInfo": "CAPI15887604823577118",
                        }
                    ]
                }
            }
        }
        result = self.service.parse_error_from_response(channeling_response=response)
        self.assertEqual(result, "Your request cannot be validated")

        # Test when error contains description instead of errorList
        response = {
            "error": {
                "status": "RJCT",
                "code": "A001",
                "description": "Organisation ID is incorrect",
            }
        }
        result = self.service.parse_error_from_response(channeling_response=response)
        self.assertEqual(result, "Organisation ID is incorrect")

        # Test when both errorList and description are present
        # Should prioritize errorList message
        response = {
            "data": {
                "error": {
                    "errorList": [{"message": "Invalid input"}],
                    "description": "General error occurred",
                }
            }
        }
        result = self.service.parse_error_from_response(channeling_response=response)
        self.assertEqual(result, "Invalid input")

    @patch('juloserver.channeling_loan.services.dbs_services.get_channeling_loan_status')
    @patch('juloserver.channeling_loan.services.dbs_services.check_common_failed_channeling')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.'
        'DBSDisbursementServices.process_sending_loan_to_dbs'
    )
    @patch(
        'juloserver.channeling_loan.services.dbs_services.'
        'DBSDisbursementServices.parse_error_from_response'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.update_channeling_loan_status')
    @patch('juloserver.channeling_loan.services.dbs_services.logger')
    def test_send_loan_for_channeling_to_dbs(
        self,
        mock_logger,
        mock_update_channeling_loan_status,
        mock_parse_error_from_response,
        mock_process_sending_loan_to_dbs,
        mock_check_common_failed_channeling,
        mock_get_channeling_loan_status,
    ):
        # Test not found channeling loan status => raise error
        mock_get_channeling_loan_status.return_value = None
        mock_logger.reset_mock()
        with self.assertRaises(ChannelingLoanStatusNotFound):
            self.service.send_loan_for_channeling_to_dbs(loan=self.loan)
        mock_get_channeling_loan_status.assert_called_once_with(
            loan=self.loan, status=ChannelingStatusConst.PENDING
        )
        mock_update_channeling_loan_status.assert_not_called()
        mock_logger.info.assert_not_called()

        channeling_loan_status = ChannelingLoanStatusFactory(
            channeling_status=ChannelingStatusConst.PENDING
        )
        mock_get_channeling_loan_status.return_value = channeling_loan_status

        # Test when common channeling check fails => update status to failed, log
        mock_check_common_failed_channeling.return_value = "Failed validation"
        status, message = self.service.send_loan_for_channeling_to_dbs(loan=self.loan)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Failed validation")
        mock_update_channeling_loan_status.assert_called_once_with(
            channeling_loan_status_id=channeling_loan_status.id,
            new_status=ChannelingStatusConst.FAILED,
            change_reason="Failed validation",
        )
        mock_logger.info.assert_called_once()

        mock_check_common_failed_channeling.return_value = None

        # Test construct body fail => update status to failed, log
        mock_update_channeling_loan_status.reset_mock()
        mock_logger.reset_mock()
        mock_process_sending_loan_to_dbs.return_value = (
            False,
            False,
            "field=abc: Value is null and not allowed to be null",
        )
        status, message = self.service.send_loan_for_channeling_to_dbs(loan=self.loan)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "field=abc: Value is null and not allowed to be null")
        mock_update_channeling_loan_status.assert_called_once_with(
            channeling_loan_status_id=channeling_loan_status.id,
            new_status=ChannelingStatusConst.FAILED,
            change_reason="field=abc: Value is null and not allowed to be null",
        )
        mock_logger.info.assert_called_once()

        # Test when sending to DBS fails => only log
        mock_update_channeling_loan_status.reset_mock()
        mock_logger.reset_mock()
        mock_process_sending_loan_to_dbs.return_value = (False, True, 'Failed to send loan to DBS')
        status, message = self.service.send_loan_for_channeling_to_dbs(loan=self.loan)
        self.assertIsNone(status)
        self.assertEqual(message, "Failed to send loan to DBS")
        mock_update_channeling_loan_status.assert_not_called()
        mock_logger.info.assert_called_once()

        # Test when DBS response contains error => update status to failed, log
        mock_process_sending_loan_to_dbs.return_value = (
            True,
            False,
            {"error": "Something went wrong"},
        )
        mock_parse_error_from_response.return_value = "Error message"
        mock_logger.reset_mock()
        status, message = self.service.send_loan_for_channeling_to_dbs(loan=self.loan)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Error message")
        mock_update_channeling_loan_status.assert_called_once_with(
            channeling_loan_status_id=channeling_loan_status.id,
            new_status=ChannelingStatusConst.FAILED,
            change_reason="Error message",
        )
        mock_logger.info.assert_called_once()

        # Test successful loan sending to DBS
        mock_process_sending_loan_to_dbs.return_value = (True, False, {"status": "success"})
        mock_parse_error_from_response.return_value = None
        mock_update_channeling_loan_status.reset_mock()
        mock_logger.reset_mock()
        status, message = self.service.send_loan_for_channeling_to_dbs(loan=self.loan)
        self.assertEqual(status, ChannelingStatusConst.PROCESS)
        self.assertEqual(message, "Success to send loan to DBS, wait for callback")
        mock_update_channeling_loan_status.assert_called_once_with(
            channeling_loan_status_id=channeling_loan_status.id,
            new_status=ChannelingStatusConst.PROCESS,
            change_reason="Success to send loan to DBS, wait for callback",
        )
        mock_logger.info.assert_called_once()


class TestDBSUpdateLoanStatusService(TestCase):
    def setUp(self):
        self.loan_xid = 'test_loan_xid'
        self.x_dbs_uuid = 'test_uuid'
        self.service = DBSUpdateLoanStatusService()

    def test_generate_error_data(self):
        # test param errors
        errors = [
            self.service.DBSErrorResponse(message="Error 1"),
            self.service.DBSErrorResponse(
                message="Error 2", code="CUSTOM_CODE", more_info="More info"
            ),
        ]
        error_data = self.service.generate_error_data(x_dbs_uuid=self.x_dbs_uuid, errors=errors)
        self.assertEqual(len(error_data['data']['error']['errorList']), 2)
        self.assertEqual(error_data['data']['error']['errorList'][0]['code'], "S801")
        self.assertEqual(error_data['data']['error']['errorList'][0]['message'], "Error 1")
        self.assertEqual(
            error_data['data']['error']['errorList'][0]['moreInfo'],
            DBSChannelingUpdateLoanStatusConst.ERROR_MESSAGE_VALIDATION_ERROR,
        )
        self.assertEqual(error_data['data']['error']['errorList'][1]['code'], "CUSTOM_CODE")
        self.assertEqual(error_data['data']['error']['errorList'][1]['message'], "Error 2")
        self.assertEqual(error_data['data']['error']['errorList'][1]['moreInfo'], "More info")

        # test param error_message
        error_data = self.service.generate_error_data(
            x_dbs_uuid=self.x_dbs_uuid, error_message="Single error message"
        )
        self.assertEqual(len(error_data['data']['error']['errorList']), 1)
        self.assertEqual(error_data['data']['error']['errorList'][0]['code'], "S801")
        self.assertEqual(
            error_data['data']['error']['errorList'][0]['moreInfo'],
            "Your request cannot be validated. Please rectify the input data",
        )
        self.assertEqual(
            error_data['data']['error']['errorList'][0]['message'], "Single error message"
        )

    def test_generate_success_data(self):
        success_data = self.service.generate_success_data(x_dbs_uuid=self.x_dbs_uuid)

        self.assertEqual(success_data['header']['msgId'], self.x_dbs_uuid)
        self.assertIn('receiptDateTime', success_data['data']['loanApplicationStatusResponse'])

    def test_generate_serializer_errors(self):
        serializer_errors = {'field1': ['Error 1', 'Error 2'], 'field2': ['Error 3']}
        error_data = self.service.generate_serializer_errors(
            x_dbs_uuid=self.x_dbs_uuid, request_serializer_errors=serializer_errors
        )

        self.assertEqual(len(error_data['data']['error']['errorList']), 2)
        self.assertEqual(error_data['data']['error']['errorList'][0]['code'], "S997")
        self.assertEqual(
            error_data['data']['error']['errorList'][0]['moreInfo'],
            "Your request cannot be validated. Please verify the input parameters",
        )
        self.assertEqual(error_data['data']['error']['errorList'][0]['message'], "field1")
        self.assertEqual(error_data['data']['error']['errorList'][1]['code'], "S997")
        self.assertEqual(
            error_data['data']['error']['errorList'][1]['moreInfo'],
            "Your request cannot be validated. Please verify the input parameters",
        )
        self.assertEqual(error_data['data']['error']['errorList'][1]['message'], "field2")

    def test_get_headers(self):
        # success
        request_metas = {
            'HTTP_X_DBS_UUID': 'test_uuid',
            'HTTP_X_DBS_ORG_ID': 'test_org',
        }
        is_valid, headers = self.service.get_headers(request_metas)
        self.assertTrue(is_valid)
        self.assertEqual(len(headers), 8)  # 4 required headers + 4 optional headers
        self.assertEqual(headers['HTTP_X_DBS_UUID'], 'test_uuid')
        self.assertEqual(headers['HTTP_X_DBS_ORG_ID'], 'test_org')
        self.assertIsNone(headers['HTTP_X_DBS_CLIENTID'])
        self.assertIsNone(headers['HTTP_X_DBS_ACCESSTOKEN'])
        self.assertIsNone(headers['HTTP_X_DBS_ACCEPT_VERSION'])
        self.assertIsNone(headers['HTTP_X_DBS_SERVICINGCOUNTRY'])

        # missing
        request_metas = {
            # Missing 'HTTP_X_DBS_UUID': 'test_uuid',
            'HTTP_X_DBS_ORG_ID': 'test_org',
        }
        is_valid, error_data = self.service.get_headers(request_metas)
        self.assertFalse(is_valid)
        self.assertIn('Missing required headers', error_data)

    @patch(
        'juloserver.channeling_loan.services.dbs_services.get_channeling_loan_status_by_loan_xid'
    )
    def test_get_channeling_loan_status(self, mock_get_status):
        # success
        mock_status = MagicMock(spec=ChannelingLoanStatus)
        mock_status.channeling_status = ChannelingStatusConst.PROCESS
        mock_get_status.return_value = mock_status
        is_valid, status = self.service.get_channeling_loan_status(loan_xid=self.loan_xid)
        self.assertTrue(is_valid)
        self.assertEqual(status, mock_status)

        # not found
        mock_get_status.return_value = None
        is_valid, error_data = self.service.get_channeling_loan_status(loan_xid=self.loan_xid)
        self.assertFalse(is_valid)
        self.assertEqual('applicationId not found', error_data)

        # already processed
        mock_status = MagicMock(spec=ChannelingLoanStatus)
        mock_status.channeling_status = ChannelingStatusConst.FAILED
        mock_get_status.return_value = mock_status
        is_valid, error_data = self.service.get_channeling_loan_status(loan_xid=self.loan_xid)
        self.assertFalse(is_valid)
        self.assertEqual(
            'applicationId already be processed',
            error_data,
        )


class TestDBSRepaymentServices(TestCase):
    def setUp(self):
        self.service = DBSRepaymentServices()

    def test_get_dbs_repayment_data(self):
        csv_bytes = b'test\n1\n2\n'
        file = SimpleUploadedFile("test.txt", csv_bytes, content_type="text/plain")
        request = RequestFactory().request()
        request.FILES["repayment_file_field"] = file

        with self.assertRaises(Exception) as context:
            self.service.get_dbs_repayment_data(request)
            self.assertEqual(context, "Please upload correct file excel")

        csv_bytes = b'test\n1\n2\n'
        file = SimpleUploadedFile("test.csv", csv_bytes, content_type="text/csv")
        request = RequestFactory().request()
        request.FILES["repayment_file_field"] = file

        results = self.service.get_dbs_repayment_data(request)
        self.assertIsNotNone(results)

        for result in results:
            self.assertTrue("test" in result)

    def test_construct_dbs_repayment_request_file_content(self):
        list_data = [
            {
                "loan_xid": "1000097141",
                "event_date": "16/02/2025",
                "event_payment": "100000",
                "sol_id": "306",
            },
            {
                "loan_xid": "1000097142",
                "event_date": "17/02/2025",
                "event_payment": "100000",
                "sol_id": "306",
            },
            {
                "loan_xid": "1000097143",
                "event_date": "18/02/2025",
                "event_payment": "100000",
                "sol_id": "306",
            },
            {
                "loan_xid": "1000097144",
                "event_date": "19/02/2025",
                "event_payment": "100000",
                "sol_id": "306",
            },
        ]

        is_success, result = self.service.construct_dbs_repayment_request_xlsx_bytes(
            headers=DBSRepaymentConst.REPAYMENT_DATA_HEADER_DICTIONARY,
            sheet_name=DBSRepaymentConst.SHEET_NAME,
            list_data=list_data,
        )

        self.assertTrue(is_success)
        self.assertIsNotNone(result)

    def test_send_repayment_for_channeling_to_dbs(self):
        csv_bytes = b'test\n1\n2\n'
        file = SimpleUploadedFile("test.csv", csv_bytes, content_type="text/csv")
        request = RequestFactory().request()
        request.FILES["repayment_file_field"] = file

        result = self.service.send_repayment_for_channeling_to_dbs(request)
        self.assertIsNotNone(result)


class TestDBSReconciliationServices(TestCase):
    def setUp(self):
        self.service = DBSReconciliationServices()

    def test_get_dbs_reconciliation_data(self):
        csv_bytes = b'test\n1\n2\n'
        file = SimpleUploadedFile("test.txt", csv_bytes, content_type="text/plain")
        request = RequestFactory().request()
        request.FILES["reconciliation_file_field"] = file

        with self.assertRaises(Exception) as context:
            self.service.get_dbs_reconciliation_data(request)
            self.assertEqual(context, "Please upload correct file excel")

        csv_bytes = b'test\n1\n2\n'
        file = SimpleUploadedFile("test.csv", csv_bytes, content_type="text/csv")
        request = RequestFactory().request()
        request.FILES["reconciliation_file_field"] = file

        results = self.service.get_dbs_reconciliation_data(request)
        self.assertIsNotNone(results)

        for result in results:
            self.assertTrue("test" in result)

    def test_construct_dbs_reconciliation_request_file_content(self):
        list_data = [
            {
                "partner_contract_number": "1234567890",
                "reconciliation_date": "16/02/2025",
                "outstanding": "100000",
                "dpd": "1",
            },
            {
                "partner_contract_number": "1234567891",
                "reconciliation_date": "17/02/2025",
                "outstanding": "100000",
                "dpd": "2",
            },
            {
                "partner_contract_number": "1234567892",
                "reconciliation_date": "18/02/2025",
                "outstanding": "100000",
                "dpd": "3",
            },
            {
                "partner_contract_number": "1234567893",
                "reconciliation_date": "19/02/2025",
                "outstanding": "100000",
                "dpd": "4",
            },
        ]

        is_success, result = self.service.construct_dbs_reconciliation_request_txt_content(
            dict_rows=list_data,
            data_header_list=DBSReconciliationConst.RECONCILIATION_DATA_HEADER_LIST,
        )
        self.assertTrue(is_success)
        self.assertIsNotNone(result)

    def test_send_reconciliation_for_channeling_to_dbs(self):
        csv_bytes = b'test\n1\n2\n'
        file = SimpleUploadedFile("test.csv", csv_bytes, content_type="text/csv")
        request = RequestFactory().request()
        request.FILES["reconciliation_file_field"] = file

        result = self.service.send_reconciliation_for_channeling_to_dbs(request)
        self.assertIsNotNone(result)


class TestDBSDisbursementDocumentServices(TestCase):
    def setUp(self):
        self.service = DBSDisbursementDocumentServices()
        self.service.channeling_loan_config = {
            "general": {
                "INTEREST_PERCENTAGE": 0.4,
            }
        }
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            mother_maiden_name='Test Mother Maiden Name',
            marital_status="Menikah",
            last_education="S1",
            job_type="Tidak bekerja",
            job_industry="Admin / Finance / HR",
            birth_place="Jakarta",
            nik="1234567890123456",
            company_name="PT Test",
            job_description="Admin",
        )
        self.dbs_channeling_application_job = DBSChannelingApplicationJobFactory(
            job_industry="Admin / Finance / HR",
            job_description="Admin",
            is_exclude=False,
            aml_risk_rating="High",
            job_code='06',
            job_industry_code='04',
        )
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(
            account=self.account, available_limit=1_000_000, set_limit=2_000_000
        )
        self.loan = LoanFactory(
            loan_xid=1234567890,
            customer=self.customer,
            sphp_accepted_ts=timezone.localtime(timezone.now()),
        )
        self.lender = LenderCurrentFactory(lender_name=ChannelingConst.LENDER_DBS)
        for payment in self.loan.payment_set.order_by("payment_number"):
            ChannelingLoanPaymentFactory(
                payment=payment,
                due_amount=payment.due_amount,
                interest_amount=payment.installment_interest,
                channeling_type=ChannelingConst.DBS,
                principal_amount=payment.installment_principal,
            )
        OcrKtpResultFactory(application_id=self.loan.get_application.id, rt_rw="001/002")
        self.channeling_loan_status = ChannelingLoanStatusFactory(
            loan=self.loan,
            channeling_type=ChannelingConst.DBS,
            channeling_status=ChannelingStatusConst.PENDING,
        )

    def test_map_loan_installment_list(self):
        result = self.service._DBSDisbursementDocumentServices__map_loan_installment_list(  # noqa
            loan=self.loan
        )

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), self.loan.payment_set.count())
        payment_number = 1
        for installment in result:
            payment = self.loan.payment_set.get(payment_number=payment_number)
            self.assertEqual(installment['RECORD_INDICATOR'], 'D')
            self.assertEqual(installment['CONTRACT_NUMBER'], 'JUL001234567890  ')
            self.assertEqual(installment['DUE_DATE'], payment.due_date.strftime('%d-%m-%Y'))
            self.assertEqual(installment['INSTALLMENT_NUMBER'], str(payment_number).zfill(3))
            self.assertEqual(
                installment['PRINCIPAL_AMOUNT'], str(payment.installment_principal).zfill(17)
            )
            self.assertEqual(
                installment['INTEREST_AMOUNT'], str(payment.installment_interest).zfill(17)
            )
            self.assertEqual(
                installment['INSTALLMENT_AMOUNT'],
                str(payment.installment_principal + payment.installment_interest).zfill(17),
            )
            self.assertEqual(installment['FILTER'], ''.ljust(118))
            payment_number += 1

    def test_map_list_disbursement_documents_data(self):
        # Setup another loan data
        application2 = ApplicationFactory(dependent=None)
        loan2 = LoanFactory(
            loan_xid=1234567891,
            application=application2,
            customer=self.customer,
            sphp_accepted_ts=timezone.localtime(timezone.now() - timedelta(days=2)),
        )
        for payment in loan2.payment_set.order_by("payment_number"):
            ChannelingLoanPaymentFactory(
                payment=payment,
                due_amount=payment.due_amount,
                interest_amount=payment.installment_interest,
                channeling_type=ChannelingConst.DBS,
                principal_amount=payment.installment_principal,
                actual_interest_amount=456,
            )
        OcrKtpResultFactory(application_id=loan2.get_application.id, rt_rw="003/004")
        channeling_loan_status2 = ChannelingLoanStatusFactory(
            loan=loan2,
            channeling_type=ChannelingConst.DBS,
            channeling_status=ChannelingStatusConst.PENDING,
        )

        result = self.service.map_list_disbursement_documents_data(
            channeling_loan_statuses=[self.channeling_loan_status, channeling_loan_status2]
        )

        # Assert
        (
            success_statuses,
            failed_statuses,
            failed_errors,
            applications,
            contracts,
            goods_info,
            installments,
        ) = result

        self.assertIsInstance(success_statuses, list)
        self.assertEqual(len(success_statuses), 2)
        self.assertEqual(success_statuses[0], self.channeling_loan_status.id)
        self.assertEqual(success_statuses[1], channeling_loan_status2.id)

        self.assertIsInstance(failed_statuses, list)
        self.assertEqual(len(failed_statuses), 0)
        self.assertEqual(len(failed_errors), 0)

        self.assertIsInstance(applications, list)
        self.assertEqual(len(applications), 2)
        first_application = applications[0]
        # check some fields in application
        self.assertEqual(first_application['TYPE'], '581')
        self.assertEqual(first_application['HOME_DISTRICT_CODE'], '02')
        self.assertEqual(first_application['HOME_SUB_DISTRICT_CODE'], '001')
        self.assertEqual(first_application['ID_CARD_SUB_DISTRICT_CODE'], '001')
        self.assertEqual(first_application['ID_CARD_DISTRICT_CODE'], '02')
        self.assertEqual(first_application['LOAN_AMOUNT_REQUEST'], str(self.loan.loan_amount))
        self.assertEqual(first_application['LOAN_TENOR'], str(self.loan.loan_duration))
        self.assertEqual(first_application['APPLICATION_REFERENCE_NUMBER'], 'JUL001234567890')
        self.assertEqual(first_application['RECOMMENDED_LIMIT'], str(self.loan.loan_amount))
        self.assertEqual(first_application['FINAL_INCOME'], str(self.customer.monthly_income))
        self.assertEqual(
            first_application['POSITION_CODE'], self.dbs_channeling_application_job.job_code
        )
        self.assertEqual(
            first_application['NATURE_OF_BUSINESS'],
            self.dbs_channeling_application_job.job_industry_code,
        )
        self.assertEqual(first_application['AML_RISK_RATING'], '1')
        self.assertEqual(
            first_application['NUMBER_OF_DEPENDENTS'], str(self.loan.get_application.dependent)
        )
        second_application = applications[1]
        self.assertEqual(second_application['HOME_DISTRICT_CODE'], '04')
        self.assertEqual(second_application['HOME_SUB_DISTRICT_CODE'], '003')
        self.assertEqual(second_application['ID_CARD_SUB_DISTRICT_CODE'], '003')
        self.assertEqual(second_application['ID_CARD_DISTRICT_CODE'], '04')
        self.assertEqual(second_application['NUMBER_OF_DEPENDENTS'], '0')

        self.assertIsInstance(contracts, list)
        self.assertEqual(len(contracts), 2)
        first_contract = contracts[0]
        # check some fields in contract
        self.assertEqual(first_contract['CONTRACT_CODE'], 'JUL001234567890')
        self.assertEqual(first_contract['BANK_PRINCIPAL'], str(self.loan.loan_amount))
        self.assertEqual(first_contract['BANK_TENOR'], str(self.loan.loan_duration))
        self.assertEqual(
            first_contract['REMAINING CREDIT LIMIT'],
            str(self.account_limit.available_limit),
        )
        self.assertEqual(first_contract['CREDIT LIMIT'], str(self.account_limit.set_limit))
        self.assertEqual(
            first_contract['LAST_DUE_DATE'],
            self.loan.payment_set.last().due_date.strftime('%d-%m-%Y'),
        )

        self.assertIsInstance(goods_info, list)
        self.assertEqual(len(goods_info), 2)
        first_goods_info = goods_info[0]
        # check all fields in goods info
        self.assertEqual(first_goods_info['CONTRACT_CODE'], 'JUL001234567890')
        self.assertEqual(first_goods_info['COMMODITY_CATEGORY_CODE'], 'Cashloan')
        self.assertEqual(first_goods_info['PRODUCER'], 'Cashloan')
        self.assertEqual(first_goods_info['CODE'], '1')
        self.assertEqual(first_goods_info['TYPE_PF_GOODS'], 'JULO')
        self.assertEqual(first_goods_info['TYPE_OF_GOODS'], 'JUL Cash Loan')
        self.assertEqual(first_goods_info['PRICE_AMOUNT'], str(self.loan.loan_amount))
        # check loan sequence number for second loan
        self.assertEqual(goods_info[1]['CODE'], '2')

        self.assertIsInstance(installments, list)
        self.assertEqual(
            len(installments), self.loan.payment_set.count() + loan2.payment_set.count()
        )

    @patch('juloserver.channeling_loan.services.dbs_services.sentry_client')
    def test_map_list_disbursement_documents_data_with_error(self, mock_sentry_client):
        # Setup another loan with some missing data (loan_xid, sphp_accepted_ts,...)
        loan3 = LoanFactory()
        channeling_loan_status3 = ChannelingLoanStatusFactory(
            loan=loan3,
            channeling_type=ChannelingConst.DBS,
            channeling_status=ChannelingStatusConst.PENDING,
        )

        result = self.service.map_list_disbursement_documents_data(
            channeling_loan_statuses=[self.channeling_loan_status, channeling_loan_status3]
        )

        (
            success_statuses,
            failed_statuses,
            failed_errors,
            applications,
            contracts,
            goods_info,
            installments,
        ) = result

        self.assertEqual(len(success_statuses), 1)
        self.assertEqual(
            success_statuses[0], self.channeling_loan_status.id
        )  # only loan1 is success

        self.assertEqual(len(failed_statuses), 1)
        self.assertEqual(failed_statuses[0], channeling_loan_status3.id)  # loan3 is fail
        self.assertEqual(len(failed_errors), 1)

        self.assertEqual(len(applications), 1)
        self.assertEqual(applications[0]['LOAN_TENOR'], str(self.loan.loan_duration))

        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0]['CONTRACT_CODE'], 'JUL001234567890')

        self.assertEqual(len(goods_info), 1)
        self.assertEqual(goods_info[0]['CONTRACT_CODE'], 'JUL001234567890')

        self.assertEqual(len(installments), self.loan.payment_set.count())
        self.assertEqual(installments[0]['CONTRACT_NUMBER'], 'JUL001234567890  ')

        # only log, no Sentry exception when mapping error
        mock_sentry_client.captureException.assert_not_called()

    def test_construct_document_content(self):
        rows = [{'col1': '123 ', 'col2': '234'}, {'col1': '345', 'col2': '   456'}]
        headers = ['col1', 'col2']

        result = self.service._DBSDisbursementDocumentServices__construct_document_content(  # noqa
            rows=rows,
            headers=headers,
            separator='|',
        )
        self.assertEqual(result, "col1|col2\n123 |234\n345|   456")

    def test_construct_installment_list_content(self):
        rows = [
            {
                'RECORD_INDICATOR': 'D',
                'CONTRACT_NUMBER': 'JUL000081592556  ',
                'DUE_DATE': '16-03-2025',
                'INSTALLMENT_NUMBER': '002',
                'PRINCIPAL_AMOUNT': '00000000000054566',
                'INTEREST_AMOUNT': '0000000000000314',
                'INSTALLMENT_AMOUNT': '000000000000057706',
                'FILTER': 'filter',
            }
        ]

        result = (
            self.service._DBSDisbursementDocumentServices__construct_loan_installment_list_content(
                rows=rows,
            )
        )
        expected_result = """H{}
DJUL000081592556  16-03-2025002000000000000545660000000000000314000000000000057706filter
T0000000001""".format(
            self.service.current_ts.strftime("%d-%m-%Y")
        )
        self.assertEqual(result, expected_result)

    def test_construct_disbursement_document_files(self):
        (
            success_statuses,
            failed_statuses,
            failed_errors,
            files,
        ) = self.service.construct_disbursement_document_files(
            channeling_loan_statuses=[self.channeling_loan_status]
        )

        # Assert
        self.assertIsInstance(success_statuses, list)
        self.assertEqual(len(success_statuses), 1)
        self.assertIsInstance(failed_statuses, list)
        self.assertEqual(len(failed_statuses), 0)
        self.assertIsInstance(failed_errors, dict)
        self.assertEqual(len(failed_errors), 0)
        self.assertIsInstance(files, dict)
        self.assertIn(DBSDisbursementDocumentConst.APPLICATION_FILENAME_FORMAT, files)
        self.assertIn(DBSDisbursementDocumentConst.CONTRACT_FILENAME_FORMAT, files)
        self.assertIn(DBSDisbursementDocumentConst.GOODS_INFO_FILENAME_FORMAT, files)
        self.assertIn(DBSDisbursementDocumentConst.LOAN_INSTALLMENT_LIST_FILENAME_FORMAT, files)
        for content in files.values():
            self.assertIsInstance(content, str)
            self.assertTrue(content)

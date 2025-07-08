from builtins import str
from builtins import range
from builtins import object
import logging
import xlrd
import re
import csv
from dateutil import parser

from django.conf import settings
from django import template
from rest_framework.response import Response

from juloserver.julo.exceptions import JuloException
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.models import Payment, PaymentEvent, PaybackTransaction
from datetime import datetime

from .constants import RepaymentParseConst


logger = logging.getLogger(__name__)
register = template.Library()


class LoggedResponse(Response):
    def __init__(self, **kwargs):
        super(LoggedResponse, self).__init__(**kwargs)
        kwargs['http_status_code'] = self.status_code
        logger.info(kwargs)


class BcaStatementFaspayParser(object):
    def parse(self, file):
        parse_result = []
        self.check_file(file)
        va = None
        paid_date = None
        paid_amount = None

        for line in file.split('\n'):
            list_word = re.split(r'\s', line)
            for word in list_word:
                if word.startswith('08'):
                    va = '18888' + word

                if '.00' in word:
                    paid_amount = word[:-3]
                    paid_amount = paid_amount.replace(',', '')
                    paid_amount = int(paid_amount)

                match_date = re.search(r'\d{2}/\d{2}/\d{2}', word)
                if match_date:
                    paid_date = str(match_date.group())
                    paid_date = parser.parse(paid_date).date()

            if va and paid_date and paid_amount:
                payback_transactions = PaybackTransaction.objects.filter(
                    virtual_account=va,
                    cdate__date=paid_date,
                    amount=paid_amount,
                    is_processed=True
                ).order_by('payment_id').values_list('id', flat=True)

                list_temp_payback_ids = []

                if payback_transactions.count() > 1:
                    for payback_id in payback_transactions:
                        if payback_id in list_temp_payback_ids:
                            continue
                        list_payment_event_ids = get_list_payment_event_ids(payback_id)
                        parse_result.extend(list_payment_event_ids)
                        list_temp_payback_ids.append(payback_id)
                        break

                elif payback_transactions.count() == 1:
                    payback_id = payback_transactions[0]
                    list_payment_event_ids = get_list_payment_event_ids(payback_id)
                    parse_result.extend(list_payment_event_ids)

        return parse_result

    def check_file(self, file):
        bca_bank_code = re.search("(18888-)", file)

        if bca_bank_code is None:
            raise JuloException('Incorrect file uploaded')


class BcaStatementDirectSettlementParser(object):
    def parse(self, file):
        parse_result = []
        self.check_file(file)
        va = None
        paid_date = None
        paid_amount = None

        for line in file.split('\n'):
            list_word = re.split(r'\s', line)
            for word in list_word:
                if word.startswith('08'):
                    va = settings.PREFIX_BCA + word

                if '.00' in word:
                    paid_amount = word[:-3]
                    paid_amount = paid_amount.replace(',', '')
                    paid_amount = int(paid_amount)

                match_date = re.search(r'\d{2}/\d{2}/\d{2}', word)
                if match_date:
                    paid_date = str(match_date.group())
                    paid_date = parser.parse(paid_date).date()

            if va and paid_date and paid_amount:
                payback_transactions = PaybackTransaction.objects.filter(
                    virtual_account=va,
                    cdate__date=paid_date,
                    amount=paid_amount,
                    is_processed=True
                ).order_by('payment_id').values_list('id', flat=True)

                list_temp_payback_ids = []

                if payback_transactions.count() > 1:
                    for payback_id in payback_transactions:
                        if payback_id in list_temp_payback_ids:
                            continue
                        list_payment_event_ids = get_list_payment_event_ids(payback_id)
                        parse_result.extend(list_payment_event_ids)
                        list_temp_payback_ids.append(payback_id)
                        break

                elif payback_transactions.count() == 1:
                    payback_id = payback_transactions[0]
                    list_payment_event_ids = get_list_payment_event_ids(payback_id)
                    parse_result.extend(list_payment_event_ids)

        return parse_result

    def check_file(self, file):
        bca_bank_code = re.search("(10994-)", file)

        if bca_bank_code is None:
            raise JuloException('Incorrect file uploaded')


class FaspayStatementParser(object):
    def parse(self, file):
        parse_result = []
        book = xlrd.open_workbook(file_contents=file)
        self.check_file(book)
        transaction_id_col = 4

        for sheet_name in book.sheet_names():
            if 'detail' == sheet_name.lower():
                curr_sheet = book.sheet_by_name(sheet_name)
                for row_idx in range(5, curr_sheet.nrows):
                    transaction_id = curr_sheet.cell(row_idx, transaction_id_col).value

                    if transaction_id:
                        payback_transaction = PaybackTransaction.objects.filter(
                            transaction_id=transaction_id,
                            is_processed=True
                        ).last()

                        if payback_transaction:
                            payment_id = payback_transaction.payment_id

                            list_payment_event_ids = PaymentEvent.objects.filter(
                                payment_id=payment_id,
                                payment_receipt=transaction_id
                            ).values_list('id', flat=True)

                            parse_result.extend(list_payment_event_ids)

        return parse_result

    def check_file(self, book):
        if 'Detail' not in book.sheet_names():
            raise JuloException('Incorrect file uploaded')


class MidtransSettlementParser(object):
    def parse(self, file):
        parse_result = []
        csv_reader = csv.DictReader(file.decode().splitlines(), delimiter=',')

        self.check_file(file)

        for row in csv_reader:
            if 'failure' in row['Transaction status']:
                continue

            transaction_id = row['Transaction ID']

            transaction_id = str(transaction_id)
            payback_transaction = PaybackTransaction.objects.filter(
                transaction_id=transaction_id,
                is_processed=True).last()

            if payback_transaction:
                payment_id = payback_transaction.payment_id
                list_payment_event_ids = PaymentEvent.objects.filter(
                    payment_id=payment_id,
                    payment_receipt=transaction_id
                ).values_list('id', flat=True)
                parse_result.extend(list_payment_event_ids)

        return parse_result

    def check_file(self, file):
        csv_reader = csv.DictReader(file.decode().splitlines(), delimiter=',')
        for row in csv_reader:
            if "GO-PAY" not in row['Payment Type']:
                raise JuloException('Incorrect file uploaded')


class PermataSettlementParser(object):
    def parse(self, file):
        parse_result = []
        book = xlrd.open_workbook(file_contents=file)
        start_row = 3
        va_col = 8
        transaction_date_col = 0
        paid_amount_col = 5
        va_number = None
        transaction_date = None
        paid_amount = None

        for sheet_name in book.sheet_names():
            curr_sheet = book.sheet_by_name(sheet_name)
            for row_idx in range(start_row, curr_sheet.nrows):
                paid_amount = curr_sheet.cell(row_idx, paid_amount_col).value
                paid_amount = int(paid_amount)
                if paid_amount == 0:
                    continue

                description = curr_sheet.cell(row_idx, va_col).value
                va_number = re.search("([0-9]{9,})", description)
                transaction_date_value = curr_sheet.cell(row_idx, transaction_date_col)
                transaction_date = read_date_in_xlrd_for_permata_and_bri(transaction_date_value, book)

                if va_number and transaction_date and paid_amount:
                    payback_transactions = PaybackTransaction.objects.filter(
                        virtual_account=va_number.group(0),
                        cdate__date=transaction_date,
                        amount=paid_amount
                    ).order_by('payment_id').values_list('id', flat=True)

                    list_temp_payback_ids = []

                    if payback_transactions.count() > 1:
                        for payback_id in payback_transactions:
                            if payback_id in list_temp_payback_ids:
                                continue

                            list_payment_event_ids = get_list_payment_event_ids(payback_id)
                            parse_result.extend(list_payment_event_ids)
                            list_temp_payback_ids.append(payback_id)
                            break

                    elif payback_transactions.count() == 1:
                        payback_id = payback_transactions[0]
                        list_payment_event_ids = get_list_payment_event_ids(payback_id)
                        parse_result.extend(list_payment_event_ids)

        return parse_result


class BriSettlementParser(object):
    def parse(self, file):
        parse_result = []
        book = xlrd.open_workbook(file_contents=file)
        start_row = 19

        transaction_date_col = 0
        va_col = 5
        paid_amount_col = 15
        va_number = None
        transaction_date = None
        paid_amount = None

        for sheet_name in book.sheet_names():
            curr_sheet = book.sheet_by_name(sheet_name)
            for row_idx in range(start_row, curr_sheet.nrows):
                paid_amount_val = str(curr_sheet.cell(row_idx, paid_amount_col).value)
                if paid_amount_val == '0.0':
                    continue
                if paid_amount_val:
                    paid_amount_val = paid_amount_val[:-2]
                    paid_amount_val = paid_amount_val.replace(',', '')
                    paid_amount = int(paid_amount_val)

                va_number_val = curr_sheet.cell(row_idx, va_col).value
                if va_number_val:
                    va_number_match = re.search("([0-9]{9,})", str(va_number_val))
                    if va_number_match:
                        va_number = va_number_match.group(0)

                transaction_date_value = curr_sheet.cell(row_idx, transaction_date_col)
                transaction_date = read_date_in_xlrd_for_permata_and_bri(transaction_date_value, book)

                if va_number and transaction_date and paid_amount:
                    payback_transactions = PaybackTransaction.objects.filter(
                        virtual_account=va_number,
                        cdate__date=transaction_date,
                        amount=paid_amount
                    ).order_by('payment_id').values_list('id', flat=True)

                    list_temp_payback_ids = []

                    if payback_transactions.count() > 1:
                        for payback_id in payback_transactions:
                            if payback_id in list_temp_payback_ids:
                                continue
                            list_payment_event_ids = get_list_payment_event_ids(payback_id)
                            parse_result.extend(list_payment_event_ids)
                            list_temp_payback_ids.append(payback_id)
                            break

                    elif payback_transactions.count() == 1:
                        payback_id = payback_transactions[0]
                        list_payment_event_ids = get_list_payment_event_ids(payback_id)
                        parse_result.extend(list_payment_event_ids)

        return parse_result


class IcareSettlementParser(object):
    def parse(self, file):
        parse_result = []
        book = xlrd.open_workbook(file_contents=file)
        start_row = 1
        application_xid_col = 0
        payment_number_col = 5
        paid_amount_col = 7
        application_xid = None
        payment_number = None

        for sheet_name in book.sheet_names():
            curr_sheet = book.sheet_by_name(sheet_name)
            header = curr_sheet.cell(0, 0).value
            if 'application_xid' not in header.lower():
                continue
            for row_idx in range(start_row, curr_sheet.nrows):
                paid_amount = curr_sheet.cell(row_idx, paid_amount_col).value
                if paid_amount:
                    paid_amount = paid_amount.replace(',', '')
                    paid_amount = int(paid_amount)
                if paid_amount == 0:
                    continue

                application_xid_val = curr_sheet.cell(row_idx, application_xid_col).value
                if application_xid_val:
                    application_xid = int(application_xid_val)
                payment_number_val = curr_sheet.cell(row_idx, payment_number_col).value
                if payment_number_val:
                    payment_number = int(payment_number_val)

                if application_xid and payment_number:
                    payment = Payment.objects.filter(
                        loan__application__partner__name=PartnerConstant.ICARE_PARTNER,
                        loan__application__application_xid=application_xid,
                        payment_number=payment_number).last()

                    list_payment_event_ids = PaymentEvent.objects.filter(
                        payment=payment
                    ).values_list('id', flat=True)

                    parse_result.extend(list_payment_event_ids)

        return parse_result


class AxiataSettlementParser(object):
    def parse(self, file):
        parse_result = []
        book = xlrd.open_workbook(file_contents=file)
        start_row = 1
        application_xid_col = 0
        paid_amount_col = 5
        due_date_col = 6
        repayment_date_col = 7
        application_xid = None
        due_date = None

        for sheet_name in book.sheet_names():
            curr_sheet = book.sheet_by_name(sheet_name)
            header = curr_sheet.cell(0, 0).value
            if 'application_xid' not in header.lower():
                continue

            for row_idx in range(start_row, curr_sheet.nrows):
                application_xid_val = curr_sheet.cell(row_idx, application_xid_col).value
                due_date_val = curr_sheet.cell(row_idx, due_date_col)
                due_date = read_date_in_xlrd_file_for_axiata(due_date_val, book)
                repayment_date_val = curr_sheet.cell(row_idx, repayment_date_col)
                repayment_date = read_date_in_xlrd_file(repayment_date_val, book)
                paid_amount_val = curr_sheet.cell(row_idx, paid_amount_col).value
                if paid_amount_val:
                    paid_amount = int(paid_amount_val)
                if application_xid_val:
                    application_xid = int(application_xid_val)

                if application_xid and due_date:
                    payment = Payment.objects.filter(
                        loan__application__partner__name=PartnerConstant.AXIATA_PARTNER,
                        loan__application__application_xid=application_xid,
                        due_date=due_date).last()

                    list_payment_event_ids = PaymentEvent.objects.filter(
                        payment=payment,
                        cdate__date=repayment_date,
                        event_payment=paid_amount
                    ).values_list('id', flat=True)

                    list_void_transaction = get_void_transaction(payment, paid_amount)

                    parse_result.extend(list_payment_event_ids)
                    parse_result.extend(list_void_transaction)

        return parse_result


class StatementParserFactory(object):
    def get_parser(self, parser_type):
        if parser_type == RepaymentParseConst.BCA_10994:
            return BcaStatementDirectSettlementParser()
        elif parser_type == RepaymentParseConst.BCA_18888:
            return BcaStatementFaspayParser()
        elif parser_type == RepaymentParseConst.FASPAY_31932:
            return FaspayStatementParser()
        elif parser_type == RepaymentParseConst.FASPAY_32401:
            return FaspayStatementParser()
        elif parser_type == RepaymentParseConst.MIDTRANS:
            return MidtransSettlementParser()
        elif parser_type == RepaymentParseConst.PERMATA:
            return PermataSettlementParser()
        elif parser_type == RepaymentParseConst.BRI:
            return BriSettlementParser()
        elif parser_type == RepaymentParseConst.ICARE:
            return IcareSettlementParser()
        elif parser_type == RepaymentParseConst.AXIATA:
            return AxiataSettlementParser()


def transform_mintos_upload_key(data):
    data = {k.replace(' ', '_'): v for k, v in list(data.items())}
    data = {k.replace('.', ''): v for k, v in list(data.items())}
    data = {k.replace(',', ''): v for k, v in list(data.items())}
    data = {k.replace('%', 'in_percent'): v for k, v in list(data.items())}
    data = {k.replace('_-_', '_'): v for k, v in list(data.items())}
    return data


def get_list_payment_event_ids(payback_id):
    payback = PaybackTransaction.objects.get(pk=payback_id)
    payment_method_id = payback.payment_method_id
    payment_id = payback.payment_id
    event_due_amount = payback.amount
    return PaymentEvent.objects.filter(
        event_due_amount=event_due_amount,
        payment_id=payment_id,
        payment_method_id=payment_method_id
    ).values_list('id', flat=True)


def read_date_in_xlrd_file(cell_value, book):

    if cell_value.ctype is xlrd.XL_CELL_DATE:

        date_value = (float(cell_value.value) - 25569) * 86400
        datetime_str = datetime.fromtimestamp(date_value).strftime('%Y/%m/%d %H:%M:%S')
        return datetime.strptime(datetime_str, '%Y/%m/%d %H:%M:%S').date()


def read_date_in_xlrd_file_for_axiata(cell_value, book):
    # 3 means 'xldate'
    if cell_value.ctype == 3:
        year, month, day, hour, minute, second = xlrd.xldate_as_tuple(float(cell_value.value), book.datemode)
        datetime_value = datetime(year, month, day, hour, minute, second)
        return datetime_value.date()


def read_date_in_xlrd_for_permata_and_bri(cell_value, book):

    if cell_value.ctype is xlrd.XL_CELL_DATE:

        date_value = (float(cell_value.value) - 25569) * 86400
        datetime_str = datetime.fromtimestamp(date_value).strftime('%Y/%m/%d %H:%M:%S')
        return datetime.strptime(datetime_str, '%Y/%d/%m %H:%M:%S').date()


def get_void_transaction(payment, event_amount):
    return PaymentEvent.objects.filter(
        payment=payment,
        event_payment=-event_amount
    ).values_list('id', flat=True)

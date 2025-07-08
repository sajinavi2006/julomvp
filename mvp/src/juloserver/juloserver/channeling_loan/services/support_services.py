import io
import time
import logging
from typing import List, Tuple

from django.conf import settings
from django.db.models import Q
from bulk_update.helper import bulk_update

from juloserver.channeling_loan.clients import get_fama_sftp_client
from juloserver.channeling_loan.constants import (
    ChannelingConst,
    MartialStatusConst,
    FAMAChannelingConst,
    ChannelingActionTypeConst,
    ChannelingStatusConst,
)
from juloserver.channeling_loan.constants.fama_constant import FAMADPDRejectionStatusEligibility
from juloserver.channeling_loan.models import (
    ChannelingLoanAddress,
    ChannelingLoanStatus,
    ChannelingLoanApprovalFile,
    ChannelingEligibilityStatus,
)
from juloserver.channeling_loan.services.general_services import (
    SFTPProcess,
    decrypt_data,
    mark_approval_file_processed,
    convert_fama_approval_content_from_txt_to_csv,
    upload_approval_file_to_oss_and_create_document,
    approve_loan_for_channeling,
)
from juloserver.channeling_loan.utils import replace_gpg_encrypted_file_name

from juloserver.julo.models import Application, Document, Loan
from juloserver.apiv3.models import (
    SubDistrictLookup,
    DistrictLookup,
    CityLookup,
)
from juloserver.julo.utils import get_file_from_oss

from juloserver.portal.object.bulk_upload.constants import GENDER

from datetime import datetime

from juloserver.sdk.services import xls_to_dict

logger = logging.getLogger(__name__)


def retroload_address(
        first_application_id=None, limit=None, batch_size=25, query_filter=None, key="BSS"):
    version = "%s-%s" % (key, str(time.time()).replace('.', ''))
    channeling_loan_address_list = []
    application_ids = {"start": first_application_id, "end": ""}
    result = {"200": 0, "404": 0, "400": 0}
    if not query_filter:
        query_filter = {"bss_eligible": True, "cdate__lte": ChannelingConst.DEFAULT_TIMESTAMP}
        if first_application_id:
            query_filter["id__gte"] = first_application_id
    query_filter["channelingloanaddress__isnull"] = True

    applications = Application.objects.filter(**query_filter)\
        .exclude(Q(address_kelurahan__exact='') | Q(address_kelurahan__isnull=True))\
        .order_by('id')\
        .values(
        "id", 'address_provinsi', 'address_kabupaten',
        'address_kecamatan', 'address_kelurahan', 'address_kodepos'
    )
    if not applications:
        return {}, []

    sub_districts = {}
    base_sub_districts = SubDistrictLookup.objects.filter(
        is_active=True
    ).values('id', 'sub_district', 'district__district', 'district', 'zipcode')
    for base_sub_district in base_sub_districts:
        sub_districts.setdefault(base_sub_district["sub_district"], []).append(base_sub_district)

    districts = {}
    base_districts = DistrictLookup.objects.filter(is_active=True).values('id', 'district', 'city')
    for base_district in base_districts:
        districts.setdefault(base_district["id"], []).append(base_district)

    cities = {}
    base_cities = CityLookup.objects.filter(is_active=True).values(
        'id', 'city', 'province__province'
    )
    for base_city in base_cities:
        cities.setdefault(base_city["id"], []).append(base_city)

    def _update_application(application, related_sub_district):
        district_id = related_sub_district['district']
        if not districts.get(district_id):
            result["400"] += 1
            logger.info({
                "state": "[400] district",
                "application": application,
                "district_id": district_id
            })
            return {}, []

        district = districts[district_id][0]
        city_id = district['city']
        if not cities.get(city_id):
            result["400"] += 1
            logger.info({
                "state": "[400] city",
                "application": application,
                "city_id": city_id
            })
            return {}, []

        city = cities[city_id][0]
        db_application = Application.objects.get_or_none(id=application["application_id"])
        if not db_application:
            result["400"] += 1
            logger.info({
                "state": "[400] application",
                "application": application
            })
            return {}, []

        result["200"] += 1
        application['version'] = version
        channeling_loan_address_list.append(ChannelingLoanAddress(**application))
        db_application.update_safely(
            address_provinsi=city['province__province'],
            address_kabupaten=city['city'],
            address_kecamatan=related_sub_district['district__district'],
            address_kelurahan=related_sub_district['sub_district'],
            address_kodepos=related_sub_district['zipcode'],
        )
        return {}, []

    applications = applications[:limit] if limit else applications
    application_ids["start"] = applications[0]["id"]
    for application in applications:
        application["application_id"] = application.pop("id")
        sub_district = application['address_kelurahan'].strip().title()
        district = application['address_kecamatan'].strip().title()
        if not sub_districts.get(sub_district):
            result["404"] += 1
            continue
        if len(sub_districts[sub_district]) == 1:
            related_sub_district = sub_districts[sub_district][0]
            _update_application(application, related_sub_district)
            continue
        ever_success = False
        for related_sub_district in sub_districts[sub_district]:
            if application['address_kodepos'] == related_sub_district['zipcode'] or\
                    district == related_sub_district['district__district']:
                _update_application(application, related_sub_district)
                ever_success = True
                break
        if not ever_success:
            result["400"] += 1
            logger.info({
                "state": "[400] sub_district",
                "application": application,
                "sub_district": sub_districts[sub_district]
            })
    application_ids["end"] = application["application_id"]
    ChannelingLoanAddress.objects.bulk_create(channeling_loan_address_list, batch_size)
    return result, application_ids


def update_application_marital_spouse_name_by_channeling_loan_status_cdate(startdate, enddate):
    if not startdate and not enddate:
        startdate = datetime.now()
        enddate = datetime.now()

    channeling_loan_statuses = ChannelingLoanStatus.objects.filter(
        channeling_type=ChannelingConst.FAMA,
        cdate__date__range=[startdate, enddate],
    )

    application_bulk_update = []
    application_ids = []
    for channeling_loan_status in channeling_loan_statuses:
        loan = channeling_loan_status.loan
        application = loan.get_application
        if application.id in application_ids:
            continue

        if application.marital_status == MartialStatusConst.MENIKAH and not application.spouse_name:
            application.spouse_name = 'Lorem Ipsum'

        application_bulk_update.append(application)

    if application_bulk_update:
        bulk_update(application_bulk_update, update_fields=['spouse_name'])


def update_application_dob_by_channeling_loan_status_cdate(startdate, enddate):
    if not startdate and not enddate:
        startdate = datetime.now()
        enddate = datetime.now()

    channeling_loan_statuses = ChannelingLoanStatus.objects.filter(
        channeling_type=ChannelingConst.FAMA,
        cdate__date__range=[startdate, enddate],
    )

    application_bulk_update = []
    application_ids = []
    for channeling_loan_status in channeling_loan_statuses:
        loan = channeling_loan_status.loan
        application = loan.get_application
        if application.id in application_ids:
            continue

        application.ktp = set_nik(application.ktp, application.dob, application.gender)
        application_bulk_update.append(application)

    if application_bulk_update:
        bulk_update(application_bulk_update, update_fields=['ktp'])


def set_nik(ktp, dob, gender):
    if not ktp:
        return

    if gender == GENDER['female']:
        date = str(int(dob.strftime("%d")) + 40) + dob.strftime("%m%y")
        print(dob.strftime("%d"))
    else:
        date = str(dob.strftime("%d%m%y"))

    return date.join([ktp[:6], ktp[12:]])


class FAMAApprovalFileServices:
    channeling_type = ChannelingConst.FAMA

    @staticmethod
    def get_multi_fama_approval_filename_from_sftp_server(
        file_type: str = ChannelingActionTypeConst.DISBURSEMENT,
        number_of_latest_file: int = 3,
    ) -> List[str]:
        """
        Get the latest file by getting the latest file in the approval folder.
        The number of files can be increased day by day, but we can't rely on a specific day,
        so let's try with this approach first.
        :return: filenames
        """
        sftp_service = SFTPProcess(sftp_client=get_fama_sftp_client())

        # approval directory contains only files, no need to check any child directories
        remote_path = FAMAChannelingConst.FILE_TYPE.get(file_type)
        filenames = sftp_service.list_dir(remote_dir_path=remote_path)
        if not filenames:
            return []

        # filename has format JUL_Confirmation_file_type_%Y%m%d%H%M%S%f.txt.gpg and
        # list filenames already be sorted in Connection.listdir,
        # so we can get some latest filenames by get some last elements of the list
        return filenames[-number_of_latest_file:]

    def download_multi_fama_approval_file_from_sftp_server(
        self,
        file_type: str,
        number_of_latest_file: int,
    ) -> List[Tuple[str, bytes]]:
        """
        :return: filename and content of the latest FAMA approval file
        """
        sftp_service = SFTPProcess(sftp_client=get_fama_sftp_client())
        filenames = self.get_multi_fama_approval_filename_from_sftp_server(
            file_type=file_type, number_of_latest_file=number_of_latest_file
        )

        result = []
        for filename in filenames:
            result.append(
                (
                    filename,
                    sftp_service.download(
                        remote_path='{}/{}'.format(
                            FAMAChannelingConst.FILE_TYPE.get(file_type),
                            filename,
                        )
                    ),
                )
            )
        return result

    def process_multi_fama_disbursement_approval_file(
        self, number_of_latest_file: int
    ) -> Tuple[List[int], List[str]]:
        file_type = ChannelingActionTypeConst.DISBURSEMENT
        document_ids, processed_encrypted_filenames = [], []

        result = self.download_multi_fama_approval_file_from_sftp_server(
            file_type=file_type, number_of_latest_file=number_of_latest_file
        )
        for encrypted_filename, encrypted_data in result:
            approval_file = ChannelingLoanApprovalFile.objects.create(
                channeling_type=self.channeling_type, file_type=file_type
            )
            approval_file_id = approval_file.id

            txt_content = decrypt_data(
                filename=encrypted_filename,
                content=encrypted_data,
                passphrase=settings.FAMA_GPG_DECRYPT_PASSPHRASE,
                gpg_recipient=settings.FAMA_GPG_DECRYPT_RECIPIENT,
                gpg_key_data=settings.FAMA_GPG_DECRYPT_KEY_DATA,
            )
            # check if decryption failed
            if txt_content is None:
                mark_approval_file_processed(approval_file_id=approval_file_id)
                continue

            filename = replace_gpg_encrypted_file_name(
                encrypted_file_name=encrypted_filename, new_file_extension='csv'
            )
            content = convert_fama_approval_content_from_txt_to_csv(content=txt_content)

            document_id = upload_approval_file_to_oss_and_create_document(
                channeling_type=ChannelingConst.FAMA,
                file_type=file_type,
                filename=filename,
                approval_file_id=approval_file_id,
                content=content,
            )

            mark_approval_file_processed(approval_file_id=approval_file_id, document_id=document_id)
            print(encrypted_filename)
            document_ids.append(document_id)
            processed_encrypted_filenames.append(encrypted_filename)

        return document_ids, processed_encrypted_filenames

    def sync_fama_disbursement_channeling_loan_status(self, document_id: int):
        document = Document.objects.get_or_none(id=document_id)
        if not document:
            raise Exception("Document not found")

        document_stream = get_file_from_oss(
            bucket_name=settings.OSS_MEDIA_BUCKET, remote_filepath=document.url
        )

        try:
            excel_datas = xls_to_dict(file_excel=io.BytesIO(document_stream.read()))
        except Exception as error:
            raise error

        total = 0
        loan_ids = []
        nok_loan_ids = []
        ok_loan_ids = []
        existing_loan_ids = []
        approved_loan_ids = []
        rejected_loan_ids = []

        for idx_sheet, sheet in enumerate(excel_datas):
            total = len(excel_datas[sheet])
            for idx_rpw, row in enumerate(excel_datas[sheet]):
                header_key = 'application_xid'

                loan_xid = row[header_key]
                loan = Loan.objects.get_or_none(loan_xid=loan_xid)
                if not loan:
                    nok_loan_ids.append(loan_xid)  # add loan_xid instead of loan_id
                    print("Error: Loan_xid %s not found\n" % str(row[header_key]))
                    continue

                loan_id = loan.id
                if loan_id not in loan_ids:
                    loan_ids.append(loan_id)
                else:
                    existing_loan_ids.append(loan_id)
                    print("Error: Loan_xid %s already exists\n" % str(row[header_key]))

                reason = row.get("reason", "")
                status, message = approve_loan_for_channeling(
                    loan, row['disetujui'], self.channeling_type, reason=reason
                )
                if status == "failed":
                    print(
                        document_id,
                        "Error: Loan_xid=%s, status=%s detail=%s\n"
                        % (str(row[header_key]), str(row['disetujui']), str(message)),
                    )
                    channeling_loan_status = ChannelingLoanStatus.objects.filter(
                        loan=loan, channeling_type=ChannelingConst.FAMA
                    ).last()
                    eligibility_status = ChannelingEligibilityStatus.objects.filter(
                        application=loan.get_application, channeling_type=ChannelingConst.FAMA
                    ).last()
                    if (
                        eligibility_status
                        and eligibility_status.eligibility_status
                        == ChannelingStatusConst.INELIGIBLE
                        and FAMADPDRejectionStatusEligibility.dpd
                        in eligibility_status.reason.lower()
                    ):
                        from juloserver.channeling_loan.services.general_services import (
                            update_channeling_loan_status,
                        )

                        update_channeling_loan_status(
                            channeling_loan_status_id=channeling_loan_status.id,
                            new_status=ChannelingStatusConst.FAILED,
                            change_reason=reason,
                        )
                    else:
                        nok_loan_ids.append(loan_id)
                        continue

                ok_loan_ids.append(loan_id)

                if row['disetujui'] == 'n':
                    rejected_loan_ids.append(loan_id)
                else:
                    approved_loan_ids.append(loan_id)

        return {
            'document_id': document_id,
            'filename': document.filename,
            'total': total,
            'existing_loan_ids': existing_loan_ids,
            'nok_loan_ids': nok_loan_ids,
            'ok_loan_ids': ok_loan_ids,
            'loan_ids': loan_ids,
            'approved_loan_ids': approved_loan_ids,
            'rejected_loan_ids': rejected_loan_ids,
        }

    def execute_upload_fama_disbursement_approval_files(self, number_of_latest_file: int = 3):
        """
        Before executing, please run `get_multi_fama_approval_filename_from_sftp_server` first
        to check whether the files are available and enough or not.

        How to run:
        - FAMAApprovalFileServices().get_multi_fama_approval_filename_from_sftp_server()
        - results = FAMAApprovalFileServices().execute_upload_fama_disbursement_approval_files()
        """
        (
            document_ids,
            processed_encrypted_filenames,
        ) = self.process_multi_fama_disbursement_approval_file(
            number_of_latest_file=number_of_latest_file
        )

        results = []
        results_msg = []
        for document_id in document_ids:
            results.append(
                self.sync_fama_disbursement_channeling_loan_status(document_id=document_id)
            )

        for result in results:
            results_msg_dict = dict()
            for key, value in result.items():
                if isinstance(value, (float, int, str)):
                    print(key, value)
                    results_msg_dict[key] = value
                else:
                    print(key, len(value))
                    results_msg_dict[key] = len(value)
            print()
            results_msg.append(results_msg_dict)

        total_success = sum(len(result['approved_loan_ids']) for result in results)
        total_reject = sum(len(result['rejected_loan_ids']) for result in results)
        total = total_success + total_reject
        success_rate = (total_success / total) * 100 if total > 0 else 0
        reject_rate = 100 - success_rate

        results_msg.append(
            {
                "total_success": total_success,
                "total_reject": total_reject,
                "success_rate": success_rate,
                "reject_rate": reject_rate,
            }
        )

        print("Approval rate: ")
        print(f"Total success: {total_success}")
        print(f"Total reject: {total_reject}")
        print(f"Success rate: {success_rate:.2f}%")
        print(f"Reject rate: {reject_rate:.2f}%")

        return results, results_msg, processed_encrypted_filenames

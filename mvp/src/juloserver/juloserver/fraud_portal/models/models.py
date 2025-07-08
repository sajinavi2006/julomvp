from typing import List

from juloserver.face_recognition.constants import FaceMatchingCheckConst


class SelfieMatchingResult:
    def __init__(
        self,
        is_feature_active: bool = False,
        is_agent_verified: bool = False,
        image_urls: List[str] = None,
        status: FaceMatchingCheckConst.Status = FaceMatchingCheckConst.Status.not_triggered,
    ):
        self.is_feature_active = is_feature_active
        self.is_agent_verified = is_agent_verified
        self.image_urls = image_urls
        self.status = status

    def to_dict(self):
        if not self.is_feature_active:
            return {
                "is_feature_active": self.is_feature_active,
            }

        return {
            "is_feature_active": self.is_feature_active,
            "is_agent_verified": self.is_agent_verified,
            "image_urls": self.image_urls,
            "status": self.status.value,
        }


class FaceMatchingResult:
    def __init__(
        self,
        application_id: int,
        application_full_name: str,
        selfie_image_urls: list,
        selfie_to_ktp: SelfieMatchingResult,
        selfie_to_liveness: SelfieMatchingResult,
    ):
        self.application_id = application_id
        self.application_full_name = application_full_name
        self.selfie_image_urls = selfie_image_urls
        self.selfie_to_ktp = selfie_to_ktp
        self.selfie_to_liveness = selfie_to_liveness

    def to_dict(self):
        return {
            "application_id": self.application_id,
            "application_full_name": self.application_full_name,
            "selfie_image_urls": self.selfie_image_urls,
            "selfie_to_ktp": self.selfie_to_ktp.to_dict(),
            "selfie_to_liveness": self.selfie_to_liveness.to_dict(),
        }


class FaceComparisonInfo:
    def __init__(self, application_id: int, matched_selfie: list, matched_ktp: list):
        self.application_id = application_id
        self.matched_selfie = matched_selfie
        self.matched_ktp = matched_ktp

    def to_dict(self):
        return {
            "application_id": self.application_id,
            "matched_selfie": self.matched_selfie,
            "matched_ktp": self.matched_ktp,
        }


class FaceSimilarityInfo:
    def __init__(
        self,
        application_id: int,
        application_full_name: str,
        selfie_image_urls: list,
        face_comparison: dict,
        face_comparison_by_geohash: list,
    ):
        self.application_id = application_id
        self.application_full_name = application_full_name
        self.selfie_image_urls = selfie_image_urls
        self.face_comparison = face_comparison
        self.face_comparison_by_geohash = face_comparison_by_geohash

    def to_dict(self):
        return {
            "application_id": self.application_id,
            "application_full_name": self.application_full_name,
            "selfie_image_urls": self.selfie_image_urls,
            "face_comparison": self.face_comparison,
            "face_comparison_by_geohash": self.face_comparison_by_geohash,
        }


class FraudApplicationInfo:
    def __init__(
        self,
        application_id: int,
        application_full_name: str,
        application_status_code: str,
        application_status: str,
        cdate: str,
        ktp: str,
        email: str,
        dob: str,
        birth_place: str,
        mobile_phone_1: str,
        marital_status: str,
        spouse_or_kin_mobile_phone: str,
        spouse_or_kin_name: str,
        address_detail: str,
        address_provinsi: str,
        address_kabupaten: str,
        address_kecamatan: str,
        address_kelurahan: str,
        bank_name: str,
        name_in_bank: str,
        bank_account_number: str,
        documents: list,
        other_documents: list,
        gender: str,
        range_upah: str,
        blth_upah: str,
        employment_status: str,
        bpjs_package: str,
        device_info_list: list,
    ):
        self.application_id = application_id
        self.application_full_name = application_full_name
        self.application_status_code = application_status_code
        self.application_status = application_status
        self.cdate = cdate
        self.ktp = ktp
        self.email = email
        self.dob = dob
        self.birth_place = birth_place
        self.mobile_phone_1 = mobile_phone_1
        self.marital_status = marital_status
        self.spouse_or_kin_mobile_phone = spouse_or_kin_mobile_phone
        self.spouse_or_kin_name = spouse_or_kin_name
        self.address_detail = address_detail
        self.address_provinsi = address_provinsi
        self.address_kabupaten = address_kabupaten
        self.address_kecamatan = address_kecamatan
        self.address_kelurahan = address_kelurahan
        self.bank_name = bank_name
        self.name_in_bank = name_in_bank
        self.bank_account_number = bank_account_number
        self.device_info_list = device_info_list
        self.documents = documents
        self.other_documents = other_documents
        self.gender = gender
        self.range_upah = range_upah
        self.blth_upah = blth_upah
        self.employment_status = employment_status
        self.bpjs_package = bpjs_package

    def to_dict(self):
        return {
            "application_id": self.application_id,
            "application_full_name": self.application_full_name,
            "application_status_code": self.application_status_code,
            "application_status": self.application_status,
            "cdate": self.cdate,
            "ktp": self.ktp,
            "email": self.email,
            "dob": self.dob,
            "birth_place": self.birth_place,
            "mobile_phone_1": self.mobile_phone_1,
            "marital_status": self.marital_status,
            "spouse_or_kin_mobile_phone": self.spouse_or_kin_mobile_phone,
            "spouse_or_kin_name": self.spouse_or_kin_name,
            "address_detail": self.address_detail,
            "address_provinsi": self.address_provinsi,
            "address_kabupaten": self.address_kabupaten,
            "address_kecamatan": self.address_kecamatan,
            "address_kelurahan": self.address_kelurahan,
            "bank_name": self.bank_name,
            "name_in_bank": self.name_in_bank,
            "bank_account_number": self.bank_account_number,
            "documents": self.documents,
            "other_documents": self.other_documents,
            "gender": self.gender,
            "range_upah": self.range_upah,
            "blth_upah": self.blth_upah,
            "employment_status": self.employment_status,
            "bpjs_package": self.bpjs_package,
            "device_info_list": self.device_info_list,
        }


class BPJSBrickInfo:
    def __init__(
        self,
        application_id: int = None,
        real_name: str = None,
        identity_number: str = None,
        birthday: str = None,
        birth_place: str = None,
        gender: str = None,
        status_sipil: str = None,
        address: str = None,
        provinsi: str = None,
        kabupaten: str = None,
        kecamatan: str = None,
        kelurahan: str = None,
        phone: str = None,
        email: str = None,
        total_balance: str = None,
        company_name: str = None,
        range_upah: str = None,
        current_salary: str = None,
        blth_upah: str = None,
        last_payment_date: str = None,
        employment_status: str = None,
        employment_month_duration: str = None,
        paket: str = None,
        bpjs_type: str = None,
        bpjs_cards: dict = None,
    ):
        self.application_id = application_id
        self.real_name = real_name
        self.identity_number = identity_number
        self.birthday = birthday
        self.birth_place = birth_place
        self.gender = gender
        self.status_sipil = status_sipil
        self.address = address
        self.provinsi = provinsi
        self.kabupaten = kabupaten
        self.kecamatan = kecamatan
        self.kelurahan = kelurahan
        self.phone = phone
        self.email = email
        self.total_balance = total_balance
        self.company_name = company_name
        self.range_upah = range_upah
        self.current_salary = current_salary
        self.blth_upah = blth_upah
        self.last_payment_date = last_payment_date
        self.employment_status = employment_status
        self.employment_month_duration = employment_month_duration
        self.paket = paket
        self.bpjs_type = bpjs_type
        self.bpjs_cards = bpjs_cards

    def to_dict(self):
        return {
            "application_id": self.application_id,
            "real_name": self.real_name,
            "identity_number": self.identity_number,
            "dob": self.birthday,
            "birth_place": self.birth_place,
            "gender": self.gender,
            "status_sipil": self.status_sipil,
            "address": self.address,
            "provinsi": self.provinsi,
            "kabupaten": self.kabupaten,
            "kecamatan": self.kecamatan,
            "kelurahan": self.kelurahan,
            "phone": self.phone,
            "email": self.email,
            "total_balance": self.total_balance,
            "company_name": self.company_name,
            "range_upah": self.range_upah,
            "current_salary": self.current_salary,
            "blth_upah": self.blth_upah,
            "last_payment_date": self.last_payment_date,
            "status_pekerjaan": self.employment_status,
            "employment_month_duration": self.employment_month_duration,
            "paket": self.paket,
            "bpjs_type": self.bpjs_type,
            "bpjs_cards": self.bpjs_cards,
        }


class DukcapilInfo:
    def __init__(
        self,
        application_id: int = None,
        name: bool = None,
        birthdate: bool = None,
        birthplace: bool = None,
        gender: bool = None,
        marital_status: bool = None,
        address_kabupaten: bool = None,
        address_kecamatan: bool = None,
        address_kelurahan: bool = None,
        address_provinsi: bool = None,
        address_street: bool = None,
        job_type: bool = None,
    ):
        self.application_id = application_id
        self.name = name
        self.birthdate = birthdate
        self.birthplace = birthplace
        self.gender = gender
        self.marital_status = marital_status
        self.address_kabupaten = address_kabupaten
        self.address_kecamatan = address_kecamatan
        self.address_kelurahan = address_kelurahan
        self.address_provinsi = address_provinsi
        self.address_street = address_street
        self.job_type = job_type

    def to_dict(self):
        return {
            "application_id": self.application_id,
            "name": self.name,
            "birthdate": self.birthdate,
            "birthplace": self.birthplace,
            "gender": self.gender,
            "marital_status": self.marital_status,
            "address_kabupaten": self.address_kabupaten,
            "address_kecamatan": self.address_kecamatan,
            "address_kelurahan": self.address_kelurahan,
            "address_provinsi": self.address_provinsi,
            "address_street": self.address_street,
            "job_type": self.job_type,
        }


class BPJSDirectInfo:
    def __init__(
        self,
        application_id: int = None,
        namaLengkap: str = None,
        nomorIdentitas: str = None,
        tglLahir: str = None,
        jenisKelamin: str = None,
        handphone: str = None,
        email: str = None,
        namaPerusahaan: str = None,
        paket: str = None,
        upahRange: str = None,
        blthUpah: str = None,
    ):
        self.application_id = application_id
        self.namaLengkap = namaLengkap
        self.nomorIdentitas = nomorIdentitas
        self.tglLahir = tglLahir
        self.jenisKelamin = jenisKelamin
        self.handphone = handphone
        self.email = email
        self.namaPerusahaan = namaPerusahaan
        self.paket = paket
        self.upahRange = upahRange
        self.blthUpah = blthUpah

    def to_dict(self):
        return {
            "application_id": self.application_id,
            "namaLengkap": self.namaLengkap,
            "nomorIdentitas": self.nomorIdentitas,
            "tglLahir": self.tglLahir,
            "jenisKelamin": self.jenisKelamin,
            "handphone": self.handphone,
            "email": self.email,
            "namaPerusahaan": self.namaPerusahaan,
            "paket": self.paket,
            "upahRange": self.upahRange,
            "blthUpah": self.blthUpah,
        }


class LoanInfo:
    def __init__(
        self,
        application_id: int,
        application_fullname: str,
        fpgw: str,
        fdc_data_history: bool,
        diabolical: str,
        loan_information: list,
    ):
        self.application_id = application_id
        self.application_fullname = application_fullname
        self.fpgw = fpgw
        self.fdc_data_history = fdc_data_history
        self.diabolical = diabolical
        self.loan_information = loan_information

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "application_fullname": self.application_fullname,
            "fpgw": self.fpgw,
            "fdc_data_history": self.fdc_data_history,
            "diabolical": self.diabolical,
            "loan_information": self.loan_information,
        }


class ConnectionAndDevice:
    def __init__(
        self,
        application_id: int,
        application_fullname: str,
        uninstalled: str,
        application_risky_flag: dict,
        overlap_connection_to_wifi: dict,
        overlap_installed_apps: dict,
    ):
        self.application_id = application_id
        self.application_fullname = application_fullname
        self.uninstalled = uninstalled
        self.application_risky_flag = application_risky_flag
        self.overlap_connection_to_wifi = overlap_connection_to_wifi
        self.overlap_installed_apps = overlap_installed_apps

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "application_fullname": self.application_fullname,
            "uninstalled": self.uninstalled,
            "application_risky_flag": self.application_risky_flag,
            "overlap_connection_to_wifi": self.overlap_connection_to_wifi,
            "overlap_installed_apps": self.overlap_installed_apps,
        }

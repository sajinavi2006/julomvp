from juloserver.portal.object.dashboard.constants import JuloUserRoles

FRONTEND_FIELD_MAP = {
    'loan_amount_request': {'label': 'Jumlah Pinjaman', 'type': 'number'},
    'loan_duration_request': {'label': 'Jangka Waktu', 'type': 'number'},
    'product_line': {'label': 'Product', 'type': 'choice'},
    'loan_purpose': {'label': 'Tujuan Pinjaman', 'type': 'choice'},
    'loan_purpose_desc': {'label': 'Uraian Tujuan Pinjaman', 'type': 'text'},
    'credit_score': {'label': 'Score Credit', 'type': 'text'},
    'credit_score_message': {'label': 'Score Message', 'type': 'text'},
    'marketing_source': {'label': 'Sumber Marketing', 'type': 'text'},
    'referral_code': {'label': 'Kode Referral', 'type': 'text'},
    'imei': {'label': 'IMEI', 'type': 'text'},
    'app_version': {'label': 'App Version', 'type': 'text'},
    'fullname': {'label': 'Nama Lengkap', 'type': 'text'},
    'customer': {'label': 'Customer ID', 'type': 'text'},
    'email': {'label': 'Email', 'type': 'text'},
    'dob': {'label': 'Tanggal Lahir', 'type': 'datetime'},
    'birth_place': {'label': 'Tempat Lahir', 'type': 'text'},
    'gender': {'label': 'Jenis Kelamin', 'type': 'choice'},
    'ktp': {'label': 'No. KTP', 'type': 'text'},
    'address': {'label': 'Alamat Tempat Tinggal', 'type': 'map'},
    'occupied_since': {'label': 'Ditempati Sejak', 'type': 'datetime'},
    'home_status': {'label': 'Status Domisili', 'type': 'text'},
    'last_education': {'label': 'Pendidikan Terakhir', 'type': 'text'},
    'college': {'label': 'Perguruan Tinggi', 'type': 'text'},
    'major': {'label': 'Jurusan', 'type': 'text'},
    'graduation_year': {'label': 'Tahun Lulus', 'type': 'text'},
    'gpa': {'label': 'IPK', 'type': 'text'},
    'mobile_phone_1': {'label': 'No. HP1', 'type': 'text'},
    'has_whatsapp_1': {'label': 'Ada WA1', 'type': 'boolean'},
    'mobile_phone_2': {'label': 'No. HP2', 'type': 'text'},
    'has_whatsapp_2': {'label': 'Ada WA2', 'type': 'boolean'},
    'dialect': {'label': 'Bahasa Daerah', 'type': 'choice'},
    'is_own_phone': {'label': 'HP Milik Sendiri', 'type': 'text'},
    'twitter_username': {'label': 'Twitter Username', 'type': 'text'},
    'instagram_username': {'label': 'Instagram Username', 'type': 'text'},
    'facebook_fullname': {'label': 'Nama Lengkap di FB', 'type': 'text'},
    'facebook_email': {'label': 'Email di FB', 'type': 'text'},
    'facebook_gender': {'label': 'Gender di FB', 'type': 'text'},
    'facebook_birth_date': {'label': 'Tgl Lahir di FB', 'type': 'text'},
    'facebook_friend_count': {'label': 'Friend Count', 'type': 'text'},
    'facebook_id': {'label': 'FB ID', 'type': 'text'},
    'facebook_open_date': {'label': 'FB Open Date', 'type': 'text'},
    'marital_status': {'label': 'Status Pernikahan', 'type': 'choice'},
    'dependent': {'label': 'Jumlah Tanggungan', 'type': 'text'},
    'spouse_name': {'label': 'Nama Pasangan', 'type': 'text'},
    'spouse_dob': {'label': 'Tgl Lahir Pasangan', 'type': 'datetime'},
    'spouse_mobile_phone': {'label': 'No. HP Pasangan', 'type': 'text'},
    'spouse_has_whatsapp': {'label': 'HP Pasangan Ada WA', 'type': 'boolean'},
    'close_kin_name': {'label': 'Nama Keluarga Kandung Terdekat', 'type': 'text'},
    'close_kin_mobile_phone': {'label': 'No HP Keluarga Kandung Terdekat', 'type': 'text'},
    'close_kin_relationship': {'label': 'Hubungan Keluarga Terdekat', 'type': 'choice'},
    'kin_name': {'label': 'Nama Keluarga Kandung', 'type': 'text'},
    'kin_dob': {'label': 'Tgl Lahir Keluarga Kandung', 'type': 'datetime'},
    'kin_gender': {'label': 'Jenis Kelamin Keluarga Kandung', 'type': 'choice'},
    'kin_mobile_phone': {'label': 'No HP Keluarga Kandung', 'type': 'text'},
    'kin_relationship': {'label': 'Hubungan Keluarga Kandung', 'type': 'choice'},
    'job_type': {'label': 'Tipe Pekerjaan', 'type': 'text'},
    'job_industry': {'label': 'Bidang Pekerjaan', 'type': 'text'},
    'job_description': {'label': 'Pekerjaan', 'type': 'text'},
    'company_name': {'label': 'Nama Perusahaan', 'type': 'text'},
    'company_phone_number': {'label': 'No Telp Perusahaan', 'type': 'text'},
    'work_kodepos': {'label': 'Kode Pos Kantor', 'type': 'number'},
    'hrd_name': {'label': 'Nama HRD/atasan', 'type': 'text'},
    'company_address': {'label': 'Alamat Kantor/Penempatan', 'type': 'text'},
    'number_of_employees': {'label': 'Jumlah Karyawan', 'type': 'number'},
    'position_employees': {'label': 'Posisi Karyawan', 'type': 'text'},
    'employment_status': {'label': 'Status Kepegawaian', 'type': 'text'},
    'billing_office': {'label': 'Penagihan/Tunggakan di Kantor', 'type': 'text'},
    'mutation': {'label': 'Mutasi/Resign', 'type': 'text'},
    'job_start': {'label': 'Tanggal Mulai Bekerja', 'type': 'datetime'},
    'payday': {'label': 'Tanggal Gajian', 'type': 'number'},
    'monthly_income': {'label': 'Penghasilan Bersih Per Bulan', 'type': 'money'},
    'verified_income': {'label': 'Penghasilan di dokumen', 'type': 'money'},
    'income_1': {'label': 'Penghasilan T-1', 'type': 'text'},
    'income_2': {'label': 'Penghasilan T-2', 'type': 'text'},
    'income_3': {'label': 'Penghasilan T-3', 'type': 'text'},
    'has_other_income': {'label': 'Ada Penghasilan Lain?', 'type': 'text'},
    'other_income_amount': {'label': 'Besar Penghasilan Lain', 'type': 'money'},
    'other_income_source': {'label': 'Sumber Penghasilan Lain', 'type': 'text'},
    'vehicle_type_1': {'label': 'Kendaraan Pribadi', 'type': 'text'},
    'vehicle_ownership_1': {'label': 'Kepemilikan Kendaraan', 'type': 'choice'},
    'bank_name': {'label': 'Nama Bank', 'type': 'text'},
    'bank_branch': {'label': 'Cabang Bank', 'type': 'text'},
    'bank_account_number': {'label': 'No Rekening', 'type': 'text'},
    'name_in_bank': {'label': 'Nama sesuai rekening bank', 'type': 'text'},
    'monthly_housing_cost': {'label': 'Biaya Sewa/Cicilan Rumah per Bulan', 'type': 'money'},
    'monthly_expenses': {'label': 'Pengeluaran Rutin per Bulan (selain rumah)', 'type': 'money'},
    'total_current_debt': {'label': 'Total Cicilan Hutang per Bulan', 'type': 'money'},
}

FRONTEND_EXTRA_FIELDS = {
    'dob_in_nik': {'label': 'Dob check in NIK'},
    'area_in_nik': {'label': 'Area Code check in NIK'},
    'fraud_report': {'label': 'Fraud Report'},
    'karakter': {'label': 'Karakter'},
    'selfie': {'label': 'Selfie'},
    'signature': {'label': 'Tanda Tangan'},
    'voice_recording': {'label': 'Voice Recording'},
}

COLL_ROLES = JuloUserRoles.collection_roles() + [JuloUserRoles.COLLECTION_SUPERVISOR]


class DVCFilterMapper():
    sd_group_fields = ['loan_purpose', 'loan_purpose_desc', 'dob_in_nik', 'area_in_nik',
                       'monthly_expenses', 'total_current_debt', 'fraud_report', 'karakter']
    dv_group_fields = ['loan_purpose_desc', 'product_line', 'loan_amount_request', 'fullname',
                       'dob', 'ktp', 'mobile_phone_1', 'marital_status', 'spouse_name',
                       'spouse_mobile_phone', 'bank_account_number', 'name_in_bank', 'selfie']
    pve_group_fields = ['company_name', 'company_phone_number', 'hrd_name',
                        'position_employees', 'job_start', 'employment_status', 'mutation',
                        'monthly_income', 'payday', 'billing_office']
    pva_group_fields = ['fullname', 'dob', 'ktp', 'address', 'home_status',
                        'mobile_phone_1', 'mobile_phone_2', 'marital_status', 'dependent',
                        'company_name', 'hrd_name', 'company_address', 'position_employees',
                        'employment_status', 'billing_office', 'payday', 'monthly_income',
                        'monthly_housing_cost', 'monthly_expenses', 'total_current_debt',
                        'fraud_report']
    fin_group_fields = ['signature', 'voice_recording']
    coll_group_fields = ['address', 'payday', 'loan_purpose', 'gender',
                         'mobile_phone_1', 'mobile_phone_2', 'dialect', 'spouse_name',
                         'spouse_mobile_phone', 'close_kin_name', 'close_kin_mobile_phone',
                         'close_kin_relationship', 'kin_name', 'kin_gender', 'kin_mobile_phone',
                         'kin_relationship', 'company_name', 'company_phone_number',
                         'company_address', 'position_employees']

MAXIMUM_FILE_SIZE_UPLOAD_USERS = 5242880  # bytes


class UserSegmentError:
    INVALID_DATA = (
        'Isi data file kosong atau tidak valid. Harap upload file dengan data yang valid.'
    )
    DATA_NOT_FOUND = 'Isi data file tidak memiliki {} atau tidak valid. Harap upload file dengan data yang valid.'
    ALREADY_EXIST = 'Nama sudah pernah digunakan, silahkan gunakan nama lain.'
    FILE_SIZE = 'Ukuran file di atas 5MB'
    CHARACTER_LIMIT = 'Maximum 50 Karakter'
    INVALID_FORMAT = 'Harap upload file dengan format CSV'

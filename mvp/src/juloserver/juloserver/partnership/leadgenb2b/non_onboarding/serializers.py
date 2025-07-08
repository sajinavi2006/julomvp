import re


class LeadgenLoanSignatureUploadSerializer:
    def __init__(self, data):
        self.data = data
        self.errors = ""
        self.validated_data = {}

    def validate(self):
        self.errors = ""
        self.validate_upload()
        self.validate_data()
        return self.errors

    def validate_upload(self):
        upload_file = self.data.get('upload')
        if not upload_file:
            self.errors = "Upload file tidak boleh kosong"
        else:
            is_jpg = upload_file.name.endswith(".jpg")
            is_png = upload_file.name.endswith(".png")
            is_jpeg = upload_file.name.endswith(".jpeg")
            if True not in {is_jpg, is_png, is_jpeg}:
                self.errors = "Ekstensi file harus berupa .jpg atau .png atau .jpeg"
            else:
                self.validated_data["upload"] = upload_file

    def validate_data(self):
        data_path = self.data.get('data')
        if not data_path:
            self.errors = "Path data tidak boleh kosong"
        else:
            pattern = re.compile(r'\.{2,}|\.{2,}\/')
            result = pattern.search(data_path)
            err = "Path file tidak valid"
            if result:
                self.errors = err
            elif data_path.startswith('--') or data_path.endswith('--'):
                self.errors = err
            elif not re.match(r"^[a-zA-Z0-9-_/.]+$", data_path):
                self.errors = err
            else:
                self.validated_data["data"] = data_path

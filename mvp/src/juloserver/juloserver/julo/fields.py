from django.db import models


class EmailLowerCaseField(models.EmailField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        if value:
            return str(value).lower()
        return value

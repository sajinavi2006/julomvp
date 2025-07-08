from pathlib import Path
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class FileExtensionValidator:
    """
    Duplicate from
    https://github.com/django/django/blob/stable/5.0.x/django/core/validators.py#L561
    """

    message = _(
        "File extension “%(extension)s” is not allowed. "
        "Allowed extensions are: %(allowed_extensions)s."
    )
    code = "invalid_extension"

    def __init__(self, allowed_extensions=None, message=None, code=None):
        if allowed_extensions is not None:
            allowed_extensions = [
                allowed_extension.lower() for allowed_extension in allowed_extensions
            ]
        self.allowed_extensions = allowed_extensions
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code

    def __call__(self, value):
        extension = Path(value.name).suffix[1:].lower()
        if self.allowed_extensions is not None and extension not in self.allowed_extensions:
            raise ValidationError(
                self.message,
                code=self.code,
                params={
                    "extension": extension,
                    "allowed_extensions": ", ".join(self.allowed_extensions),
                    "value": value,
                },
            )

    def __eq__(self, other):
        return (
            isinstance(other, self.__class__)
            and set(self.allowed_extensions or []) == set(other.allowed_extensions or [])
            and self.message == other.message
            and self.code == other.code
        )


def get_available_image_extensions():
    """
    Duplicate from
    https://github.com/django/django/blob/stable/5.0.x/django/core/validators.py#L604
    """
    try:
        from PIL import Image
    except ImportError:
        return []
    else:
        Image.init()
        return [ext.lower()[1:] for ext in Image.EXTENSION]


def validate_image_file_extension(value):
    """
    Duplicate from
    https://github.com/django/django/blob/stable/5.0.x/django/core/validators.py#L604
    """
    return FileExtensionValidator(allowed_extensions=get_available_image_extensions())(value)


@deconstructible
class FileSizeValidator:
    message = _("File size is too large.")
    max_size = 5 * 1024 * 1024  # 5 MB
    code = "invalid_file_size"

    def __init__(self, max_size=None, message=None, code=None):
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if max_size is not None:
            self.max_size = max_size

    def __call__(self, value):
        if value.size > self.max_size:
            raise ValidationError(
                self.message,
                code=self.code,
            )
        return value

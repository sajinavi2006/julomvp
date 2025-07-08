import math
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, date, time
from typing import Any, Optional, Dict, Union, List

from juloserver.channeling_loan.exceptions import (
    ChannelingMappingValueError,
    ChannelingMappingNullValueError,
)
from juloserver.channeling_loan.utils import convert_datetime_string_to_other_format, padding_words


@dataclass
class GeneralChannelingData:
    """
    value: value to be mapped
    function_post_mapping: function to be executed after mapping
    is_hardcode: if True, value will be used as is. No more processing
    length: for str type: left-justified string of length width;
            for float type: round down to decimal length
    data_type: supported str, bool, int, float, datetime, date, time
    input_format: for str & datetime types: format to convert string to datetime
    output_format: for str & datetime types: format to convert datetime to string
    """

    value: Any
    function_post_mapping: Optional[str] = None
    is_hardcode: bool = False
    allow_null: bool = True
    is_padding_word: bool = False
    is_padding_number: bool = False
    length: Optional[int] = None
    data_type: type = str
    input_format: Optional[str] = None
    output_format: Optional[str] = None

    def __repr__(self) -> str:
        # Only show non-default values to keep output clean
        parts = [f"value={repr(self.value)}"]

        if self.function_post_mapping is not None:
            parts.append(f"function_post_mapping='{self.function_post_mapping}'")
        if self.is_hardcode:
            parts.append("is_hardcode=True")
        if not self.allow_null:
            parts.append("allow_null=False")
        if self.is_padding_word:
            parts.append("is_padding_word=True")
        if self.is_padding_number:
            parts.append("is_padding_number=True")
        if self.length is not None:
            parts.append(f"length={self.length}")
        if self.data_type != str:
            parts.append(f"data_type={self.data_type.__name__}")
        if self.input_format is not None:
            parts.append(f"input_format='{self.input_format}'")
        if self.output_format is not None:
            parts.append(f"output_format='{self.output_format}'")

        return f"GeneralChannelingData({', '.join(parts)})"


class ChannelingMappingServices:
    def __init__(self, **kwargs):
        """
        :param kwargs: objects that are required for eval during mapping
        """

        for key, value in kwargs.items():
            setattr(self, key, value)

    def data_mapping(
        self, data_map: Dict[str, Optional[Union[GeneralChannelingData, List[Dict], Dict]]]
    ) -> Dict[str, Any]:
        """
        recursively fill the data with eval function
        the data must exist before filling
        make sure set format (any set will be skipped)
        """
        data_map = deepcopy(data_map)
        for key, data in data_map.items():
            if type(data) is list:
                list_child_data_map = []
                for item in data:
                    list_child_data_map.append(self.data_mapping(data_map=item))
                data_map[key] = list_child_data_map
            elif type(data) is dict:
                data_map[key] = self.data_mapping(data_map=data_map[key])
            elif type(data) is GeneralChannelingData:
                data_map[key] = self._evaluate_value(
                    mapping_key=key,
                    channeling_data=data,
                )
            elif data is None:
                data_map[key] = self._evaluate_value(
                    mapping_key=key, channeling_data=GeneralChannelingData(value=None)
                )
            else:
                raise ChannelingMappingValueError(
                    "Unsupported data map type: {}".format(type(data)),
                    mapping_key=key,
                    mapping_value=str(data),
                )

        return data_map

    def _evaluate_value(
        self,
        mapping_key: str,
        channeling_data: GeneralChannelingData,
    ) -> Any:
        if channeling_data.is_hardcode:
            # return the data directly if hardcoded
            return channeling_data.value

        if channeling_data.value is None:
            # return the data directly if empty
            return None

        mapping_value = repr(channeling_data)

        # objects were inited via kwargs in the constructor, so can access them via self.object_name
        channeling_data.value = eval("self.{}".format(channeling_data.value))

        if channeling_data.value is None:
            if not channeling_data.allow_null:
                # if value is None after eval and not allowed to be null, raise error
                raise ChannelingMappingNullValueError(
                    "Value is null and not allowed to be null",
                    mapping_key=mapping_key,
                    mapping_value=mapping_value,
                )

            # return None directly if still empty after eval
            return None

        if channeling_data.function_post_mapping:
            channeling_data.value = eval("self.{}".format(channeling_data.function_post_mapping))(
                channeling_data.value
            )

        if not channeling_data.allow_null and channeling_data.value is None:
            # if value is still None after post mapping, raise error
            raise ChannelingMappingNullValueError(
                "Value is null and not allowed to be null",
                mapping_key=mapping_key,
                mapping_value=mapping_value,
            )

        return self._map_type(
            mapping_key=mapping_key,
            mapping_value=mapping_value,
            value=channeling_data.value,
            is_padding_word=channeling_data.is_padding_word,
            is_padding_number=channeling_data.is_padding_number,
            length=channeling_data.length,
            data_type=channeling_data.data_type,
            input_format=channeling_data.input_format,
            output_format=channeling_data.output_format,
        )

    def _map_type(
        self,
        mapping_key: str,
        mapping_value: str,
        value: Any,
        is_padding_word: bool,
        is_padding_number: bool,
        length: Optional[int],
        data_type: type,
        input_format: Optional[str],
        output_format: Optional[str],
    ) -> Any:
        """
        :param value: value to be mapped
        :param length: for str type: left-justified string of length width;
                       for float type: round down to decimal length
        :param data_type: supported str, bool, int, float, datetime, date, time
        :param input_format: for str & datetime types: format to convert string to datetime
        :param output_format: for str & datetime types: format to convert datetime to string
        :return: value with the correct type
        """

        datetime_types = [datetime, date, time]
        supported_data_types = [str, bool, int, float] + datetime_types

        if data_type not in supported_data_types:
            raise ChannelingMappingValueError(
                "Unsupported data type. Supported values are {}".format(
                    ', '.join([str(t) for t in supported_data_types])
                ),
                mapping_key=mapping_key,
                mapping_value=mapping_value,
            )

        if data_type in datetime_types:
            value = self._map_datetime_type(
                mapping_key=mapping_key,
                mapping_value=mapping_value,
                value=value,
                data_type=data_type,
                input_format=input_format,
            )
        elif data_type is str:
            value = self._map_str_type(
                mapping_key=mapping_key,
                mapping_value=mapping_value,
                value=value,
                is_padding_word=is_padding_word,
                is_padding_number=is_padding_number,
                length=length,
                input_format=input_format,
                output_format=output_format,
            )
        elif data_type is float:
            value = self._map_float_type(value=value, length=length)
        elif data_type in (bool, int):
            value = data_type(value)

        return value

    @staticmethod
    def _map_datetime_type(
        mapping_key: str,
        mapping_value: str,
        value: Any,
        data_type: type,
        input_format: Optional[str] = None,
    ) -> Any:
        if type(value) is str:
            if not input_format:
                raise ChannelingMappingValueError(
                    "Input format is required to convert from string to datetime",
                    mapping_key=mapping_key,
                    mapping_value=mapping_value,
                )

            value = datetime.strptime(value, input_format)
            if data_type is date:
                value = value.date()
            elif data_type is time:
                value = value.time()

        elif type(value) is datetime:
            if data_type is date:
                value = value.date()
            elif data_type is time:
                value = value.time()

        elif type(value) is date:
            if data_type is datetime:
                value = datetime.combine(value, time())
            elif data_type is time:
                value = time()

        elif type(value) is time:
            if data_type is datetime:
                value = datetime.combine(date.today(), value)
            elif data_type is date:
                value = date.today()

        else:
            raise ChannelingMappingValueError(
                "Unsupported value for datetime mapping",
                mapping_key=mapping_key,
                mapping_value=mapping_value,
            )

        return value

    @staticmethod
    def _map_str_type(
        mapping_key: str,
        mapping_value: str,
        value: Any,
        is_padding_word: bool,
        is_padding_number: bool,
        length: Optional[int],
        input_format: Optional[str] = None,
        output_format: Optional[str] = None,
    ) -> str:
        if type(value) is str and (input_format or output_format):
            # convert datetime string from one format to another format

            if (input_format and not output_format) or (output_format and not input_format):
                raise ChannelingMappingValueError(
                    "Input and output format is required to convert datetime from string to string",
                    mapping_key=mapping_key,
                    mapping_value=mapping_value,
                )

            if input_format and output_format:
                value = convert_datetime_string_to_other_format(value, input_format, output_format)

        if type(value) in (datetime, date, time):
            if not output_format:
                raise ChannelingMappingValueError(
                    "Output format is required to convert from datetime to string",
                    mapping_key=mapping_key,
                    mapping_value=mapping_value,
                )
            value = value.strftime(output_format)

        value = str(value)

        if length:
            if is_padding_word:
                value = padding_words(word=value, length=length)
            elif is_padding_number:
                value = value.zfill(length)
            else:
                value = value[:length] if len(value) > length else value

        return value

    @staticmethod
    def _map_float_type(value: Any, length: Optional[int]) -> float:
        value = float(value)

        if length is None:
            length = 2  # default number of decimal places for float

        value = math.floor(value * pow(10, length)) / pow(10, length)

        return value

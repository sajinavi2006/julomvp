import sys
from kombu.serialization import str_to_bytes, BytesIO
from kombu.serialization import pickle_load, pickle, pickle_protocol


def pickle_loads(s, load=pickle_load):
    # used to support buffer objects
    return load(BytesIO(s), fix_imports=True, encoding="latin1")


def pickle_loads_p2(s, load=pickle_load):
    # used to support buffer objects
    return load(BytesIO(s))


if sys.version_info[0] == 3:  # pragma: no cover
    def unpickle(s):
        return pickle_loads(str_to_bytes(s))
else:
    unpickle = pickle_loads_p2  # noqa


def pickle_dumps(obj, dumper=pickle.dumps):
    return dumper(obj, protocol=pickle_protocol)

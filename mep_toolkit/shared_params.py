"""Read a Revit shared parameter file (UTF-16 text). Read only; never writes.

Only the lines this toolkit needs are used:
  GROUP<TAB>id<TAB>name
  PARAM<TAB>guid<TAB>name<TAB>datatype<TAB>...
"""
import hashlib
from dataclasses import dataclass
from typing import Tuple


class SharedFileError(ValueError):
    """The shared parameter file cannot be read as expected."""


@dataclass(frozen=True)
class FileParam:
    name: str
    guid: str  # as written in the file
    data_type: str


@dataclass(frozen=True)
class SharedFile:
    sha256: str
    groups: Tuple[str, ...]
    params: Tuple[FileParam, ...]


def parse_shared_bytes(raw: bytes) -> SharedFile:
    """Parse the raw bytes of a shared parameter file."""
    if not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise SharedFileError("not a UTF-16 file with a byte order mark (Revit shared parameter files are UTF-16)")
    try:
        text = raw.decode("utf-16")
    except UnicodeDecodeError as ex:
        raise SharedFileError("cannot decode the file as UTF-16: %s" % ex) from ex
    groups = []
    params = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("GROUP\t"):
            cols = line.split("\t")
            if len(cols) < 3 or not cols[2].strip():
                raise SharedFileError("line %d: GROUP needs an ID and a NAME" % number)
            groups.append(cols[2])
        elif line.startswith("PARAM\t"):
            cols = line.split("\t")
            if len(cols) < 4 or not cols[2].strip():
                raise SharedFileError("line %d: PARAM needs a GUID, a NAME and a DATATYPE" % number)
            params.append(FileParam(name=cols[2], guid=cols[1], data_type=cols[3]))
    if not params:
        raise SharedFileError("the file has no PARAM lines")
    return SharedFile(hashlib.sha256(raw).hexdigest(), tuple(groups), tuple(params))


def parse_shared_file(path: str) -> SharedFile:
    with open(path, "rb") as fh:
        return parse_shared_bytes(fh.read())

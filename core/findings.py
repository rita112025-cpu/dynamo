"""Finding: the result of one check on one element (or on the whole model)."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    # The check could not decide (missing data, closed workset, rule not confirmed).
    # Never report it as PASS.
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class Finding:
    check: str
    status: Status
    element_id: Optional[int] = None  # None = the finding is about the whole model
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.check, str) or not self.check.strip():
            raise ValueError("check must be a non-empty string")
        if not isinstance(self.status, Status):
            raise ValueError("status must be a Status, got %r" % (self.status,))
        if self.element_id is not None and (
            isinstance(self.element_id, bool) or not isinstance(self.element_id, int)
        ):
            raise ValueError("element_id must be an int or None, got %r" % (self.element_id,))
        if not isinstance(self.reason, str):
            raise ValueError("reason must be a string")
        if self.status is not Status.PASS and not self.reason.strip():
            raise ValueError("%s findings need a reason" % self.status.value)

from enum import StrEnum


class MonitoringMode(StrEnum):
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    CURRENT_MONITORING = "CURRENT_MONITORING"


class QualityFlag(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    DUPLICATE = "DUPLICATE"
    SUSPECT = "SUSPECT"


class UserRole(StrEnum):
    COORDINATOR = "coordinator"
    FIELD_OFFICER = "field_officer"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    DISMISSED = "DISMISSED"
    NEEDS_FOLLOWUP = "NEEDS_FOLLOWUP"


class PriorityLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DISMISSED = "DISMISSED"


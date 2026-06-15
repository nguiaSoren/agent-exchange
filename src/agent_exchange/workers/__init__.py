"""Worker agents — specialists (system prompt + model backend) and the audit pool."""

from .finding import Finding, Severity, Specialist, parse_findings
from .job_types import JOB_TYPES, JobType, document_label_for, job_kinds, roster_for
from .nda_specialists import NDA_SPECIALISTS, SAMPLE_NDA
from .pool import AuditPool
from .reporter import ReporterWorker
from .specialist import SPECIALISTS, SpecialistWorker, make_pool_specialists
from .worker import Worker, make_worker

__all__ = [
    "Worker",
    "make_worker",
    "Finding",
    "Severity",
    "Specialist",
    "parse_findings",
    "SpecialistWorker",
    "SPECIALISTS",
    "make_pool_specialists",
    "AuditPool",
    "ReporterWorker",
    "NDA_SPECIALISTS",
    "SAMPLE_NDA",
    "JobType",
    "JOB_TYPES",
    "roster_for",
    "document_label_for",
    "job_kinds",
]

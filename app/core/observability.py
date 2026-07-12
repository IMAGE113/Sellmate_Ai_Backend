import uuid
import contextvars
import logging
from typing import Optional

# Context variable to store correlation ID for the duration of a request/task
correlation_id_ctx = contextvars.ContextVar("correlation_id", default=None)

class Observability:
    @staticmethod
    def set_correlation_id(cid: Optional[str] = None) -> str:
        cid = cid or str(uuid.uuid4())
        correlation_id_ctx.set(cid)
        return cid

    @staticmethod
    def get_correlation_id() -> Optional[str]:
        return correlation_id_ctx.get()

class StructuredLogger:
    """
    Logger that automatically includes correlation ID in every log record.
    """
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

    def _log(self, level, msg, *args, **kwargs):
        extra = kwargs.get("extra", {})
        extra["correlation_id"] = Observability.get_correlation_id()
        kwargs["extra"] = extra
        self.logger.log(level, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs): self._log(logging.INFO, msg, *args, **kwargs)
    def error(self, msg, *args, **kwargs): self._log(logging.ERROR, msg, *args, **kwargs)
    def warning(self, msg, *args, **kwargs): self._log(logging.WARNING, msg, *args, **kwargs)

import logging
import functools
from typing import Any, Callable

def workflow_error_handler(fallback_status: str = "FALLBACK"):
    """
    Decorator for workflow-related functions to ensure they never fail silently.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logging.error(f"Workflow Error in {func.__name__}: {e}", exc_info=True)
                # Return a safe fallback or structure that the caller can handle
                return {"error": str(e), "status_key": fallback_status}
        return wrapper
    return decorator

class SellMateError(Exception):
    """Base error for SellMate application."""
    pass

class MultiTenancyError(SellMateError):
    """Raised when merchant isolation is breached or invalid."""
    pass

class WorkflowError(SellMateError):
    """Raised during conversation or order workflow issues."""
    pass

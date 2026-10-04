from openai import RateLimitError, APITimeoutError, APIConnectionError, AuthenticationError, NotFoundError
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError, ClientAuthenticationError


def friendly(e: Exception) -> str:
    """رسالة مفهومة للمستخدم، من غير مفاتيح أو محتوى CVs."""
    if isinstance(e, RateLimitError):
        return "Azure OpenAI is busy (429). Wait a bit or switch the deployment in .env."
    if isinstance(e, APITimeoutError):
        return "Azure OpenAI timed out. Try again."
    if isinstance(e, APIConnectionError):
        return "Cannot reach Azure OpenAI. Check your network."
    if isinstance(e, AuthenticationError):
        return "Azure OpenAI rejected the key/endpoint. Check .env."
    if isinstance(e, NotFoundError):
        return "Azure OpenAI deployment not found. Check deployment names in .env."
    if isinstance(e, ResourceNotFoundError):
        return "Azure resource not found (index or container missing)."
    if isinstance(e, ClientAuthenticationError):
        return "Azure credentials rejected. Check the keys in .env."
    if isinstance(e, HttpResponseError):
        return f"Azure service error (HTTP {getattr(e, 'status_code', '?')})."
    if isinstance(e, ValueError):
        return str(e)
    return f"Unexpected error ({type(e).__name__})."
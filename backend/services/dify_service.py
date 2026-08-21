"""Server-side client for the existing Dify chat application."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import DIFY_API_URL, DIFY_TIMEOUT_SECONDS, get_dify_api_key


class DifyServiceError(RuntimeError):
    """Raised when Dify cannot return a final chat answer."""


def chat_with_dify(user_id: str | int, message: str) -> str:
    """Send one user message to Dify and return its final text answer.

    ``user_id`` is forwarded both as Dify's stable end-user identifier and as
    the Workflow input variable named ``user_id``.
    """
    if not str(user_id).strip():
        raise ValueError("user_id is required")
    if not message or not message.strip():
        raise ValueError("message is required")

    payload = {
        "inputs": {"user_id": str(user_id)},
        "query": message,
        "response_mode": "blocking",
        "user": str(user_id),
    }
    request = Request(
        DIFY_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {get_dify_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=DIFY_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise DifyServiceError(f"Dify API request failed with status {error.code}") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise DifyServiceError("Dify API request failed") from error

    answer = result.get("answer")
    if not isinstance(answer, str):
        raise DifyServiceError("Dify API response did not contain an answer")
    return answer

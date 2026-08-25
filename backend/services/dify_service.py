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
    "inputs": {
        "user_id": str(user_id),
        "user_input": message,
    },
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
            status_code = response.status
            response_body = response.read().decode("utf-8")

            print(f"[Dify] HTTP {status_code}")
            print(f"[Dify] Response: {response_body}")

            result = json.loads(response_body)

    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")

        print(f"[Dify] HTTP Error {error.code}")
        print(f"[Dify] Response: {response_body}")

        raise DifyServiceError(
            f"Dify API request failed with status {error.code}: {response_body}"
        ) from error

    except (URLError, TimeoutError) as error:
        print(f"[Dify] Connection error: {error}")
        raise DifyServiceError("Dify API request failed") from error

    except json.JSONDecodeError as error:
        print(f"[Dify] Invalid JSON response: {response_body}")
        raise DifyServiceError("Dify API returned invalid JSON") from error

    data = result.get("data", {})
    outputs = data.get("outputs", {})
    answer = outputs.get("answer")

    if not isinstance(answer, str):
        print(f"[Dify] Missing answer field. Response: {result}")
        raise DifyServiceError("Dify API response did not contain an answer")

    return answer
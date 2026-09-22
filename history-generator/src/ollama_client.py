import json
import time

import requests

from gpu_lock import gpu_lock


class OllamaError(Exception):
    pass


def _post(url, payload, timeout, retries, backoff):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            # Held for the whole request, not just the attempt loop -- Ollama's
            # /api/chat with stream:false blocks until generation finishes, so the GPU
            # is busy for the request's full duration. See gpu_lock.py.
            with gpu_lock:
                resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001 - want to retry on anything and report it
            last_exc = e
            if attempt < retries:
                sleep_s = backoff * attempt
                print(f"     [warn] Ollama request failed (attempt {attempt}/{retries}): {e}; retrying in {sleep_s:.0f}s")
                time.sleep(sleep_s)
    raise OllamaError(f"Ollama request failed after {retries} attempts: {last_exc}")


def chat_json(base_url, model, system, user, temperature=0.7, retries=3, backoff=5, timeout=180):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "format": "json",
        "think": False,
        "stream": False,
        "options": {"temperature": temperature},
    }
    data = _post(f"{base_url}/api/chat", payload, timeout, retries, backoff)
    content = data["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise OllamaError(f"Ollama returned invalid JSON: {e}\ncontent={content[:500]}") from e


def chat_tool(base_url, model, system, user, tool, temperature=0.4, retries=3, backoff=5, timeout=180):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "tools": [tool],
        "think": False,
        "stream": False,
        "options": {"temperature": temperature},
    }
    data = _post(f"{base_url}/api/chat", payload, timeout, retries, backoff)
    tool_calls = data.get("message", {}).get("tool_calls") or []
    if not tool_calls:
        raise OllamaError(f"model did not call the '{tool['function']['name']}' tool")
    args = tool_calls[0]["function"]["arguments"]
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError as e:
            raise OllamaError(f"tool call arguments were not valid JSON: {e}") from e
    return args


def chat_text(base_url, model, system, user, temperature=0.8, retries=3, backoff=5, timeout=180):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "think": False,
        "stream": False,
        "options": {"temperature": temperature},
    }
    data = _post(f"{base_url}/api/chat", payload, timeout, retries, backoff)
    return data["message"]["content"].strip()

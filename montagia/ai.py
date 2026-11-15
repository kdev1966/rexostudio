"""Client Ollama : sorties structurees (JSON Schema) et streaming.

Le point cle : sur un modele 3B, la seule maniere fiable d'obtenir une
reponse exploitable est de fixer un schema JSON. On l'utilise partout.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config


class OllamaError(RuntimeError):
    def __init__(self, message, raw: str = ""):
        super().__init__(message)
        self.raw = raw          # reponse brute du modele (recuperation partielle)


def _post(path: str, payload: dict, timeout: int = None, stream: bool = False):
    url = config.OLLAMA_URL.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    timeout = timeout or config.LLM_TIMEOUT
    if stream:
        return urllib.request.urlopen(req, timeout=timeout)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str, timeout: int = 10):
    url = config.OLLAMA_URL.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_up() -> bool:
    try:
        _get("/api/version", timeout=3)
        return True
    except Exception:
        return False


def list_models() -> list:
    try:
        data = _get("/api/tags", timeout=5)
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def extract_json(text: str):
    """Extrait un objet/tableau JSON d'une reponse brute (le 3B emballe souvent
    sa reponse dans des backticks ou du texte)."""
    if not text:
        raise OllamaError("Reponse vide du modele")
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1] if "```" in raw[3:] else raw[3:]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.split("```")[0]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except ValueError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except ValueError:
                continue
    raise OllamaError("Reponse JSON invalide : %s" % raw[:300], raw=raw)


def chat_json(system: str, user: str, schema: dict, model: str = None,
              temperature: float = 0.3, num_predict: int = 1200,
              timeout: int = None) -> dict:
    """Appel avec schema JSON : la reponse est un dict/list deja parse."""
    payload = {
        "model": model or config.LLM_MODEL,
        "stream": False,
        "format": schema,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": temperature,
            "num_ctx": config.LLM_NUM_CTX,
            "num_predict": num_predict,
            "top_p": 0.9,
            "repeat_penalty": 1.05,
        },
        "keep_alive": config.LLM_KEEP_ALIVE,
    }
    try:
        resp = _post("/api/chat", payload, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:500]
        except Exception:
            pass
        raise OllamaError("Ollama HTTP %s : %s" % (exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise OllamaError("Ollama injoignable (%s). Lancez 'ollama serve'." % exc.reason) from exc

    content = (resp.get("message") or {}).get("content", "")
    if not content.strip():
        raise OllamaError("Le modele n'a rien repondu (prompt trop long ?)")
    return extract_json(content)


def chat_text(system: str, user: str, model: str = None,
              temperature: float = 0.6, num_predict: int = 900) -> str:
    payload = {
        "model": model or config.LLM_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": temperature,
            "num_ctx": config.LLM_NUM_CTX,
            "num_predict": num_predict,
            "top_p": 0.9,
        },
        "keep_alive": config.LLM_KEEP_ALIVE,
    }
    try:
        resp = _post("/api/chat", payload)
    except urllib.error.URLError as exc:
        raise OllamaError("Ollama injoignable (%s)" % exc.reason) from exc
    return (resp.get("message") or {}).get("content", "").strip()


def chat_stream(system: str, user: str, model: str = None,
                temperature: float = 0.6, num_predict: int = 900):
    """Generateur de fragments de texte (pour le chat en flux)."""
    payload = {
        "model": model or config.LLM_MODEL,
        "stream": True,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": temperature,
            "num_ctx": config.LLM_NUM_CTX,
            "num_predict": num_predict,
            "top_p": 0.9,
        },
        "keep_alive": config.LLM_KEEP_ALIVE,
    }
    resp = _post("/api/chat", payload, stream=True)
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if data.get("error"):
                raise OllamaError(data["error"])
            piece = (data.get("message") or {}).get("content", "")
            if piece:
                yield piece
            if data.get("done"):
                break


def loaded_models() -> list:
    """Modeles actuellement en memoire (noms)."""
    try:
        return [m.get("name", "") for m in _get("/api/ps", timeout=3).get("models", [])]
    except Exception:
        return []


def unload(model: str = None) -> bool:
    """Decharge le modele de la RAM (bouton Quitter, avant un rendu...).
    Rien a faire s'il n'est pas charge : une requete keep_alive=0 sur un
    modele absent le chargerait d'abord (2,4 Go lus pour rien)."""
    model = model or config.LLM_MODEL
    if model not in loaded_models():
        return True
    try:
        _post("/api/generate", {"model": model, "keep_alive": 0}, timeout=30)
        return True
    except Exception:
        return False


def stats() -> dict:
    """Infos utiles affichees dans l'interface."""
    info = {"up": False, "model": config.LLM_MODEL, "models": [], "ctx": config.LLM_NUM_CTX}
    try:
        info["version"] = _get("/api/version", timeout=3).get("version", "")
        info["up"] = True
    except Exception:
        return info
    try:
        tags = _get("/api/tags", timeout=5)
        info["models"] = [
            {"name": m.get("name"), "size": m.get("size", 0),
             "params": (m.get("details") or {}).get("parameter_size", ""),
             "quant": (m.get("details") or {}).get("quantization_level", "")}
            for m in tags.get("models", [])
        ]
    except Exception:
        pass
    return info

"""Client de l'IA locale : sorties structurees (JSON Schema) et streaming.

Deux moteurs, meme interface pour le reste du code :
- llama.cpp (bin/llama-server, voir llm_server.py), par defaut s'il est
  installe : environ 2 fois plus rapide sur l'iMac 2015 ;
- Ollama, en secours (config.LLM_BACKEND).

Le point cle : sur un petit modele, la seule maniere fiable d'obtenir une
reponse exploitable est de fixer un schema JSON. On l'utilise partout
(llama.cpp le transforme en grammaire, Ollama le passe en "format").
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config, llm_server


class LLMError(RuntimeError):
    def __init__(self, message, raw: str = ""):
        super().__init__(message)
        self.raw = raw          # reponse brute du modele (recuperation partielle)


# -- Ollama : bas niveau -----------------------------------------------------
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


def _http_error(exc) -> LLMError:
    if isinstance(exc, urllib.error.HTTPError):
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:500]
        except Exception:
            pass
        return LLMError("Moteur IA, erreur HTTP %s : %s" % (exc.code, detail))
    if isinstance(exc, urllib.error.URLError):
        if config.LLM_BACKEND == "ollama":
            return LLMError("Ollama injoignable (%s). Lancez 'ollama serve'." % exc.reason)
        return LLMError("Moteur IA injoignable (%s)" % exc.reason)
    return LLMError(str(exc))


# -- un echange, quel que soit le moteur -------------------------------------
def _messages(system: str, user: str) -> list:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _llama_body(messages, temperature, num_predict, schema=None, repeat_penalty=None,
                stream=False) -> dict:
    body = {
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.9,
        "max_tokens": num_predict,
        "stream": stream,
        "cache_prompt": True,           # debut commun des appels relu depuis le cache
        # Modeles a "reflexion" (Qwen3.5, Gemma 4) : reponse directe.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if repeat_penalty:
        body["repeat_penalty"] = repeat_penalty
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"schema": schema}}
    return body


def _ollama_payload(messages, temperature, num_predict, schema=None, repeat_penalty=None,
                    stream=False) -> dict:
    options = {"temperature": temperature, "num_ctx": config.LLM_NUM_CTX,
               "num_predict": num_predict, "top_p": 0.9}
    if repeat_penalty:
        options["repeat_penalty"] = repeat_penalty
    payload = {"model": config.LLM_MODEL, "stream": stream, "messages": messages,
               "options": options, "keep_alive": config.LLM_KEEP_ALIVE}
    if schema:
        payload["format"] = schema
    return payload


def _complete(messages, temperature, num_predict, schema=None, repeat_penalty=None,
              timeout=None) -> str:
    """Texte complet de la reponse."""
    try:
        if config.LLM_BACKEND == "llama":
            data = llm_server.SERVER.post("/v1/chat/completions", _llama_body(
                messages, temperature, num_predict, schema, repeat_penalty), timeout=timeout)
            return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        resp = _post("/api/chat", _ollama_payload(
            messages, temperature, num_predict, schema, repeat_penalty), timeout=timeout)
        return (resp.get("message") or {}).get("content", "")
    except llm_server.LlamaServerError as exc:
        raise LLMError(str(exc)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise _http_error(exc) from exc


def extract_json(text: str):
    """Extrait un objet/tableau JSON d'une reponse brute (le 3B emballe souvent
    sa reponse dans des backticks ou du texte)."""
    if not text:
        raise LLMError("Réponse vide du modèle")
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
    raise LLMError("Réponse JSON invalide : %s" % raw[:300], raw=raw)


def chat_json(system: str, user: str, schema: dict, model: str = None,
              temperature: float = 0.3, num_predict: int = 1200,
              timeout: int = None) -> dict:
    """Appel avec schema JSON : la reponse est un dict/list deja parse.
    (model : ignore, conserve pour compatibilite ; voir config.LLM_MODEL.)"""
    content = _complete(_messages(system, user), temperature, num_predict, schema=schema,
                        repeat_penalty=1.05, timeout=timeout)
    if not content.strip():
        raise LLMError("Le modèle n'a rien répondu (texte envoyé trop long ?)")
    return extract_json(content)


def chat_text(system: str, user: str, model: str = None,
              temperature: float = 0.6, num_predict: int = 900) -> str:
    return _complete(_messages(system, user), temperature, num_predict).strip()


def chat_stream(system: str, user: str, model: str = None,
                temperature: float = 0.6, num_predict: int = 900):
    """Generateur de fragments de texte (pour le chat en flux)."""
    messages = _messages(system, user)
    try:
        if config.LLM_BACKEND == "llama":
            for data in llm_server.SERVER.stream("/v1/chat/completions", _llama_body(
                    messages, temperature, num_predict, stream=True)):
                piece = ((data.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if piece:
                    yield piece
            return
        resp = _post("/api/chat", _ollama_payload(messages, temperature, num_predict,
                                                  stream=True), stream=True)
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
                    raise LLMError(data["error"])
                piece = (data.get("message") or {}).get("content", "")
                if piece:
                    yield piece
                if data.get("done"):
                    break
    except llm_server.LlamaServerError as exc:
        raise LLMError(str(exc)) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise _http_error(exc) from exc


# -- memoire et etat ---------------------------------------------------------
def loaded_models() -> list:
    """Modeles Ollama actuellement en memoire (noms)."""
    try:
        return [m.get("name", "") for m in _get("/api/ps", timeout=3).get("models", [])]
    except Exception:
        return []


def unload(model: str = None) -> bool:
    """Rend la memoire du modele (bouton Quitter, avant un rendu...).
    llama.cpp : arret du serveur. Ollama : rien a faire si le modele n'est
    pas charge (une requete keep_alive=0 le chargerait d'abord)."""
    if config.LLM_BACKEND == "llama":
        llm_server.SERVER.stop()
        return True
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
    info = {"up": False, "backend": config.LLM_BACKEND, "model": config.LLM_MODEL,
            "models": [], "ctx": config.LLM_NUM_CTX}
    if config.LLM_BACKEND == "llama":
        # "Pret" = installe : le serveur demarre a la premiere demande.
        info["up"] = llm_server.SERVER.installed()
        info["running"] = llm_server.SERVER.running()
        return info
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

"""
blueprints/ai_proxy.py
Proxy to Ollama — runs AI models locally on your own machine.
No API key needed. No rate limits. Completely free.

SETUP (one time):
  1. Download Ollama from https://ollama.com and install it
  2. Open a terminal and run:  ollama pull llama3.2
  3. Start your Flask app — AI features will work automatically

Ollama runs at http://localhost:11434 by default.
You can change the model or URL in your .env file:
  OLLAMA_MODEL=llama3.2
  OLLAMA_URL=http://localhost:11434
"""
import os
import json
import logging
import urllib.request as _req
import urllib.error   as _err

from flask import Blueprint, request, jsonify
from utils.helpers import login_required

logger = logging.getLogger(__name__)

ai_bp = Blueprint("ai", __name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL      = os.environ.get("OLLAMA_MODEL", "llama3.2")


@ai_bp.route("/api/ai", methods=["POST"])
@login_required
def ai_proxy():
    data   = request.get_json() or {}
    prompt = data.get("prompt", "").strip()
    system = data.get("system", "You are a helpful civic assistant.")

    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    # Combine system + user prompt (Ollama /api/generate format)
    full_prompt = f"{system}\n\n{prompt}"

    payload = json.dumps({
        "model":  MODEL,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 1024,
        },
    }).encode("utf-8")

    url = f"{OLLAMA_URL}/api/generate"
    req = _req.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _req.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        text = result.get("response", "").strip()
        return jsonify({"text": text})

    except _err.URLError as exc:
        logger.error("Ollama not reachable: %s", exc)
        return jsonify({
            "error": "Ollama is not running. Open a terminal and run: ollama serve"
        }), 503

    except Exception as exc:
        logger.error("AI proxy failed: %s", exc)
        return jsonify({"error": f"Request failed: {exc}"}), 500


@ai_bp.route("/api/ai/status", methods=["GET"])
def ai_status():
    """Check if Ollama is running and which models are available."""
    try:
        req = _req.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with _req.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m["name"] for m in data.get("models", [])]
        return jsonify({
            "status":        "online",
            "current_model": MODEL,
            "models":        models,
        })
    except Exception:
        return jsonify({
            "status":  "offline",
            "message": "Ollama is not running. Run: ollama serve",
        }), 503

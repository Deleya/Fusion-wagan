import requests
from django.conf import settings

def ask(messages: list, model: str = "llama3.2") -> str:
    """Envoie une conversation, retourne le texte de réponse."""
    resp = requests.post(
        f"{settings.BAKELI_AI_URL}/v1/chat",
        headers={"Authorization": f"Bearer {settings.BAKELI_AI_KEY}"},
        json={"model": model, "messages": messages},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]

def ask_with_file(prompt: str, filepath: str, model: str = "llama3.2") -> str:
    """Envoie un fichier avec un prompt."""
    with open(filepath, "rb") as f:
        resp = requests.post(
            f"{settings.BAKELI_AI_URL}/v1/chat/file",
            headers={"Authorization": f"Bearer {settings.BAKELI_AI_KEY}"},
            data={"prompt": prompt, "model": model},
            files={"file": f},
            timeout=180,
        )
    return resp.json()["message"]["content"]
import requests
import logging
from django.conf import settings
from .whatsapp_service import envoyer_alerte_whatsapp

logger = logging.getLogger(__name__)

def envoyer_alerte_discord(phone_number, message_text, sentiment_score, derniers_messages=None, sentiment_label='negative'):
    """
    Envoie un Embed riche sur un salon Discord configuré via un Webhook.
    
    Args:
        phone_number (str): Le numéro WhatsApp du client.
        message_text (str): Le contenu du dernier message négatif.
        sentiment_score (float): Le score de sentiment.
        derniers_messages (list): Facultatif, liste de l'historique récent de la conversation.
        sentiment_label (str): 'negative' ou 'positive'.
    """
    webhook_url = settings.DISCORD_WEBHOOK_URL
    if not webhook_url:
        logger.warning("⚠️ Discord Webhook non configuré (DISCORD_WEBHOOK_URL absent dans .env). Alerte Discord ignorée.")
        return False

    if sentiment_label == 'positive':
        embed_color = 3066993  # Vert
        title = "🎯 HOT LEAD : PROSPECT CHAUD (CRM Bot)"
        desc = "Le prospect exprime une intention claire de s'inscrire ou de payer."
        analyse = f"🟢 **Positif** (Confiance: `{sentiment_score}`)"
    elif sentiment_label == 'lost_lead':
        embed_color = 16776960  # Jaune
        title = "⚠️ PROSPECT PERDU / DÉSINTÉRESSÉ"
        desc = "Le prospect souhaite abandonner, trouve le prix trop cher, ou a dit au revoir."
        analyse = f"🟡 **Désintérêt** (Confiance: `{sentiment_score}`)"
    elif sentiment_label == 'bot_stuck':
        embed_color = 16744192  # Orange
        title = "🚨 IMPASSE BOT : INTERVENTION REQUISE"
        desc = "Le bot ne sait pas répondre, tourne en rond, ou le prospect a demandé un humain."
        analyse = f"🟠 **Bot Bloqué** (Confiance: `{sentiment_score}`)"
    else:
        # Fallback pour 'angry' et 'negative' (Rouge)
        embed_color = 15158332
        title = "🔥 CLIENT MÉCONTENT / PLAINTE"
        desc = "Une forte insatisfaction ou une plainte a été détectée."
        analyse = f"🔴 **Négatif / Fâché** (Confiance: `{sentiment_score}`)"
    
    # Construction du corps de l'embed
    embed = {
        "title": title,
        "description": desc,
        "color": embed_color,
        "fields": [
            {
                "name": "📱 Numéro de téléphone",
                "value": f"`{phone_number}`",
                "inline": True
            },
            {
                "name": "📊 Analyse Globale",
                "value": analyse,
                "inline": True
            },
            {
                "name": "💬 Dernier message reçu",
                "value": f"\"{message_text}\"",
                "inline": False
            }
        ],
        "footer": {
            "text": "Système d'Alerte WhatsApp-CRM • Résilience Active"
        }
    }

    # Intégration de l'historique récent si disponible
    if derniers_messages and len(derniers_messages) > 1:
        historique_str = ""
        for idx, msg in enumerate(derniers_messages, 1):
            # Tronquer les messages très longs
            msg_tronque = msg[:80] + "..." if len(msg) > 80 else msg
            # Mettre en valeur le dernier message
            prefix = "👉" if idx == len(derniers_messages) else "•"
            historique_str += f"{prefix} **Msg {idx}** : {msg_tronque}\n"
        
        embed["fields"].append({
            "name": "📜 Historique récent de la conversation",
            "value": historique_str,
            "inline": False
        })

    # Corps complet de la requête Webhook
    # Permet d'ajouter une mention discrète si souhaitée via l'env
    mention_str = getattr(settings, 'DISCORD_MENTION', '')
    payload = {
        "content": mention_str if mention_str else None,
        "embeds": [embed]
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        if response.status_code not in [200, 204]:
            logger.error(f"❌ Erreur lors de l'envoi Discord Webhook (Code: {response.status_code}): {response.text}")
            raise Exception(f"Discord API error status {response.status_code}")
        
        logger.info(f"✅ Alerte Discord envoyée avec succès pour le client {phone_number}.")
        return True
    except Exception as e:
        logger.exception(f"❌ Exception lors de l'envoi de l'alerte Discord: {e}")
        raise e

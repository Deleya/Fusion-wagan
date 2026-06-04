from celery import shared_task
from django.conf import settings
from .nlp_utils import analyser_message_whatsapp, analyser_sentiment_global
from .agent_brain import generer_reponse
from .whatsapp_sender import send_whatsapp_message, envoyer_boutons_amorce
from .models import Message



@shared_task(bind=True, max_retries=3, acks_late=True)
def process_message_async(self, phone_number, message_text, message_type, message_id, raw_webhook_data):
    """
    Tâche async: Analyse sentiment + génère réponse + envoie WhatsApp.

    Args:
        phone_number: Numéro WhatsApp du client
        message_text: Texte du message
        message_type: Type (text, image, video, etc.)
        message_id: UUID du message en DB
        raw_webhook_data: Données brutes du webhook
    """
    try:
        sentiment_label = None
        sentiment_score = None
        derniers_messages = None

        print(f"🔄 Traitement async commencé: {phone_number}")

        # 0. Vérifier si le message a déjà été traité
        message_obj = Message.objects.filter(id=message_id).first()
        if not message_obj:
            print(f"❌ Message introuvable au moment du traitement: {message_id}")
            return
        if message_obj.processed:
            print(f"⚠️  Message déjà traité: {message_id}")
            return

        # 0.5. Amorce de discussion (Menu interactif)
        mots_amorce = ['bonjour', 'salut', 'hello', 'menu', 'aide', 'coucou', 'start']
        if message_type == 'text' and message_text.lower().strip() in mots_amorce:
            print(f"👋 Amorce détectée, envoi du menu interactif à {phone_number}")
            try:
                envoyer_boutons_amorce(phone_number)
            except Exception as e:
                print(f"❌ Erreur envoi amorce: {e}")
            
            # On met à jour la base de données comme "traité"
            try:
                message_obj = Message.objects.get(id=message_id)
                message_obj.processed = True
                message_obj.save()
            except:
                pass
            return # On s'arrête là, pas besoin de Groq pour un simple "bonjour"

        # 1. Analyser sentiment GLOBAL (basé sur les 4 derniers messages de la conversation)
        if message_type in ['text', 'interactive']:
            try:
                # Récupérer les 4 derniers messages texte du client (incluant le message actuel)
                derniers_messages = list(
                    Message.objects.filter(
                        phone_number=phone_number,
                        message_text__isnull=False
                    ).exclude(
                        message_text=''
                    ).order_by('-timestamp')[:4].values_list('message_text', flat=True)
                )
                # Ajouter le message actuel s'il n'est pas encore en DB avec le bon texte
                if message_text not in derniers_messages:
                    derniers_messages.insert(0, message_text)
                # Inverser pour avoir l'ordre chronologique (du plus ancien au plus récent)
                derniers_messages = derniers_messages[::-1]
                
                print(f"📊 Messages pour analyse globale ({len(derniers_messages)}): {[m[:30]+'...' if len(m)>30 else m for m in derniers_messages]}")
                
                resultat_ia = analyser_sentiment_global(derniers_messages)
                sentiment_label = resultat_ia['label']
                sentiment_score = resultat_ia['score']
                print(f"📊 Sentiment GLOBAL: {sentiment_label} ({sentiment_score})")
            except Exception as e:
                print(f"❌ Erreur Sentiment Analysis: {e}. Valeurs par défaut appliquées.")
                sentiment_label = "neutral"
                sentiment_score = 0.5

        # 2. Générer réponse IA
        reponse_ia = generer_reponse(
            message_utilisateur=message_text,
            numero_tel=phone_number,
            sentiment=sentiment_label,
            score=sentiment_score
        )
        print(f"🧠 Réponse IA générée: {len(reponse_ia)} chars")

        # 3. Envoyer réponse WhatsApp
        if reponse_ia:
            try:
                result = send_whatsapp_message(phone_number, reponse_ia)
                print(f"📤 Message WhatsApp envoyé: {result}")
            except Exception as e:
                print(f"❌ Impossible d'envoyer le WhatsApp final: {e}")

        # 3.5. Déclenchement de la tâche d'alerte asynchrone découplée
        if sentiment_label == 'negative':
            try:
                send_admin_alerts_async.delay(
                    phone_number=phone_number,
                    message_text=message_text,
                    sentiment_score=float(sentiment_score) if sentiment_score is not None else 0.5,
                    derniers_messages=derniers_messages
                )
                print(f"🚨 Tâche d'alerte asynchrone planifiée pour le client mécontent {phone_number}")
            except Exception as e:
                print(f"❌ Impossible de planifier la tâche d'alerte: {e}")

        # 4. Mettre à jour le message en DB
        try:
            message_obj = Message.objects.get(id=message_id)
            message_obj.sentiment_label = sentiment_label
            message_obj.sentiment_score = sentiment_score
            message_obj.processed = True
            message_obj.save()
        except Exception as e:
            print(f"❌ Erreur lors de la sauvegarde en DB: {e}")

        print(f"✅ Message traité avec succès: {phone_number}")

    except Message.DoesNotExist:
        print(f"❌ Message non trouvé: {message_id}")
    except Exception as e:
        print(f"❌ Erreur traitement async: {e}")
        # Retry avec backoff exponentiel (3s, 6s, 12s)
        try:
            self.retry(exc=e, countdown=3 ** self.request.retries)
        except Exception as retry_e:
            print(f"❌ Retry échoué: {retry_e}")
            # Marquer comme erreur en DB
            try:
                message_obj = Message.objects.get(id=message_id)
                message_obj.processed = False
                message_obj.save()
            except:
                pass


@shared_task(bind=True, max_retries=3, acks_late=True)
def send_admin_alerts_async(self, phone_number, message_text, sentiment_score, derniers_messages=None):
    """
    Tâche Celery pour envoyer les alertes sur WhatsApp et Discord de manière isolée et résiliente.
    """
    print(f"🚨 Début d'envoi des alertes pour {phone_number}...")
    whatsapp_error = None
    discord_error = None

    # 1. Envoi Alerte WhatsApp
    try:
        from .whatsapp_service import envoyer_alerte_whatsapp
        message_alerte = f"⚠️ *ALERTE CLIENT MÉCONTENT*\nNuméro: {phone_number}\nMessage: {message_text}"
        envoyer_alerte_whatsapp(message_alerte, settings.WHATSAPP_ADMIN_NUMBER)
        print(f"✅ Alerte WhatsApp envoyée avec succès à {settings.WHATSAPP_ADMIN_NUMBER}")
    except Exception as e:
        print(f"❌ Échec de l'alerte WhatsApp: {e}")
        whatsapp_error = e

    # 2. Envoi Alerte Discord
    try:
        from .alerts import envoyer_alerte_discord
        envoyer_alerte_discord(
            phone_number=phone_number,
            message_text=message_text,
            sentiment_score=sentiment_score,
            derniers_messages=derniers_messages
        )
    except Exception as e:
        print(f"❌ Échec de l'alerte Discord: {e}")
        discord_error = e

    # Relancer si au moins une erreur s'est produite
    if whatsapp_error or discord_error:
        erreurs = []
        if whatsapp_error:
            erreurs.append(f"WhatsApp: {whatsapp_error}")
        if discord_error:
            erreurs.append(f"Discord: {discord_error}")
        erreur_msg = " & ".join(erreurs)
        print(f"⚠️ Relance de la tâche d'alerte en raison des erreurs: {erreur_msg}")
        try:
            self.retry(exc=Exception(erreur_msg), countdown=5 ** self.request.retries)
        except Exception as retry_e:
            print(f"❌ Impossible de planifier le retry de l'alerte: {retry_e}")

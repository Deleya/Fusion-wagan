from celery import shared_task
from django.conf import settings
from .nlp_utils import analyser_message_whatsapp, analyser_sentiment_global
from .agent_brain import generer_reponse, generer_amorce
from .whatsapp_sender import send_whatsapp_message
from .models import Message

# Mappe les titres de boutons WhatsApp vers un label de sentiment direct.
# Les clés correspondent aux champs 'title' extraits dans extract_message_data() (views.py).
# Cela évite un appel LLM inutile et capture les signaux d'intention forts sans ambiguïté.
BUTTON_SENTIMENT_MAP = {
    "🚀 Je veux me former": "positive",
    "❓ J'ai une question": "neutral",
    "📞 Être rappelé(e)": "positive",
}


# Ordre de gravité des labels d'alerte (plus le chiffre est haut, plus c'est grave).
# Utilisé pour court-circuiter le cooldown si la situation s'aggrave.
_LABEL_GRAVITE = {'lost_lead': 1, 'bot_stuck': 2, 'angry': 3}


def should_send_alert(phone_number: str, new_label: str, cooldown_minutes: int = 30) -> bool:
    """
    Détermine si une alerte doit être envoyée pour ce prospect.

    Retourne True si :
    - C'est le premier message urgent de ce prospect (pas de précédent en DB), OU
    - La gravité a AUGMENTÉ (ex: lost_lead → angry) — cooldown ignoré, urgence prioritaire, OU
    - Le label a changé ET le cooldown est expiré.

    Retourne False si :
    - Le label est identique au précédent ET cooldown actif (doublon simple), OU
    - Le label a changé mais vers la même gravité ou moins grave ET cooldown actif.
    """
    from django.utils import timezone
    from datetime import timedelta

    # Dernier message avec un label déjà attribué pour ce prospect
    dernier_msg = Message.objects.filter(
        phone_number=phone_number,
        sentiment_label__isnull=False
    ).order_by('-timestamp').first()

    if not dernier_msg:
        return True  # Premier message urgent → toujours alerter

    label_precedent = dernier_msg.sentiment_label
    label_changed = label_precedent != new_label

    # Montée en gravité → alerter TOUJOURS, cooldown ignoré
    gravite_precedente = _LABEL_GRAVITE.get(label_precedent, 0)
    gravite_nouvelle = _LABEL_GRAVITE.get(new_label, 0)
    if gravite_nouvelle > gravite_precedente:
        print(f"🚨 Montée en gravité détectée: {label_precedent} → {new_label} (cooldown ignoré)")
        return True

    # Vérifier le cooldown : une alerte a-t-elle déjà été envoyée dans les X dernières minutes ?
    dernier_msg_alerte = Message.objects.filter(
        phone_number=phone_number,
        sentiment_label__in=['lost_lead', 'bot_stuck', 'angry'],
    ).order_by('-timestamp').first()

    if dernier_msg_alerte:
        if (timezone.now() - dernier_msg_alerte.timestamp) < timedelta(minutes=cooldown_minutes):
            return False  # Cooldown actif et pas de montée en gravité → pas d'alerte

    return label_changed


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

        # 0. Vérifier si le message a déjà été traité (Concurrence / Retry Meta)
        # select_for_update() pose un verrou SQL sur la ligne le temps de la vérification.
        # Si deux webhooks identiques arrivent en même temps, le 2e attendra que le 1er
        # ait fini de poser processed=True avant de lire la valeur → plus de doublons.
        from django.db import transaction
        with transaction.atomic():
            message_obj = Message.objects.select_for_update().filter(id=message_id).first()
            if not message_obj:
                print(f"❌ Message introuvable au moment du traitement: {message_id}")
                return
            if message_obj.processed:
                print(f"⚠️  Message déjà traité (ignorer doublon): {message_id}")
                return
            # Verrouillage immédiat pour éviter les doublons de webhook
            message_obj.processed = True
            message_obj.save()

        # --- Commande de test pour le développeur ---
        if message_type == 'text' and message_text.strip().lower() == 'reset':
            Message.objects.filter(phone_number=phone_number).exclude(id=message_id).delete()
            try:
                from .models import ConversationState
                ConversationState.objects.filter(phone_number=phone_number).delete()
            except Exception as e:
                pass
            send_whatsapp_message(phone_number, "🔄 Session et mémoire IA réinitialisées. Vous pouvez tester l'amorce depuis zéro.")
            return

        # --- Amorce IA : premier message ou nouvelle session (après 12h d'inactivité)
        from django.utils import timezone
        from datetime import timedelta
        
        # La commande 'reset' est exclue : en cas de course avec un retry Meta,
        # sa ligne peut survivre en base et ferait croire à une session active.
        dernier_message_avant = Message.objects.filter(
            phone_number=phone_number,
            processed=True
        ).exclude(id=message_id).exclude(message_text__iexact='reset').order_by('-timestamp').first()

        premier_message = False
        if not dernier_message_avant:
            premier_message = True
        elif (timezone.now() - dernier_message_avant.timestamp) > timedelta(hours=12):
            premier_message = True

        # Une salutation PURE ("bonjour", "slt", "salam"...) = entame de
        # conversation → panel d'amorce SYSTÉMATIQUE, même en session active.
        from .nlp_utils import est_salutation_pure
        est_entame = premier_message or (
            message_type == 'text' and est_salutation_pure(message_text)
        )

        if est_entame and message_type == 'text':
            raison = "premier message" if premier_message else "salutation d'entame"
            print(f"👋 Entame détectée ({raison}) pour {phone_number} — envoi du panel d'amorce")
            try:
                from .whatsapp_sender import envoyer_boutons_amorce
                envoyer_boutons_amorce(phone_number)
            except Exception as e:
                print(f"❌ Erreur envoi boutons amorce: {e}")
                # Ne JAMAIS laisser le prospect sans réponse : fallback texte.
                try:
                    reponse_secours = generer_amorce(message_text, phone_number)
                    send_whatsapp_message(phone_number, reponse_secours)
                    print("✅ Fallback amorce texte envoyé")
                except Exception as e2:
                    print(f"❌ Fallback amorce texte impossible: {e2}")
            # L'amorce étant le point de sortie, le message reste 'processed'
            return  # Entame traitée par l'amorce, on s'arrête là

        # 1. Analyser sentiment GLOBAL (basé sur l'historique complet)
        sentiment_label = "neutral"
        sentiment_score = 0.5
        derniers_messages = None
        
        if message_type == 'text':
            try:
                from .models import ConversationState
                state = ConversationState.objects.filter(phone_number=phone_number).first()
                if state and state.history:
                    # Prendre les 6 derniers échanges
                    derniers_echanges = state.history[-6:]
                    derniers_messages = [f"{msg['role'].upper()}: {msg['content']}" for msg in derniers_echanges]
                    # L'historique n'est enrichi qu'APRÈS la génération de la réponse
                    # (agent_brain.ajouter_au_historique) : le message en cours de
                    # traitement n'y figure pas encore. Sans cet ajout, le LLM analyse
                    # la conversation SANS le dernier message du prospect.
                    derniers_messages.append(f"USER: {message_text}")
                else:
                    derniers_messages = [f"USER: {message_text}"]

                print(f"📊 Analyse sentiment sur les {len(derniers_messages)} dernier(s) échange(s)")

                # Statut CRM persistant injecté dans le prompt (détection des retournements)
                statut_precedent = state.statut_prospect if state else None

                resultat_ia = analyser_sentiment_global(derniers_messages, statut_precedent=statut_precedent)
                sentiment_label = resultat_ia['label']
                sentiment_score = resultat_ia['score']
                print(f"📊 Sentiment GLOBAL: {sentiment_label} ({sentiment_score})")
            except Exception as e:
                print(f"❌ Erreur Sentiment Analysis: {e}. Valeurs par défaut appliquées.")
        elif message_type == 'interactive':
            # Les boutons d'amorce ont un titre connu → on mappe directement sans appel LLM.
            bouton_label = BUTTON_SENTIMENT_MAP.get(message_text)
            if bouton_label:
                sentiment_label = bouton_label
                sentiment_score = 0.95
                print(f"🔘 Sentiment bouton détecté: '{message_text}' → {sentiment_label}")
            else:
                print(f"⏩ Bouton interactif non mappé (neutral par défaut): '{message_text}'")
        else:
            print(f"⏩ Type de message non analysé: {message_type} (neutral par défaut)")

        # 1.5. Machine à états : mise à jour du statut PERSISTANT du prospect.
        # Le sentiment du message est un signal instantané ; le statut prospect
        # est l'état CRM qui pilote le dashboard, les hot leads et les alertes.
        from .qualification import mettre_a_jour_statut_prospect, TRANSITION_RECUPERATION
        statut_prospect = sentiment_label
        transition = None
        try:
            statut_prospect, transition = mettre_a_jour_statut_prospect(
                phone_number, sentiment_label, sentiment_score
            )
        except Exception as e:
            print(f"❌ Erreur mise à jour statut prospect: {e}")

        # 2. Générer réponse IA
        reponse_ia, is_panne = generer_reponse(
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
        if is_panne:
            try:
                send_admin_alerts_async.delay(
                    phone_number=phone_number,
                    message_text=message_text,
                    sentiment_score=0.0,
                    sentiment_label='negative',
                    derniers_messages=None,
                    is_panne=True
                )
                print(f"🚨 Tâche d'alerte PANNE IA planifiée pour le numéro {phone_number}")
            except Exception as e:
                print(f"❌ Impossible de planifier la tâche d'alerte panne: {e}")
        elif transition == TRANSITION_RECUPERATION:
            # 🔥 Le signal commercial le plus précieux : un prospect perdu/mécontent
            # revient avec une intention positive. Pas de cooldown : événement rare
            # qui mérite une intervention humaine immédiate.
            try:
                send_admin_alerts_async.delay(
                    phone_number=phone_number,
                    message_text=message_text,
                    sentiment_score=float(sentiment_score) if sentiment_score is not None else 0.5,
                    sentiment_label='positive',
                    derniers_messages=derniers_messages,
                    is_panne=False,
                    is_recovery=True
                )
                print(f"🔥 Alerte PROSPECT RÉCUPÉRÉ planifiée pour {phone_number}")
            except Exception as e:
                print(f"❌ Impossible de planifier l'alerte de récupération: {e}")
        elif sentiment_label in ['lost_lead', 'bot_stuck', 'angry']:
            try:
                if should_send_alert(phone_number, sentiment_label):
                    send_admin_alerts_async.delay(
                        phone_number=phone_number,
                        message_text=message_text,
                        sentiment_score=float(sentiment_score) if sentiment_score is not None else 0.5,
                        sentiment_label=sentiment_label,
                        derniers_messages=derniers_messages,
                        is_panne=False
                    )
                    print(f"🚨 Tâche d'alerte asynchrone planifiée pour le client {sentiment_label} ({phone_number})")
                else:
                    print(f"⏭️ Alerte ignorée (cooldown 30 min ou label identique): {phone_number} [{sentiment_label}]")
            except Exception as e:
                print(f"❌ Impossible de planifier la tâche d'alerte: {e}")

        # 4. Mettre à jour le message en DB avec son sentiment
        try:
            message_obj.sentiment_label = sentiment_label
            message_obj.sentiment_score = sentiment_score
            message_obj.save()
        except Exception as e:
            print(f"❌ Erreur lors de la mise à jour sentiment DB: {e}")

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
def send_admin_alerts_async(self, phone_number, message_text, sentiment_score, sentiment_label='negative', derniers_messages=None, is_panne=False, is_recovery=False):
    """
    Tâche Celery pour envoyer les alertes sur WhatsApp et Discord de manière isolée et résiliente.
    """
    print(f"🚨 Début d'envoi des alertes pour {phone_number} (Panne={is_panne}, Récupération={is_recovery})...")
    whatsapp_error = None
    discord_error = None

    # 1. Envoi Alerte WhatsApp
    try:
        from .whatsapp_service import envoyer_alerte_whatsapp
        if is_panne:
            message_alerte = f"⚠️ *ALERTE PANNE IA*\nL'API Groq est injoignable.\nLe bot a utilisé le message de secours pour le numéro: {phone_number}\nMessage client: {message_text}"
        elif is_recovery:
            message_alerte = f"🔥 *PROSPECT RÉCUPÉRÉ — RAPPELER EN PRIORITÉ*\nCe prospect était perdu/mécontent et revient avec une intention d'inscription.\nNuméro: {phone_number}\nMessage: {message_text}"
        elif sentiment_label == 'lost_lead':
            message_alerte = f"⚠️ *PROSPECT PERDU / DÉSINTÉRESSÉ*\nLe prospect souhaite abandonner ou a dit au revoir.\nNuméro: {phone_number}\nMessage: {message_text}"
        elif sentiment_label == 'bot_stuck':
            message_alerte = f"🚨 *IMPASSE BOT : INTERVENTION REQUISE*\nLe bot tourne en rond ou le client demande un humain.\nNuméro: {phone_number}\nMessage: {message_text}"
        else:
            message_alerte = f"🔥 *CLIENT MÉCONTENT / PLAINTE*\nPlainte détectée.\nNuméro: {phone_number}\nMessage: {message_text}"
        envoyer_alerte_whatsapp(message_alerte, settings.WHATSAPP_ADMIN_NUMBER)
        print(f"✅ Alerte WhatsApp envoyée avec succès à {settings.WHATSAPP_ADMIN_NUMBER}")
    except Exception as e:
        print(f"❌ Échec de l'alerte WhatsApp: {e}")
        whatsapp_error = e

    # 2. Envoi Alerte Discord
    try:
        from .alerts import envoyer_alerte_discord
        if not is_panne:
            envoyer_alerte_discord(
                phone_number=phone_number,
                message_text=message_text,
                sentiment_score=sentiment_score,
                derniers_messages=derniers_messages,
                sentiment_label=sentiment_label
            )
        else:
            # On pourrait avoir une alerte Discord spécifique pour la panne, on l'omet ou on l'envoie avec un titre différent.
            # Pour l'instant on utilise la même fonction mais on pourrait l'adapter dans alerts.py
            envoyer_alerte_discord(
                phone_number=phone_number,
                message_text=f"PANNE IA: {message_text}",
                sentiment_score=0.0,
                derniers_messages=["L'API IA EST EN PANNE !"],
                sentiment_label='negative'
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

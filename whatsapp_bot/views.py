from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
from django.conf import settings
from .models import Message, BotKnowledge
from .celery_tasks import process_message_async
from django.utils import timezone


def extract_message_data(webhook_data):
    """
    Extrait le numéro de téléphone, le texte du message et le type du webhook WhatsApp.
    Retourne un tuple (phone_number, message_text, message_type) ou (None, None, None) si extraction échouée.
    """
    try:
        entry = webhook_data.get('entry', [{}])[0]
        changes = entry.get('changes', [{}])[0]
        value = changes.get('value', {})

        # Vérifier si c'est un nouveau message
        if 'messages' not in value:
            return None, None, None, None

        message_obj = value['messages'][0]
        phone_number = message_obj.get('from')
        message_type = message_obj.get('type')
        external_message_id = message_obj.get('id')

        if not phone_number:
            return None, None, None, None

        # Extraire le texte selon le type de message
        message_text = None

        if message_type == 'text':
            message_text = message_obj.get('text', {}).get('body', '')

        elif message_type == 'interactive':
            # Si l'utilisateur a cliqué sur un bouton
            interactive_obj = message_obj.get('interactive', {})
            interactive_type = interactive_obj.get('type')
            if interactive_type == 'button_reply':
                message_text = interactive_obj.get('button_reply', {}).get('title', '')
                print(f"🔘 Bouton cliqué : {message_text}")
            elif interactive_type == 'list_reply':
                message_text = interactive_obj.get('list_reply', {}).get('title', '')
            else:
                message_text = "[Interaction reçue]"

        elif message_type == 'image':
            # Récupérer la légende si elle existe
            message_text = message_obj.get('image', {}).get('caption')
            if not message_text:
                message_text = "[Image reçue sans légende]"

        elif message_type == 'video':
            message_text = message_obj.get('video', {}).get('caption')
            if not message_text:
                message_text = "[Vidéo reçue sans légende]"

        elif message_type == 'audio':
            message_text = "[Message audio reçu]"

        elif message_type == 'document':
            # Récupérer le nom du document si possible
            filename = message_obj.get('document', {}).get('filename', 'document')
            message_text = f"[Document reçu: {filename}]"

        elif message_type == 'location':
            message_text = "[Localisation reçue]"

        else:
            message_text = f"[Type de message non géré: {message_type}]"

        return phone_number, message_text if message_text else "", message_type, external_message_id

    except (KeyError, IndexError, TypeError) as e:
        print(f"❌ Erreur lors de l'extraction du message: {e}")
        return None, None, None, None


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    print(f"\n{'='*90}")
    print(f"REQUÊTE REÇUE - Méthode: {request.method} | Path: {request.path}")
    print(f"{'='*90}")

    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        print(f"GET - Verify Token reçu: {token}")

        if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
            print("✅ Webhook vérifié avec succès par Meta !")
            return JsonResponse(int(challenge), safe=False, status=200)
        
        print("❌ Verify token invalide")
        return JsonResponse({"error": "Invalid verify token"}, status=403)

    # === POST ===
    try:
        data = json.loads(request.body)
        print("✅ POST REÇU AVEC SUCCÈS !")

        phone_number, message_text, message_type, external_message_id = extract_message_data(data)

        if phone_number and message_text:
            if external_message_id:
                existing_message = Message.objects.filter(whatsapp_message_id=external_message_id).first()
                if existing_message:
                    print(f"⚠️  Message déjà reçu : {external_message_id}. Aucune nouvelle tâche créée.")
                else:
                    message_obj = Message.objects.create(
                        phone_number=phone_number,
                        message_text=message_text,
                        raw_webhook_data=data,
                        whatsapp_message_id=external_message_id,
                        processed=False
                    )
                    print(f"✅ Message créé en DB: {message_obj.id}")

                    # 2. Queue la tâche async (NE PAS ATTENDRE)
                    try:
                        process_message_async.delay(
                            phone_number=phone_number,
                            message_text=message_text,
                            message_type=message_type,
                            message_id=str(message_obj.id),
                            raw_webhook_data=data
                        )
                        print(f"⏳ Tâche queued pour traitement async")
                    except Exception as celery_err:
                        print(f"❌ Erreur Redis/Celery (message non traité) : {celery_err}")
            else:
                message_obj = Message.objects.create(
                    phone_number=phone_number,
                    message_text=message_text,
                    raw_webhook_data=data,
                    processed=False
                )
                print(f"✅ Message créé en DB sans ID externe: {message_obj.id}")

                try:
                    process_message_async.delay(
                        phone_number=phone_number,
                        message_text=message_text,
                        message_type=message_type,
                        message_id=str(message_obj.id),
                        raw_webhook_data=data
                    )
                    print(f"⏳ Tâche queued pour traitement async")
                except Exception as celery_err:
                    print(f"❌ Erreur Redis/Celery (message non traité) : {celery_err}")
        else:
            print("⚠️  Aucun message à traiter")

        print(f"{'='*90}\n")

        # 3. Répondre IMMÉDIATEMENT (< 0.2s) sans attendre le traitement
        return JsonResponse({"status": "received"}, status=200)

    except json.JSONDecodeError:
        print("❌ Erreur : Le body n'est pas du JSON valide")
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        print(f"❌ Erreur inattendue : {e}")
        # Toujours retourner 200 à WhatsApp pour éviter les retries en boucle
        return JsonResponse({"status": "error_acknowledged"}, status=200)


def dashboard_api(request):
    qs = Message.objects.all()
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    from django.utils.dateparse import parse_datetime
    if start_date:
        parsed_start = parse_datetime(start_date)
        if parsed_start:
            qs = qs.filter(timestamp__gte=parsed_start)
    if end_date:
        parsed_end = parse_datetime(end_date)
        if parsed_end:
            qs = qs.filter(timestamp__lte=parsed_end)
            
    total = qs.count()
    utilisateurs = qs.values('phone_number').distinct().count()
    pending = qs.filter(processed=False).count()
    
    users_latest_sentiment = {}
    user_messages = {}
    
    for msg in qs.order_by('timestamp'):
        if msg.phone_number not in user_messages:
            user_messages[msg.phone_number] = []
        user_messages[msg.phone_number].append(msg)
        
        if msg.sentiment_label:
            users_latest_sentiment[msg.phone_number] = msg.sentiment_label
            
    positifs = list(users_latest_sentiment.values()).count('positive')
    negatifs = list(users_latest_sentiment.values()).count('negative')
    neutres = list(users_latest_sentiment.values()).count('neutral')
    
    nb_analyses = positifs + negatifs + neutres
    
    p_positif = round((positifs / nb_analyses * 100), 1) if nb_analyses > 0 else 0
    p_negatif = round((negatifs / nb_analyses * 100), 1) if nb_analyses > 0 else 0
    p_neutre = round((neutres / nb_analyses * 100), 1) if nb_analyses > 0 else 0
    
    # ===== ANALYSE DE CONVERSION APPROFONDIE =====
    # Un prospect est considéré "converti" UNIQUEMENT si :
    # 1. Son dernier sentiment est "positive" (il finit convaincu)
    # 2. Il a au moins 2 messages analysés (pas un simple "bonjour" positif)
    # 3. On compte TOUS les messages échangés avant d'atteindre
    #    le premier message "positive" qui est MAINTENU jusqu'à la fin
    #    (= pas un faux positif suivi d'un retour en neutral/negative)
    
    conversion_counts = []
    nb_prospects_convertis = 0
    
    for phone, msgs in user_messages.items():
        # Extraire seulement les messages qui ont un sentiment analysé
        sentiments_timeline = []
        for i, m in enumerate(msgs):
            if m.sentiment_label:
                sentiments_timeline.append({
                    'index': i + 1,  # position dans la conversation (1-based)
                    'label': m.sentiment_label,
                    'score': m.sentiment_score or 0.5
                })
        
        if len(sentiments_timeline) < 2:
            continue  # Pas assez de données pour juger une conversion
        
        dernier_sentiment = sentiments_timeline[-1]['label']
        
        if dernier_sentiment != 'positive':
            continue  # Le prospect n'a PAS fini positivement → pas converti
        
        # Trouver le point de bascule : le PREMIER "positive" 
        # à partir duquel il RESTE positif jusqu'à la fin
        point_de_bascule = None
        for idx in range(len(sentiments_timeline)):
            # Vérifier si à partir de cet index, tous les sentiments restants sont positifs
            remaining = sentiments_timeline[idx:]
            if all(s['label'] == 'positive' for s in remaining):
                point_de_bascule = sentiments_timeline[idx]['index']
                break
        
        if point_de_bascule is not None:
            nb_prospects_convertis += 1
            conversion_counts.append(point_de_bascule)
    
    avg_messages_to_convert = 0
    if conversion_counts:
        avg_messages_to_convert = round(sum(conversion_counts) / len(conversion_counts), 1)
    
    # Taux de conversion réel
    taux_conversion = 0
    if utilisateurs > 0:
        taux_conversion = round((nb_prospects_convertis / utilisateurs * 100), 1)
    
    # Liste détaillée des prospects
    prospects_list = []
    for phone, msgs in user_messages.items():
        first_contact = msgs[0].timestamp.isoformat()
        last_contact = msgs[-1].timestamp.isoformat()
        nb_msgs = len(msgs)
        sentiment = users_latest_sentiment.get(phone, 'inconnu')
        
        # Score de confiance moyen
        scores = [m.sentiment_score for m in msgs if m.sentiment_score is not None]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0
        
        # Statut lisible
        if sentiment == 'positive':
            statut = 'Chaud'
        elif sentiment == 'negative':
            statut = 'Alerte'
        elif sentiment == 'neutral':
            statut = 'Froid'
        else:
            statut = 'En attente'
        
        prospects_list.append({
            'phone': phone,
            'nb_messages': nb_msgs,
            'first_contact': first_contact,
            'last_contact': last_contact,
            'sentiment': sentiment,
            'statut': statut,
            'avg_score': avg_score,
        })
    
    # Trier par dernier contact desc
    prospects_list.sort(key=lambda x: x['last_contact'], reverse=True)
    
    context = {
        'total': total,
        'utilisateurs': utilisateurs,
        'positifs': positifs,
        'negatifs': negatifs,
        'neutres': neutres,
        'pending': pending,
        'nb_analyses': nb_analyses,
        'p_positif': p_positif,
        'p_negatif': p_negatif,
        'p_neutre': p_neutre,
        'avg_messages_to_convert': avg_messages_to_convert,
        'nb_prospects_convertis': nb_prospects_convertis,
        'taux_conversion': taux_conversion,
        'prospects_list': prospects_list,
        'now': timezone.now().isoformat()
    }
    return JsonResponse(context)


# ============================================================
# API CONFIGURATION DU BOT (Base de Connaissances Dynamique)
# ============================================================

@csrf_exempt
@require_http_methods(["GET", "PUT"])
def bot_config_api(request):
    """
    GET  /whatsapp/config/ — Retourne la configuration actuelle du bot.
    PUT  /whatsapp/config/ — Met à jour la configuration du bot.

    Utilisé par l'onglet 'Configuration' du Dashboard React.
    Le pattern Singleton BotKnowledge.get_solo() garantit
    qu'il n'y a jamais plus d'un enregistrement en base.
    """
    config = BotKnowledge.get_solo()

    if request.method == "GET":
        return JsonResponse({
            'etablissement_nom': config.etablissement_nom,
            'etablissement_description': config.etablissement_description,
            'etablissement_site': config.etablissement_site,
            'etablissement_inscription': config.etablissement_inscription,
            'catalogue_formations': config.catalogue_formations,
            'horaires': config.horaires,
            'updated_at': config.updated_at.isoformat(),
        })

    # PUT — Mise à jour de la configuration
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide.'}, status=400)

    # Champs autorisés à être modifiés (whitelist de sécurité)
    champs_autorises = [
        'etablissement_nom',
        'etablissement_description',
        'etablissement_site',
        'etablissement_inscription',
        'catalogue_formations',
        'horaires',
    ]

    for champ in champs_autorises:
        if champ in data:
            setattr(config, champ, data[champ])

    config.save()

    print(f"✅ BotKnowledge mis à jour par l'admin à {timezone.now()}")

    return JsonResponse({
        'success': True,
        'message': 'Configuration du bot mise à jour avec succès.',
        'updated_at': config.updated_at.isoformat(),
    })
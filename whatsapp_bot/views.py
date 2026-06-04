from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
from django.conf import settings
from .models import Message
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
        print("Payload complet reçu :")
        print(json.dumps(data, indent=2))

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
    total = Message.objects.count()
    utilisateurs = Message.objects.values('phone_number').distinct().count()
    pending = Message.objects.filter(processed=False).count()
    
    # NOUVELLE LOGIQUE : Satisfaction Globale par Utilisateur
    users_latest_sentiment = {}
    for msg in Message.objects.order_by('timestamp'):
        if msg.sentiment_label:
            users_latest_sentiment[msg.phone_number] = msg.sentiment_label
            
    positifs = list(users_latest_sentiment.values()).count('positive')
    negatifs = list(users_latest_sentiment.values()).count('negative')
    neutres = list(users_latest_sentiment.values()).count('neutral')
    
    nb_analyses = positifs + negatifs + neutres
    
    p_positif = round((positifs / nb_analyses * 100), 1) if nb_analyses > 0 else 0
    p_negatif = round((negatifs / nb_analyses * 100), 1) if nb_analyses > 0 else 0
    p_neutre = round((neutres / nb_analyses * 100), 1) if nb_analyses > 0 else 0
    
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
        'now': timezone.now().isoformat()
    }
    return JsonResponse(context)
#!/usr/bin/env bash
# Diagnostic prod du bot WhatsApp — session du lundi 2026-07-13.
# A lancer sur le serveur, A LA RACINE du projet, venv active :
#   bash scripts/diagnostic_prod.sh
# Pendant l'execution de la section 1, envoyer un message WhatsApp au bot
# avec `journalctl -u gunicorn -f` ouvert dans un autre terminal.

export DJANGO_SETTINGS_MODULE=wagan_project.settings.prod

echo "=================== 1. SERVICES & PROCESSUS ==================="
ps aux | grep -E 'gunicorn|celery' | grep -v grep
echo "--- Config systemd gunicorn (doit contenir DJANGO_SETTINGS_MODULE=...prod) ---"
systemctl cat gunicorn 2>/dev/null | grep -Ei 'Environment|ExecStart|WorkingDirectory' || echo "!! pas de service gunicorn trouve — quel est son nom ?"
echo "--- Config systemd celery (idem) ---"
systemctl cat 'celery*' 2>/dev/null | grep -Ei 'Environment|ExecStart|WorkingDirectory' || echo "!! pas de service celery trouve — worker lance a la main ?"

echo "=================== 2. SQLITE PARASITE ? ==================="
# Un db.sqlite3 modifie recemment = quelque chose tourne en settings.local
ls -l db.sqlite3 2>/dev/null || echo "pas de db.sqlite3 (bon signe)"

echo "=================== 3. MESSAGES VUS PAR LA BASE PROD ==================="
# total: 0 alors que des messages ont ete envoyes => Gunicorn ecrit en SQLite
# processed=False qui s'accumulent => le worker ne consomme pas
python manage.py shell -c "
from whatsapp_bot.models import Message
qs = Message.objects.order_by('-timestamp')
print('total:', qs.count())
for m in qs.values('phone_number', 'processed', 'timestamp')[:5]:
    print(m)
"

echo "=================== 4. WORKER CELERY ==================="
# process_message_async doit apparaitre dans 'registered'
celery -A wagan_project inspect registered 2>&1 | head -30
echo "--- File d'attente Redis (0 attendu ; qui grossit = personne ne consomme) ---"
redis-cli llen celery

echo "=================== 5. ENVOI META DEPUIS LE SERVEUR ==================="
# Teste le .env DU SERVEUR (401 = token serveur perime, #131030 = numero non autorise)
python manage.py shell -c "
from whatsapp_bot.whatsapp_sender import send_whatsapp_message, envoyer_boutons_amorce
print('texte:', send_whatsapp_message('221776746609', 'test diagnostic serveur'))
try:
    print('boutons:', envoyer_boutons_amorce('221776746609'))
except Exception as e:
    print('boutons ERREUR:', e)
"

echo "=================== FIN — copier TOUTE la sortie ==================="

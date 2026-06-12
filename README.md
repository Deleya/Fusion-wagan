# Wagan - Plateforme IA & Bot WhatsApp

Wagan est une plateforme complète intégrant un tableau de bord (Dashboard) web et un Bot WhatsApp intelligent (Assistant Bakeli). Le système gère l'orientation des prospects, l'analyse des sentiments en temps réel, et déclenche des alertes humaines automatiques pour maximiser le taux de conversion.

## 🚀 Fonctionnalités Principales

- **Bot WhatsApp (Assistant Bakeli)** : IA propulsée par Groq (LLaMA 3) pour interagir naturellement avec les prospects, cerner leurs besoins et les orienter vers la bonne formation.
- **Analyse de Sentiment** : Détection des prospects chauds (positifs) et des pertes d'intérêt (négatifs) via le pipeline d'analyse de contexte.
- **Dashboard Web (React)** : Suivi en temps réel du taux de conversion et du volume d'interactions.
- **Alertes Admin** : Notification instantanée sur WhatsApp et Discord lorsqu'un prospect nécessite l'intervention humaine d'un conseiller (Client mécontent) ou lors d'une panne technique de l'API.

## 🏗 Architecture

- **Backend** : Django / Django REST Framework
- **Frontend** : React / TypeScript / Vite / TailwindCSS
- **IA** : API Groq via la surcouche Bakeli AI (`openai/gpt-oss-20b`)
- **Tâches Asynchrones** : Celery + Redis (indispensable pour l'envoi de messages sans bloquer les webhooks)
- **Base de Données** : SQLite (Dev) / PostgreSQL (Prod)

## 🛠 Prérequis

- Python 3.10+
- Node.js 18+
- Redis Server (doit être lancé en arrière-plan)
- Un compte développeur Meta (WhatsApp Cloud API)
- Un compte Discord (pour le webhook d'alerte)

## ⚙️ Installation & Lancement

### 1. Backend (Django)

```bash
# Cloner le dépôt et aller dans le dossier
cd wagan

# Créer un environnement virtuel et l'activer
python -m venv venv
venv\Scripts\activate  # Sous Windows

# Installer les dépendances
pip install -r requirements.txt

# Créer le fichier d'environnement
cp .env.example .env
```

**Variables d'environnement requises (`.env`) :**
```env
# Django
DJANGO_SECRET_KEY=votre_cle_secrete
DJANGO_SECURITY=True
DATABASE=sqlite:///db.sqlite3

# APIs
BAKELI_AI_KEY=votre_cle_bakeli_groq
WHATSAPP_TOKEN=votre_token_meta
WHATSAPP_PHONE_NUMBER_ID=votre_phone_id
WHATSAPP_VERIFY_TOKEN=votre_webhook_verify_token
WHATSAPP_ADMIN_NUMBER=221770000000

# Discord
DISCORD_WEBHOOK_URL=votre_url_webhook
DISCORD_MENTION=<@ID_DU_ROLE>
```

**Lancement du backend :**
```bash
# Migrations et lancement du serveur
python manage.py migrate
python manage.py runserver
```

**Lancement de Celery (Nécessite Redis) :**
Dans un nouveau terminal :
```bash
venv\Scripts\activate
celery -A wagan_project worker --loglevel=info --pool=solo
```

### 2. Frontend (React)

```bash
cd wagan-front
npm install
npm run dev
```

## 📈 Logique Métier & Dashboard

L'algorithme de conversion (dans `views.py`) se base sur le dernier sentiment calculé pour chaque prospect :
- **🔥 Prospect Chaud (`positive`)** : Prospect fortement intéressé. Il augmente le *Taux de conversion*.
- **❄️ Prospect Froid (`neutral`)** : En phase d'exploration ou a simplement dit "Bonjour".
- **🚨 Alerte Humaine (`negative`)** : Désintérêt ou besoin hyper-spécifique non couvert. Le système notifie immédiatement les administrateurs via Discord et WhatsApp.

## 🔐 Sécurité & Audit

Lors de notre audit final, nous avons validé :
- L'isolation totale des clés privées via `.env`.
- Le découplage des envois réseau à Meta via Celery pour ne jamais dépasser le timeout de 3 secondes des Webhooks Meta.
- La robustesse du fallback de l'IA (en cas de panne de Groq, une alerte spécifique "PANNE IA" est envoyée au staff pour reprendre le relai manuellement).

---
*Ce projet a été bâti et documenté sur la branche `chrys`.*

from django.db import models
from django.utils import timezone
import uuid

class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    phone_number = models.CharField(max_length=20, db_index=True)
    message_text = models.TextField()
    
    sentiment_score = models.FloatField(null=True, blank=True)   # ex: 0.85
    sentiment_label = models.CharField(
        max_length=15,
        choices=[
            ('positive', 'Positive (Hot Lead)'),
            ('neutral', 'Neutral'),
            ('lost_lead', 'Lost Lead (Abandon)'),
            ('bot_stuck', 'Bot Stuck (Impasse)'),
            ('angry', 'Angry (Mécontent)'),
        ],
        null=True,
        blank=True
    )
    
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    
    # Pour garder le payload complet du webhook (très utile pour debug)
    raw_webhook_data = models.JSONField(null=True, blank=True)
    whatsapp_message_id = models.CharField(max_length=128, unique=True, null=True, blank=True, db_index=True)
    
    processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['phone_number', 'timestamp']),
        ]
        verbose_name = "Message WhatsApp"
        verbose_name_plural = "Messages WhatsApp"

    def __str__(self):
        return f"{self.phone_number} - {self.timestamp.strftime('%Y-%m-%d %H:%M')}"


class BotKnowledge(models.Model):
    """
    Modèle Singleton — Base de connaissances du bot WhatsApp.
    Un seul enregistrement existe en base. L'admin peut le modifier
    depuis le Dashboard pour mettre à jour le catalogue et les infos
    de l'établissement sans toucher au code source.
    """
    etablissement_nom = models.CharField(
        max_length=255,
        default="Bakeli School of Technology",
        verbose_name="Nom de l'établissement"
    )
    etablissement_description = models.TextField(
        default="Centre de formation professionnelle diplômante et certifiante au Sénégal.",
        verbose_name="Description de l'établissement"
    )
    etablissement_site = models.URLField(
        default="https://bakeli.tech",
        verbose_name="Site web"
    )
    etablissement_inscription = models.URLField(
        default="https://bakeli.tech/inscription",
        verbose_name="Lien d'inscription"
    )
    catalogue_formations = models.TextField(
        verbose_name="Catalogue des formations (texte libre)",
        help_text="Décrivez chaque formation, ses durées et son lien. Le bot utilisera ce texte pour répondre aux prospects."
    )
    horaires = models.TextField(
        default="Cours en présentiel du lundi au vendredi. Pas de cours le week-end.",
        verbose_name="Horaires et disponibilités",
        help_text="Informations sur les horaires, jours de cours, modalités (présentiel, en ligne)."
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Base de Connaissances du Bot"
        verbose_name_plural = "Base de Connaissances du Bot"

    def __str__(self):
        return f"Configuration Bot — Mis à jour le {self.updated_at.strftime('%Y-%m-%d %H:%M')}"

    @classmethod
    def get_solo(cls):
        """
        Récupère l'unique enregistrement de configuration.
        S'il n'existe pas encore, le crée avec les valeurs par défaut complètes.
        Pattern Singleton garanti : jamais de doublons.
        """
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                'catalogue_formations': (
                    "=== CATALOGUE DES FORMATIONS BAKELI ===\n\n"
                    "PROGRAMMES DISPONIBLES :\n\n"
                    "1️⃣ Développement Web & Mobile\n"
                    "   Rôle : Développeur web/mobile\n"
                    "   Détail : Sites web, apps mobiles, React, JavaScript, PHP, Flutter\n"
                    "   Durée : 6 mois (certifiant) | 12 mois (certifiant + stage garanti) | 24 mois (diplômant)\n"
                    "   Lien : bakeli.tech/domaine/developpement-web-et-mobile\n\n"
                    "2️⃣ Marketing & Communication Digitale\n"
                    "   Rôle : Digital Marketer / Community Manager\n"
                    "   Détail : SEO, réseaux sociaux, pub digitale, stratégie de marque\n"
                    "   Durée : 6 mois (certifiant) | 24 mois (diplômant)\n"
                    "   Lien : bakeli.tech/domaine/marketing-et-communication-digitale\n\n"
                    "3️⃣ Informatique de Gestion\n"
                    "   Rôle : Gestionnaire de systèmes informatiques\n"
                    "   Détail : Automatisation des processus, structuration des données, ERP\n"
                    "   Durée : 6 mois | 24 mois (diplômant)\n"
                    "   Lien : bakeli.tech/domaine/informatique-de-gestion\n\n"
                    "4️⃣ Infographie\n"
                    "   Rôle : Infographiste / Designer visuel\n"
                    "   Détail : Photoshop, Illustrator, design graphique, identité visuelle\n"
                    "   Durée : 6 mois | 24 mois (diplômant)\n"
                    "   Lien : bakeli.tech/domaine/infographie\n\n"
                    "5️⃣ Webmaster & Réseaux Sociaux\n"
                    "   Rôle : Webmaster / Gestionnaire de présence digitale\n"
                    "   Détail : Gestion de sites, animation de communautés, outils digitaux 360°\n"
                    "   Durée : 6 mois | 24 mois\n"
                    "   Lien : bakeli.tech/domaine/webmaster-reseaux-sociaux\n\n"
                    "6️⃣ Secrétariat Bureautique\n"
                    "   Rôle : Assistant(e) administratif(ve) / Secrétaire de direction\n"
                    "   Détail : Word, Excel, organisation, gestion documentaire, communication\n"
                    "   Durée : 6 mois | 24 mois\n"
                    "   Lien : bakeli.tech/domaine/secretariat-bureautique\n\n"
                    "7️⃣ Assistant de Gestion PME/PMI\n"
                    "   Rôle : Assistant de direction / Gestionnaire d'entreprise\n"
                    "   Détail : Comptabilité, RH, gestion commerciale, suivi opérationnel\n"
                    "   Durée : 6 mois | 24 mois (diplômant)\n"
                    "   Lien : bakeli.tech/domaine/assistant-de-gestion-de-pmepmi\n\n"
                    "8️⃣ Développement Fullstack JS & DevOps (avec bourse Volkeno)\n"
                    "   Rôle : Fullstack Developer / DevOps Engineer\n"
                    "   Détail : React, Node.js, CI/CD, Docker, déploiement cloud\n"
                    "   Lien : bakeli.tech/bourse/developpement-fullstack-js-devops\n\n"
                    "9️⃣ Analyse des Données & IA (avec bourse Volkeno)\n"
                    "   Rôle : Data Analyst / Ingénieur IA\n"
                    "   Détail : Python, Machine Learning, Power BI, traitement de données\n"
                    "   Lien : bakeli.tech/bourse/analyse-des-donnees-ia\n\n"
                    "TYPES DE FORMATION :\n"
                    "- Formations certifiantes (6 mois et 12 mois) : certificat professionnel\n"
                    "- Formations diplômantes (24 mois) : diplôme Technicien Supérieur reconnu par le Ministère\n"
                    "- Bakeli Learning : cours en ligne gratuits — learning.bakeli.tech\n"
                    "- Bourses Volkeno : jusqu'à 70% de réduction (Dév Web, Fullstack JS, Data & IA, etc.)\n"
                )
            }
        )
        return obj

class ConversationState(models.Model):
    """
    Stocke l'historique de la conversation (mémoire du LLM) pour un numéro de téléphone donné.
    Remplace la mémoire RAM volatile qui posait problème lors des redémarrages ou du multi-processing.
    """
    phone_number = models.CharField(max_length=20, unique=True, db_index=True)
    history = models.JSONField(default=list)  # Stocke une liste de dicts [{"role": "user", "content": "..."}, ...]
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "État de la conversation"
        verbose_name_plural = "États des conversations"

    def __str__(self):
        return f"Historique de {self.phone_number} ({len(self.history)} messages)"

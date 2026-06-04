from django.db import models
from django.utils import timezone
import uuid

class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    phone_number = models.CharField(max_length=20, db_index=True)
    message_text = models.TextField()
    
    sentiment_score = models.FloatField(null=True, blank=True)   # ex: 0.85
    sentiment_label = models.CharField(
        max_length=10,
        choices=[
            ('positive', 'Positive'),
            ('negative', 'Negative'),
            ('neutral', 'Neutral'),
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

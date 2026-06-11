import json
import re
from decouple import config
from utils.ai_client import ask

def analyser_sentiment_global(messages_textes):
    """
    Analyse le sentiment GLOBAL et l'INTENTION d'une conversation complète.
    Utilise LLaMA 3.1 via Groq pour une analyse sémantique profonde du contexte métier.
    """
    if not messages_textes:
        return {'label': 'neutral', 'score': 0.5}

    # On prépare la conversation pour l'IA
    conversation = "\n".join([f"- {m}" for m in messages_textes])

    prompt = f"""Tu es un expert en analyse d'intention d'achat pour un centre de formation.
Analyse cette conversation WhatsApp avec un prospect et détermine son niveau d'intérêt.

RÈGLES DE CLASSIFICATION STRICTES:
1. "positive" : Prospect CHAUD. Très intéressé, montre des signes clairs de vouloir s'inscrire rapidement, pose des questions sur les modalités d'inscription, le paiement, ou le début des cours.
2. "neutral" : Prospect FROID ou INCERTAIN. Pose des questions mais ne montre pas de signe d'engagement clair, ou n'a pas montré d'intérêt explicite. Nécessite une relance.
3. "negative" : Prospect TRÈS MÉCONTENT. Il y a une plainte sérieuse, de la frustration extrême, une insulte, ou une exigence forte (remboursement, litige). Ne classe pas en négatif si c'est juste un manque d'intérêt ou un simple "non". Réserve "negative" pour les cas qui nécessitent une intervention humaine URGENTE pour gérer une crise.

CONVERSATION RÉCENTE DU PROSPECT:
{conversation}

Réponds UNIQUEMENT au format JSON avec cette structure exacte (sans aucun autre texte autour, sans markdown) :
{{"label": "positive", "score": 0.95}}

Le champ 'label' doit être EXACTEMENT l'un de ces trois mots : "positive", "neutral", ou "negative".
Le champ 'score' est ta confiance entre 0.0 et 1.0.
"""

    try:
        print("🧠 Appel à Bakeli AI pour analyse d'intention (Sentiment)...")
        reponse_texte = ask(
            messages=[{"role": "user", "content": prompt}], 
            model="openai/gpt-oss-20b"
        )
        
        # Nettoyage d'éventuels blocs markdown retournés par le LLM
        reponse_texte = reponse_texte.strip()
        if reponse_texte.startswith("```json"):
            reponse_texte = reponse_texte[7:]
        if reponse_texte.startswith("```"):
            reponse_texte = reponse_texte[3:]
        if reponse_texte.endswith("```"):
            reponse_texte = reponse_texte[:-3]
            
        data = json.loads(reponse_texte.strip())
        
        label = data.get('label', 'neutral').lower()
        if label not in ['positive', 'neutral', 'negative']:
            label = 'neutral'
            
        score = float(data.get('score', 0.5))
        
        # On filtre les faux positifs : un score trop bas sur un "negative" devient "neutral"
        if label == 'negative' and score < 0.72:
            label = 'neutral'
            
        print(f"📊 Résultat Intention: {label} (confiance: {score})")
        return {'label': label, 'score': score}

    except Exception as e:
        print(f"❌ Erreur Groq IA Sentiment: {e}")
        # Logique de secours basique par mots-clés au cas où l'API Groq est inaccessible
        texte_complet = " ".join(messages_textes).lower()
        
        mots_negatifs_graves = ['escroc', 'arnaque', 'rembourser', 'remboursement', 'plainte', 'incompétent', 'honte']
        mots_positifs = ['oui', 'inscription', 'payer', 'comment', 'intéressé', 'super', 'génial', 'commencer']
        
        if any(mot in texte_complet for mot in mots_negatifs_graves):
            return {'label': 'negative', 'score': 0.8}
        if any(mot in texte_complet for mot in mots_positifs):
            return {'label': 'positive', 'score': 0.8}
            
        return {'label': 'neutral', 'score': 0.5}

def analyser_message_whatsapp(texte):
    """
    Rétrocompatibilité si appelée individuellement.
    """
    return analyser_sentiment_global([texte])
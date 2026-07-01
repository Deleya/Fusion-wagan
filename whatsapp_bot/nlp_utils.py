import json
import re
from decouple import config
from utils.ai_client import ask

# =============================================================================
# FEW-SHOT EXAMPLES — Exemples calibrés sur le contexte sénégalais.
# Inclure des fautes de frappe réelles pour que le LLM tolère le langage informel.
# =============================================================================
FEW_SHOT_EXAMPLES = """
EXEMPLES DE CLASSIFICATION (pour calibrer ton jugement) :

Exemple 1 — POSITIVE :
ASSISTANT: Voulez-vous réserver votre place dans la formation ?
USER: Ok j'aimerais commencer la semaine prochaine et m'inscrire
→ LABEL: positive (intention directe d'inscription, malgré le fait de remettre à plus tard)

Exemple 2 — LOST_LEAD :
ASSISTANT: Avez-vous d'autres questions sur nos formations ?
USER: Finalement je ne suis plis interesser tout compte fais mon emploie du temps me permet pas
→ LABEL: lost_lead (abandon explicite malgré les fautes "plis interesser", "emploie du temps")

Exemple 3 — LOST_LEAD :
ASSISTANT: La prochaine session démarre le 15 août. Des questions ?
USER: Merci quand mm
→ LABEL: lost_lead ("merci quand même" = formule de congé polie = AU REVOIR définitif)

Exemple 4 — POSITIVE :
ASSISTANT: Souhaitez-vous vous inscrire à la formation Développement Web ?
USER: je veux le faire
→ LABEL: positive (confirmation directe, même courte)

Exemple 5 — BOT_STUCK :
ASSISTANT: Je vous propose la formation de 6 mois à 150 000 FCFA.
USER: tu comprends rien a ce que je dis depuis le debut
→ LABEL: bot_stuck (frustration envers le bot, pas envers Bakeli)

Exemple 6 — NEUTRAL :
ASSISTANT: Souhaitez-vous en savoir plus sur nos programmes ?
USER: Daccord merci
→ LABEL: neutral (accusé de réception informatif, pas d'intention de décision)

Exemple 7 — LOST_LEAD :
ASSISTANT: Le prix de la formation est de 200 000 FCFA.
USER: c trop cher pour moi
→ LABEL: lost_lead (contrainte financière explicite = abandon probable)

Exemple 8 — NEUTRAL :
ASSISTANT: Nous proposons plusieurs formations en tech et marketing.
USER: et pour les cours du soir c'est possible ?
→ LABEL: neutral (question d'exploration, pas encore de décision)
"""

def analyser_sentiment_global(messages_textes):
    """
    Analyse le sentiment GLOBAL et l'INTENTION d'une conversation complète.
    Utilise LLaMA 3.1 via Groq pour une analyse sémantique profonde du contexte métier.
    """
    if not messages_textes:
        return {'label': 'neutral', 'score': 0.5}

    # On prépare la conversation pour l'IA
    conversation = "\n".join([f"- {m}" for m in messages_textes])

    prompt_system = f"""Tu es un expert en qualification de leads pour le centre de formation Bakeli (Sénégal).
Ta mission est d'analyser cette conversation WhatsApp et de déterminer l'INTENTION ACTUELLE du prospect.

CONTEXTE CULTUREL IMPORTANT :
- Les prospects écrivent souvent en français avec des fautes de frappe importantes (langage informel sénégalais).
- Expressions courantes d'abandon : "plis intéressé", "plsuinteresser", "emploie du temps", "trop cher", "merci quand mm", "merci quand même".
- Expressions d'intention positive : "m'inscire", "commencer semaine prochaine", "je veux le faire".
- "merci quand même" ou "merci quand mm" en FIN de conversation = AU REVOIR définitif = LOST_LEAD.
- Sers-toi toujours de la question précédente de l'ASSISTANT pour interpréter une réponse courte du USER.
  Ex : ASSISTANT="Voulez-vous vous inscrire ?" + USER="Oui" → POSITIVE.
  Ex : ASSISTANT="Autre chose ?" + USER="Non merci" → peut être LOST_LEAD selon le ton.

RÈGLES DE CLASSIFICATION (5 STATUTS) :
1. "positive"  — Intention claire d'inscription, de paiement, ou de démarrage de formation.
2. "neutral"   — Exploration, questions d'information, découverte. État par défaut.
3. "lost_lead" — Abandon, désintérêt, contrainte (prix, temps, emploi du temps).
4. "bot_stuck" — Frustration envers le bot, demande d'un conseiller humain, bot qui tourne en rond.
5. "angry"     — Mécontentement explicite, insultes, plaintes, arnaque.

RÈGLE D'OR : Le label DOIT refléter l'intention du DERNIER message du USER, interprété dans son contexte.

{FEW_SHOT_EXAMPLES}

Réponds UNIQUEMENT au format JSON avec cette structure exacte :
{{"label": "positive", "score": 0.95, "reason": "..."}}

Le champ 'label' doit être "positive", "neutral", "lost_lead", "bot_stuck", ou "angry".
Le champ 'score' est ta confiance entre 0.0 et 1.0.
Le champ 'reason' est une courte explication de ton choix (utile pour le debug, 1 phrase max).
"""

    prompt_user = f"""CONVERSATION RÉCENTE DU PROSPECT:
{conversation}"""

    try:
        print("🧠 Appel à Bakeli AI pour analyse d'intention (Sentiment)...")
        reponse_texte = ask(
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user}
            ], 
            model="openai/gpt-oss-20b"
        )
        # Extraction robuste du JSON via Regex
        match = re.search(r'\{.*\}', reponse_texte, re.DOTALL)
        if match:
            reponse_texte = match.group(0)
            
        data = json.loads(reponse_texte.strip())
        
        label = data.get('label', 'neutral').lower()
        if label not in ['positive', 'neutral', 'lost_lead', 'bot_stuck', 'angry']:
            label = 'neutral'

        score = float(data.get('score', 0.5))
        reason = data.get('reason', '')
        if reason:
            print(f"🧠 Raison IA: {reason}")

        # On filtre les faux positifs (baisse de confiance)
        if label in ['angry', 'lost_lead'] and score < 0.72:
            label = 'neutral'
            
        # =================================================================
        # FILET DE SÉCURITÉ (Post-traitement)
        # L'IA (20B) fait parfois des erreurs de jugement sur le statut 'neutral'.
        # Si elle classifie comme neutre, on effectue une passe de mots-clés robuste
        # pour corriger les intentions évidentes (et tolérer les fautes de frappe).
        # =================================================================
        texte_dernier_msg = messages_textes[-1].lower() if messages_textes else ""
        
        if label == 'neutral':
            # Mots-clés pour LOST LEAD (Désintérêt / Abandon)
            # Patterns regex tolérant les fautes de frappe et les mots intercalés
            est_lost_lead = (
                re.search(r"(plus|plsu|plus?).{0,10}int[eé]ress[eé]", texte_dernier_msg) or
                re.search(r"plsuinteress", texte_dernier_msg) or
                re.search(r"laisse.{0,5}tomber", texte_dernier_msg) or
                re.search(r"(permet|peux|peux pas|peux pu).{0,25}(inscrire|inscire|s'inscr)", texte_dernier_msg) or
                re.search(r"(temps|emploi|emploie|schedule).{0,20}(permet|peux|empêche).{0,20}(inscr|payer)", texte_dernier_msg) or
                re.search(r"finalement.{0,30}(pas|plus|pu).{0,30}(inscr|intéress|interest)", texte_dernier_msg) or
                re.search(r"plus int[eé]ress[eé]", texte_dernier_msg) or
                # Formules de congé polies sénégalaises — "merci quand mm" = "merci quand même" = AU REVOIR
                re.search(r"merci (quand (mm|meme|même)|mais non)", texte_dernier_msg) or
                re.search(r"\b(bye|ciao)\b", texte_dernier_msg) or
                re.search(r"(au revoir|bonne continuation).{0,10}$", texte_dernier_msg) or
                "trop cher" in texte_dernier_msg or
                "pas intéressé" in texte_dernier_msg or
                "au revoir" in texte_dernier_msg
            )
            if est_lost_lead:
                label = 'lost_lead'
                score = 0.90
                print("[NLP] Filet de securite active : neutral -> lost_lead")
                
            # Mots-clés pour POSITIVE (Conversion / Inscription)
            elif re.search(r"(m.inscrire|m.inscire|commencer|payer|je veux|je souhaite).{0,30}(formation|cours|maintenant|semaine)", texte_dernier_msg) or \
                 re.search(r"je (veux|souhaite) (le faire|m.inscrire|m.inscire)", texte_dernier_msg) or \
                 re.search(r"(ok|oui|d.accord|je).{0,15}(veux|veux bien|souhaite|aimerais).{0,15}(inscr|commenc|payer)", texte_dernier_msg):
                label = 'positive'
                score = 0.90
                print("[NLP] Filet de securite active : neutral -> positive")
                
        print(f"📊 Résultat Intention: {label} (confiance: {score})")
        return {'label': label, 'score': score}

    except Exception as e:
        print(f"❌ Erreur Groq IA Sentiment: {e}")
        # Logique de secours basique (Fallback complet si l'API crash)
        texte_complet = messages_textes[-1].lower() if messages_textes else ""
        
        mots_angry = ['escroc', 'arnaque', 'rembourser', 'remboursement', 'plainte', 'incompétent', 'honte', 'nul', 'nul']
        mots_lost = ['intéresse plus', 'pas satisfait', 'laisse tomber', 'plus intéressé', 'au revoir', 'trop cher', 'laisser tomber', 'plsuinteresser', 'merci quand mm', 'merci quand même', 'ciao', 'bye']
        mots_stuck = ['humain', 'conseiller', 'tourne en rond', 'réponds pas', 'comprends rien']
        mots_positifs = ['oui', 'inscription', 'payer', 'comment', 'intéressé', 'super', 'génial', 'commencer', 'je veux le faire', 'prix', 'm\'inscire', 'm\'inscrire']
        
        if any(mot in texte_complet for mot in mots_angry):
            return {'label': 'angry', 'score': 0.8}
        if any(mot in texte_complet for mot in mots_lost) or re.search(r"(plus|plsu).*int[eé]ress[eé]r?", texte_complet):
            return {'label': 'lost_lead', 'score': 0.8}
        if any(mot in texte_complet for mot in mots_stuck):
            return {'label': 'bot_stuck', 'score': 0.8}
        if any(mot in texte_complet for mot in mots_positifs) or re.search(r"(m'inscrire|m'inscire)", texte_complet):
            return {'label': 'positive', 'score': 0.8}
            
        return {'label': 'neutral', 'score': 0.5}

def analyser_message_whatsapp(texte):
    """
    Rétrocompatibilité si appelée individuellement.
    """
    return analyser_sentiment_global([texte])
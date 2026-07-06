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

Exemple 9 — NEUTRAL :
ASSISTANT: Les cours d'informatique ne sont pas disponibles en ce moment.
USER: Daccord les cours de developpement web m'interesse egalement
→ LABEL: neutral (Le prospect explore une autre option suite à une indisponibilité, c'est une marque d'intérêt, PAS un abandon)

Exemple 10 — POSITIVE (retournement / récupération) :
ASSISTANT: Je comprends tout à fait, n'hésitez pas à revenir vers nous.
USER: Finalement tout compte fais j'ai du temps de libre, je vais m'inscrire dès lundi
→ LABEL: positive (le prospect REVIENT sur son abandon précédent = récupération. Le label reflète son intention ACTUELLE, jamais son passé)
"""

# =============================================================================
# FILET DE SÉCURITÉ (post-traitement déterministe)
# Corrige les erreurs de jugement du LLM sur le label 'neutral' UNIQUEMENT.
# EXIGENCE DE PRÉCISION : chaque pattern force le label avec une confiance de
# 0.90 et déclenche une alerte CRM → un pattern ne doit matcher QUE des
# intentions non ambiguës (négation explicite obligatoire pour lost_lead).
# =============================================================================

# --- Patterns LOST_LEAD (désintérêt / abandon) — testés dans CET ordre ---
_PATTERNS_LOST_LEAD = [
    # Négation d'intérêt, fautes tolérées : "ne suis plus/plis intéressé",
    # "pas intéressé", "plus du tout intéressé", "jamais intéressé"
    r"(ne\s*suis\s*pl[iu]s|pl[iu]s\s*du\s*tout|pas\s*du\s*tout|pas|jamais)\s*int[eé]ress[eé]",
    # Ordre inversé : "ça ne m'intéresse plus/pas" (négation ne/n' obligatoire)
    r"\b(ne|n')\s*(m'\s*)?int[eé]resse\s+(plus|pas)\b",
    # "je suis plus intéressé" SANS "par/que" derrière (sinon c'est un comparatif
    # = intérêt pour une alternative, ex: "je suis plus intéressé par le dev web")
    r"suis\s+pl[iu]s\s+int[eé]ress[eé]e?s?\b(?!\s+(par|que)\b)",
    # Faute de frappe réelle observée en production
    r"plsuinteress",
    # Abandon explicite
    r"laisse[rz]?\s{0,5}tomber",
    r"j'\s*abandonne",
    # Contrainte empêchant l'inscription — NÉGATION OBLIGATOIRE ("peux pas",
    # "permet pas"). "je peux m'inscrire ?" ne doit JAMAIS matcher (lead chaud).
    r"(permet|peux|peut|pourrai\w*)\s*(pas|plus|pu)\b.{0,30}(inscri|payer|suivre|commencer|continuer|venir)",
    # Futur proche négatif : "je (ne) vais pas m'inscrire"
    r"vais\s+pas\s+.{0,15}(inscri|payer|venir|continuer)",
    r"(temps|emploi|emploie|travail|boulot|schedule).{0,25}permet\s*(pas|plus)",
    r"finalement.{0,30}(pas|plus|pu).{0,30}(inscri|int[eé]ress|interest)",
    # Formules de congé polies sénégalaises — "merci quand mm" = AU REVOIR
    r"merci\s+(quand\s+(mm|meme|même)|mais\s+non)",
    r"\b(bye|ciao)\b",
    r"au\s*revoir",
    r"bonne\s+continuation",
    # Contrainte financière explicite (Exemple 7)
    r"trop\s+cher",
]

# --- Patterns POSITIVE (conversion / inscription) ---
_PATTERNS_POSITIVE = [
    r"(m'?\s*inscri|commencer|payer|je\s+veux|je\s+souhaite).{0,30}(formation|cours|maintenant|semaine)",
    r"je\s+(veux|souhaite)\s+(le\s+faire|m'?\s*inscri)",
    r"(ok|oui|d'?\s*accord|je).{0,15}(veux|veux\s+bien|souhaite|aimerais).{0,15}(inscri|commenc|payer)",
    # Question pratique d'inscription = intention d'achat ("comment je peux m'inscrire ?")
    r"(comment|quand|o[uù])\s.{0,25}(inscri|payer|commencer)",
    r"(peux|peut|pourrais?)\s+(m'?\s*)?inscri",
    # Futur proche / engagement daté : "je vais m'inscrire dès lundi prochain"
    r"(je\s+vais|j'irai|je\s+compte)\s+(m'?\s*)?inscri",
    r"inscri\w*\s+d[eè]s\s+(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|demain|la\s+semaine)",
]


# =============================================================================
# DÉTECTION D'ENTAME DE CONVERSATION
# =============================================================================

# Salutations pures reconnues (contexte sénégalais : salam aleykoum, cc, slt...)
_SALUTATION = (
    r"(bonjour|bonsoir|bjr|bsr|salut|slt|coucou|cc|hello|hi|hey|yo"
    r"|salam(\s*aleykoum)?|as?\s*salamou?\s*aleykoum|salamaleykoum)"
)
# Un message d'entame = uniquement des salutations (répétées ou non), avec en
# option une formule de politesse courte ("ça va ?") et ponctuation/emojis.
_RE_SALUTATION_PURE = re.compile(
    rf"^\s*(?:{_SALUTATION})(?:[\s,!.]+{_SALUTATION})*"
    rf"(?:[\s,!.]+(?:ça\s*va|ca\s*va|cv|comment\s+allez\s*-?\s*vous))?"
    rf"[\W_]*$",
    re.IGNORECASE,
)


def est_salutation_pure(texte):
    """
    True si le message n'est QU'UNE salutation ("bonjour", "slt", "salam"...).
    Utilisé pour déclencher SYSTÉMATIQUEMENT le panel d'amorce en début de
    conversation, même si le prospect a déjà échangé dans les 12 dernières heures.
    Un message avec du contenu ("bonjour je veux m'inscrire") n'est PAS une
    salutation pure : il mérite une vraie réponse, pas le menu.
    """
    if not texte or len(texte) > 60:
        return False
    return bool(_RE_SALUTATION_PURE.match(texte.replace("’", "'").strip()))


def _dernier_message_user(messages_textes):
    """
    Retourne le texte du dernier message USER (minuscules, apostrophes normalisées).
    Les entrées sont au format "USER: ..." / "ASSISTANT: ..." (ou du texte brut).
    Le filet de sécurité ne doit JAMAIS s'appliquer à un message de l'ASSISTANT
    (ex: "vous pouvez vous inscrire..." matcherait un pattern positif).
    """
    for entree in reversed(messages_textes or []):
        texte = entree.strip()
        if texte.upper().startswith("ASSISTANT:"):
            continue
        if texte.upper().startswith("USER:"):
            texte = texte[5:]
        return texte.replace("’", "'").lower().strip()
    return ""


def appliquer_filet_securite(label, score, texte_dernier_msg):
    """
    Passe de mots-clés déterministe appliquée UNIQUEMENT quand le LLM répond
    'neutral'. lost_lead est testé AVANT positive (ex: "je peux pas m'inscrire"
    contient "inscrire" mais doit rester lost_lead).
    Retourne (label, score) — inchangés si aucun pattern ne matche.
    """
    if label != 'neutral' or not texte_dernier_msg:
        return label, score

    t = texte_dernier_msg.replace("’", "'").lower()

    for pattern in _PATTERNS_LOST_LEAD:
        if re.search(pattern, t):
            print(f"[NLP] Filet de securite active : neutral -> lost_lead (pattern: {pattern})")
            return 'lost_lead', 0.90

    for pattern in _PATTERNS_POSITIVE:
        if re.search(pattern, t):
            print(f"[NLP] Filet de securite active : neutral -> positive (pattern: {pattern})")
            return 'positive', 0.90

    return label, score


def analyser_sentiment_global(messages_textes, statut_precedent=None):
    """
    Analyse le sentiment GLOBAL et l'INTENTION d'une conversation complète.
    Utilise LLaMA 3.1 via Groq pour une analyse sémantique profonde du contexte métier.

    Args:
        messages_textes: liste de lignes "USER: ..." / "ASSISTANT: ...".
        statut_precedent: statut CRM persistant du prospect (machine à états),
            injecté dans le prompt pour aider le LLM à détecter les retournements.
    """
    if not messages_textes:
        return {'label': 'neutral', 'score': 0.5}

    # On prépare la conversation pour l'IA
    conversation = "\n".join([f"- {m}" for m in messages_textes])

    # Contexte CRM : le statut persistant aide le LLM à repérer un retournement
    # (ex: prospect 'lost_lead' qui revient avec une intention d'inscription).
    contexte_statut = ""
    if statut_precedent and statut_precedent != 'neutral':
        contexte_statut = (
            f"\nSTATUT CRM ACTUEL DU PROSPECT : {statut_precedent}\n"
            "Si son DERNIER message contredit ce statut (ex: un prospect 'lost_lead' "
            "qui revient s'inscrire), c'est un RETOURNEMENT : classe selon le dernier "
            "message, PAS selon le statut passé.\n"
        )

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
- ATTENTION : Si le prospect dit "d'accord" ou accepte de changer de formation suite à une indisponibilité, c'est NEUTRAL ou POSITIVE, ce n'est PAS un abandon (LOST_LEAD).

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

    prompt_user = f"""{contexte_statut}CONVERSATION RÉCENTE DU PROSPECT:
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
            
        # Filet de sécurité déterministe — appliqué au dernier message USER
        # uniquement (jamais à une ligne ASSISTANT de l'historique).
        texte_dernier_msg = _dernier_message_user(messages_textes)
        label, score = appliquer_filet_securite(label, score, texte_dernier_msg)

        print(f"📊 Résultat Intention: {label} (confiance: {score})")
        return {'label': label, 'score': score}

    except Exception as e:
        print(f"❌ Erreur Groq IA Sentiment: {e}")
        # Logique de secours basique (Fallback complet si l'API crash)
        texte_complet = _dernier_message_user(messages_textes)

        mots_angry = ['escroc', 'arnaque', 'rembourser', 'remboursement', 'plainte', 'incompétent', 'honte', 'nul']
        mots_lost = ['intéresse plus', 'pas satisfait', 'laisse tomber', 'plus intéressé', 'au revoir', 'trop cher', 'laisser tomber', 'plsuinteresser', 'merci quand mm', 'merci quand même', 'ciao', 'bye']
        mots_stuck = ['humain', 'conseiller', 'tourne en rond', 'réponds pas', 'comprends rien']
        mots_positifs = ['oui', 'inscription', 'payer', 'comment', 'intéressé', 'super', 'génial', 'commencer', 'je veux le faire', 'prix', 'm\'inscire', 'm\'inscrire']
        
        if any(mot in texte_complet for mot in mots_angry):
            return {'label': 'angry', 'score': 0.8}
        if any(mot in texte_complet for mot in mots_lost) or re.search(r"(ne\s*suis\s*plus|plus\s*du\s*tout|pas\s*du\s*tout)\s*int[eé]ress[eé]r?", texte_complet):
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
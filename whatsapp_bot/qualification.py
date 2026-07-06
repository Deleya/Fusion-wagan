"""
Machine à états de qualification des prospects (CRM).

PRINCIPE FONDAMENTAL :
Le sentiment d'un MESSAGE est un signal instantané ; le statut d'un PROSPECT
est un état persistant. Les deux ne doivent jamais être confondus :
un "ok merci" (neutral) après un "je m'inscris lundi" (positive) est une
politesse de clôture, PAS une dégradation du prospect.

RÈGLES DE TRANSITION :
1. 'neutral' = ABSENCE de signal → ne modifie JAMAIS un statut existant.
2. Un signal sous le seuil de confiance est ignoré (bruit).
3. Tout signal fort (positive/lost_lead/bot_stuck/angry) devient le nouveau statut.
4. La transition {lost_lead, bot_stuck, angry} → positive est une RÉCUPÉRATION :
   le prospect revient après un abandon — signal commercial prioritaire.
"""

from django.utils import timezone

# Labels considérés comme de vrais signaux (par opposition à 'neutral')
SIGNAUX = {'positive', 'lost_lead', 'bot_stuck', 'angry'}

# Statuts négatifs depuis lesquels un retour à 'positive' = récupération
STATUTS_A_RISQUE = {'lost_lead', 'bot_stuck', 'angry'}

# Seuil de confiance minimal pour qu'un signal modifie le statut du prospect.
# En dessous, le signal est considéré comme du bruit (hallucination LLM probable).
SEUIL_CONFIANCE_SIGNAL = 0.60

# Types de transition retournés (consommés par les alertes et les logs)
TRANSITION_INITIALE = 'initiale'          # premier signal du prospect
TRANSITION_RECUPERATION = 'recuperation'  # à risque → positive (alerte prioritaire !)
TRANSITION_DEGRADATION = 'degradation'    # positive/neutral → à risque
TRANSITION_ESCALADE = 'escalade'          # montée en gravité entre statuts à risque
TRANSITION_PROGRESSION = 'progression'    # neutral → positive
TRANSITION_CONFIRMATION = 'confirmation'  # même statut confirmé
TRANSITION_AUCUNE = None                  # pas de signal ou signal ignoré

# Gravité des statuts à risque (alignée sur _LABEL_GRAVITE de celery_tasks)
_GRAVITE = {'lost_lead': 1, 'bot_stuck': 2, 'angry': 3}


def calculer_transition(statut_actuel, nouveau_label, nouveau_score):
    """
    Fonction PURE (sans accès DB) : calcule le nouveau statut d'un prospect.

    Args:
        statut_actuel (str|None): statut persistant actuel ('neutral' si inconnu).
        nouveau_label (str): label du dernier message analysé.
        nouveau_score (float): confiance du label.

    Returns:
        tuple (nouveau_statut, type_transition)
    """
    statut_actuel = statut_actuel or 'neutral'

    # Règle 1 : 'neutral' = absence de signal → le statut ne bouge pas.
    if nouveau_label not in SIGNAUX:
        return statut_actuel, TRANSITION_AUCUNE

    # Règle 2 : signal trop faible → ignoré.
    if (nouveau_score or 0) < SEUIL_CONFIANCE_SIGNAL:
        return statut_actuel, TRANSITION_AUCUNE

    # Règle 3 : le signal fort devient le nouveau statut.
    if nouveau_label == statut_actuel:
        return statut_actuel, TRANSITION_CONFIRMATION

    if statut_actuel == 'neutral':
        if nouveau_label == 'positive':
            return nouveau_label, TRANSITION_PROGRESSION
        return nouveau_label, TRANSITION_DEGRADATION

    # Règle 4 : récupération d'un prospect à risque.
    if statut_actuel in STATUTS_A_RISQUE and nouveau_label == 'positive':
        return nouveau_label, TRANSITION_RECUPERATION

    if statut_actuel == 'positive' and nouveau_label in STATUTS_A_RISQUE:
        return nouveau_label, TRANSITION_DEGRADATION

    # Entre deux statuts à risque différents : escalade ou simple bascule.
    if statut_actuel in STATUTS_A_RISQUE and nouveau_label in STATUTS_A_RISQUE:
        if _GRAVITE.get(nouveau_label, 0) > _GRAVITE.get(statut_actuel, 0):
            return nouveau_label, TRANSITION_ESCALADE
        return nouveau_label, TRANSITION_DEGRADATION

    return nouveau_label, TRANSITION_CONFIRMATION


def mettre_a_jour_statut_prospect(phone_number, label, score):
    """
    Applique la machine à états sur le statut persistant du prospect
    (ConversationState) et retourne (statut, type_transition).
    """
    from .models import ConversationState

    state, _ = ConversationState.objects.get_or_create(phone_number=phone_number)
    statut_precedent = state.statut_prospect

    # Premier signal d'un prospect encore vierge → transition initiale
    premier_signal = state.statut_updated_at is None

    nouveau_statut, transition = calculer_transition(statut_precedent, label, score)

    if transition is not TRANSITION_AUCUNE:
        state.statut_prospect = nouveau_statut
        state.statut_score = float(score or 0.5)
        state.statut_updated_at = timezone.now()
        state.save(update_fields=['statut_prospect', 'statut_score', 'statut_updated_at', 'updated_at'])
        if premier_signal:
            transition = TRANSITION_INITIALE
        print(f"[QUALIF] {phone_number}: {statut_precedent} -> {nouveau_statut} ({transition})")
    else:
        print(f"[QUALIF] {phone_number}: statut inchangé ({statut_precedent}) — signal '{label}' ({score}) sans effet")

    return nouveau_statut, transition

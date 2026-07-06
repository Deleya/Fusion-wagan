
from django.core.files.storage import default_storage
from rest_framework.response import Response

from rest_framework import views, serializers, status
from rest_framework.permissions import IsAuthenticated

from chatbot.constantes.functions import extract_text_from_file
from chatbot.serializers import DocumentUploadSerializer
from ..constantes.constante import WAGAN_PERSONA,client


# Classe de vue pour gérer le téléchargement de documents
class DocumentUploadView(views.APIView):
    """
    Vue pour gérer le téléchargement de documents (PDF, Word, TXT) pour enrichir la base de connaissances du chatbot.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Gère les requêtes POST pour télécharger des documents.  Le texte des documents est extrait
        et ajouté à la base de connaissances du chatbot.

        Args:
            request (Request): L'objet Request contenant le fichier téléchargé.

        Returns:
            Response: L'objet Response indiquant le succès ou l'échec du téléchargement.
        """
        # L'ancienne implémentation faisait `global WAGAN_PERSONA += ...` :
        # 1) elle ne modifiait que la copie importée dans CE module (aucun effet
        #    réel sur le prompt du chat), et 2) si elle avait fonctionné, le
        #    document d'UN utilisateur aurait été injecté dans le prompt de TOUS
        #    (fuite de données + croissance mémoire illimitée).
        # En attendant une vraie base de connaissances persistante par
        # utilisateur, on répond honnêtement que la fonctionnalité arrive.
        return Response(
            {"error": "L'enrichissement de la base de connaissances par document "
                      "n'est pas encore disponible. Fonctionnalité en cours de développement."},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )


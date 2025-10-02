# coding: utf-8
import os
from django.conf import settings
from rest_framework.response import Response
from django.shortcuts import render
from rest_framework import views, serializers, status

from chatbot.serializers import ChatInputSerializer, ChatResponseSerializer, DocumentUploadSerializer

from ..constantes.constante import WAGAN_PERSONA,client

# Classe de vue pour gérer le chat
class ChatView(views.APIView):
    """
    Vue pour gérer les interactions de chat avec le chatbot Wagan.
    """
    def post(self, request):
        """
        Gère les requêtes POST pour envoyer des messages au chatbot et obtenir des réponses.

        Args:
            request (Request): L'objet Request contenant le message de l'utilisateur.

        Returns:
            Response: L'objet Response contenant la réponse du chatbot.
        """
        serializer = ChatInputSerializer(data=request.data)
        if serializer.is_valid():
            message = serializer.validated_data["message"]

            # Construire le prompt pour le modèle Gemini
            prompt = f"""{WAGAN_PERSONA}
            L'utilisateur a posé la question suivante : {message}
            """

            try:
                response = client.models.generate_content(
                        model="gemini-2.0-flash", contents=[prompt]
                    )
                response_text = response.text
                response_serializer = ChatResponseSerializer({"response": response_text})
                return Response(response_serializer.data, status=status.HTTP_200_OK)
            except Exception as e:
                return Response(
                    {"error": f"Erreur lors de la communication avec le modèle de langage : {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


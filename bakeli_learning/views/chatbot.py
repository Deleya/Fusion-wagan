from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from chatbot.serializers import ChatResponseSerializer
from ..models import ChatSession, Message
from ..serializers import ChatSessionSerializer, MessageSerializer
import requests
from chatbot.constantes.constante import WAGAN_PERSONA,client

class StartChatSession(APIView):
    def post(self, request):
        session = ChatSession.objects.create()
        return Response({"session_id": str(session.session_id)})

class ChatMessage(APIView):
    def post(self, request, session_id):
        try:
            session = ChatSession.objects.get(session_id=session_id)
        except ChatSession.DoesNotExist:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        user_input = request.data.get("message")
        if not user_input:
            return Response({"error": "Message is required."}, status=400)
        
        #Commande spéciale pour réinitialiser une session
        if user_input.strip().lower() == "/reset":
            session.messages.all().delete()
            return Response({"message": "La session a été réinitialisée."}, status=status.HTTP_200_OK)

        # Enregistrer le message utilisateur
        msg_user = Message.objects.create(session=session, sender="user", content=user_input)

        # Appel à l'API Gemini (ou autre LLM)
        response_text = self.get_bot_response(user_input, session)

        # Enregistrer réponse bot
        msg_bot = Message.objects.create(session=session, sender="bot", content=response_text)

        return Response({
            "user_message": MessageSerializer(msg_user).data,
            "bot_message": MessageSerializer(msg_bot).data
        })

    def get_bot_response(self, prompt, session):
        API_KEY = "VOTRE_CLE_GEMINI"

        # 1. Connaissances statiques
        static_knowledge = """
        Bienvenue sur notre site !
        Nous proposons :
        - Développement d'applications web
        - Formations en intelligence artificielle
        - Formations Analyse de Données
        - Service client 24h/24 
        """

        # 2. Récupérer des données d’une API externe (exemple : météo ou produits)
        api_context = ""
        try:
            api_response = requests.get("https://api.exemple.com/infos-actuelles")
            if api_response.status_code == 200:
                data = api_response.json()
                api_context = f"\nInformations du jour : {data.get('infos', 'non disponible')}"
        except:
            api_context = "\nAucune information dynamique disponible pour le moment."

        # 3. Construire un prompt enrichi
        full_prompt = f"""
        CONTEXTE :
        {static_knowledge}
        {WAGAN_PERSONA}
        {api_context}

        QUESTION DE L'UTILISATEUR :
        {prompt}

        RÉPONDS de manière claire et concise.
        """

        # 4. Appel Gemini
        #response = requests.post(
        #    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={API_KEY}",
        #    json={"contents": [{"parts": [{"text": full_prompt}]}]}
        #)

        # 3. Construire l’historique de conversation
        messages = session.messages.order_by("timestamp")
        conversation = []

        
        # Ajouter le contexte initial
        conversation.append({
            "role": "user",
            "text": f"{full_prompt}\n{api_context}"
        })

        for msg in messages:
            if msg.sender == "user":
                conversation.append({"role": "user", "text": msg.content})
            else:
                conversation.append({"role": "model", "text": msg.content})

        # Ajouter le dernier message utilisateur (utile si pas encore enregistré)
        conversation.append({"role": "user", "text": prompt})

        try:
            response = client.models.generate_content(
                    model="gemini-2.0-flash", contents=[full_prompt]
                )
            response_text = response.text
            response_serializer = ChatResponseSerializer({"response": response_text})
            return response_serializer.data['response']
        except Exception as e:
            return Response(
                {"error": f"Erreur lors de la communication avec le modèle de langage : {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

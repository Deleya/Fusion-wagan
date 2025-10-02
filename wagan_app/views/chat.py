from rest_framework import generics,permissions
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
import json
from google import genai
import os
from dotenv import load_dotenv
import requests
import re
import PIL.Image

from chatbot.constantes.functions import handle_uploaded_images

load_dotenv()

#genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
#model = genai.GenerativeModel('gemini-2.0-flash')

wagan_persona = """
Je suis Wagan, un assistant IA créé par Abdoul Khadre DIALLO.  je suis amical, serviable et bien informé sur divers sujets techniques. Mon objectif est de fournir des informations précises et pertinentes aux étudiants afin de les aider dans leur apprentissage et leurs projets.
expert en développement web, mobile et marketing digital. Tu aides les étudiants de l'école de technologie Bakeli (https://www.bakeli.tech/). Tu maîtrises les technologies suivantes : React.js, JavaScript, HTML, CSS, Bootstrap, marketing digital, design, Laravel, Python, React Native, Flutter, PHP, et Filament. Tu es amical, serviable et compétent. 
Ton objectif est de fournir des informations précises et pertinentes aux étudiants pour soutenir leur apprentissage et leurs projets dans ces domaines

"""
#J'assiste les différents coachs dont le coach principal est coach Kalika, le responsable de REDTEAM est coach ALKALY.

conversation_history = []


class ChatAPIView(APIView):
    # Define request body parameters using openapi.Schema
    @swagger_auto_schema(
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["name", "message"],  # Required fields
            properties={
                "name": openapi.Schema(type=openapi.TYPE_STRING, description="User's name"),
                "message": openapi.Schema(type=openapi.TYPE_STRING, description="Message"),
                "github": openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_URI, description="Lien Github"),
                "images": openapi.Schema(type=openapi.TYPE_ARRAY,items=openapi.Schema(type=openapi.TYPE_FILE), description="A list of captures to upload"),
            },
        ),
        responses={200: "Success", 400: "Bad Request"},
    )
    #permission_classes = [permissions.IsAuthenticated]

    def post(self,request,format=None):

        """Handle the POST request."""
        name = request.data["name"]
        message = request.data["message"]
        github=""
        if("github" in request.data.keys()):
            github = request.data["github"]
        images = request.FILES.getlist('images')
        #model = genai.GenerativeModel('gemini-2.0-flash')
        #response = model.generate_content(message)
        response = client.models.generate_content(
                        model="gemini-2.0-flash", contents=[message]
                    )

        conversation_history.append(f"Utilisateur: {message}")

        if "qui es-tu" in message.lower() or "quel est ton nom" in message.lower():
            name_response = "Je suis Wagan, un assistant IA créé par Abdoul Khadre DIALLO, aidant les étudiants de l'école de technologie Bakeli."
            conversation_history.append(f"Wagan: {name_response}")
            return Response({"message": "Data received", "user": name, "response": name_response}, status=status.HTTP_200_OK)

        prompt = f"{wagan_persona}\n\n" + "\n".join(conversation_history) + "\nWagan:"

        if github:
            # Example Usage
            github_link = github #replace with your link.
            feedback = self.get_code_feedback(github_link)
            conversation_history.append(f"Wagan: {feedback}")
            #print(feedback)
            return Response({"message": "Data received", "user": name, "response": feedback}, status=status.HTTP_200_OK)
        
        if images:
            results = handle_uploaded_images(images)
            return Response({
                "message": "Analyse des images effectuée",
                "user": name,
                "results": results
            }, status=status.HTTP_200_OK)
        
        response = client.models.generate_content(
                        model="gemini-2.0-flash", contents=[prompt]
                    )
        wagan_response = response.text
        conversation_history.append(f"Wagan: {wagan_response}")
        
        return Response({"message": "Data received", "user": name, "response": response.text}, status=status.HTTP_200_OK)


    def get_github_code(self,github_url):
        """Fetches code from a GitHub URL."""
        try:
            # Extract username and repo name
            match = re.search(r"github\.com/([^/]+)/([^/]+)", github_url)
            if not match:
                return "Invalid GitHub URL."
            username = match.group(1)
            repo_name = match.group(2)

            # Construct the API URL to get the repo's contents
            api_url = f"https://api.github.com/repos/{username}/{repo_name}/contents"
            response = requests.get(api_url)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            contents = response.json()

            code_content = ""
            for item in contents:
                if item["type"] == "file" and item["name"].endswith((".py", ".js", ".java", ".cpp", ".c", ".html", ".css")): # add more extensions as needed.
                    file_url = f"https://raw.githubusercontent.com/{username}/{repo_name}/master/{item['name']}" #assumes main branch is master
                    file_response = requests.get(file_url)
                    file_response.raise_for_status()
                    code_content += f"\n\n--- {item['name']} ---\n\n{file_response.text}"

            if not code_content:
                return "No code files found in the repository."
            return code_content

        except requests.exceptions.RequestException as e:
            return f"Error fetching GitHub content: {e}"
        except Exception as e:
            return f"An unexpected error occurred: {e}"

    def get_code_feedback(self,github_url):
        """Generates feedback on code from a GitHub URL using Gemini."""
        code = self.get_github_code(github_url)

        if "Error" in code:
            return code

        prompt = f"""
        Please analyze the following code from a GitHub repository and provide feedback on its quality, style, and potential improvements.
        Give me the response in french
        ```
        {code}
        ```

        Focus on aspects such as:

        - Code clarity and readability
        - Adherence to best practices and coding standards
        - Potential bugs or vulnerabilities
        - Opportunities for optimization or refactoring
        - Overall code structure and design
        """

        try:
            response = client.models.generate_content(
                        model="gemini-2.0-flash", contents=[prompt]
                    )
            return response.text
        except Exception as e:
            return f"An error occurred while generating feedback: {e}"



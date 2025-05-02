from django import views
from django.urls import include, path

from wagan_app.views.chat import ChatAPIView

urlpatterns = [
    path('wagan/chat/', ChatAPIView.as_view()),
]

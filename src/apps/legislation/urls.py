"""
URL configuration for legislation app.
"""

from django.urls import path
from . import views

app_name = 'legislation'

urlpatterns = [
    # List view
    path('', views.NormaListView.as_view(), name='norma_list'),
    
    # Chatbot interface (MUST come before <int:pk>/ to avoid conflicts)
    path('chatbot/', views.chatbot_view, name='chatbot'),
    # Chatbot with session slug (like Gemini: /chatbot/abc123def456)
    path('chatbot/<str:session_slug>/', views.chatbot_view, name='chatbot_session'),
    
    # Detail views (generic patterns at the end)
    path('<int:pk>/', views.NormaDetailView.as_view(), name='norma_detail'),
    path('<int:pk>/compare/', views.norma_compare_view, name='norma_compare'),
    path('<int:pk>/tree/', views.norma_dispositivos_tree_view, name='norma_tree'),
]


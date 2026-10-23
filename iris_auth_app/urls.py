from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('staff/login/', views.staff_login_view, name='staff_login'),
    path('staff/register/', views.staff_register_view, name='staff_register'),
    path('staff/dashboard/', views.staff_dashboard, name='staff_dashboard'),
    path('staff/re-enroll/', views.staff_reenroll_view, name='staff_reenroll'),
    path('verify-iris/', views.verify_iris, name='verify_iris'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('logout/', views.logout_view, name='logout'),
]

"""Internationalization (i18n) engine for Input Locker following Google engineering standards.

Features:
- Zero external dependencies (pure Python standard library).
- Fallback chaining: specific locale -> language family -> English (en) default.
- Safe key lookups with parameter interpolation: never crashes on missing keys or args.
- Supports English, Spanish, French, German, Japanese, Simplified Chinese, and Hindi.
- Automatic OS locale detection with manual override support.
"""

from __future__ import annotations

import locale
import logging
import os
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "es": "Español (Spanish)",
    "fr": "Français (French)",
    "de": "Deutsch (German)",
    "ja": "日本語 (Japanese)",
    "zh": "简体中文 (Chinese Simplified)",
    "hi": "हिन्दी (Hindi)",
}

# Translation catalogs
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # App identity
        "app_name": "Input Locker",
        "app_tagline": "AV Staging Lock & Input Interception",
        "app_desc": "A high-performance Windows staging & live AV lock screen utility engineered to intercept keyboard and mouse input while keeping background rendering engines running safely.",
        "version_tag": "v{version} Production",
        "open_source": "Open Source",
        "mit_license": "MIT License",
        "windows_tag": "Windows 10/11",

        # Header buttons & quick actions
        "btn_lock_now": "🔒 Lock Screen Now",
        "btn_lock_now_header": "🔒 Lock Screen",
        "btn_check_updates": "🔄 Check for Updates",
        "btn_checking": "Checking...",
        "btn_about": "👤 About",
        "btn_guide": "📖 Guide",
        "btn_cancel": "Cancel",
        "btn_run_background": "Run in Background ({hotkey} to Lock)",
        "btn_save_apply": "Save & Apply",
        "btn_browse": "📁 Browse...",
        "btn_remove": "✕ Remove",
        "btn_close": "Close",

        # Shortcut banner
        "guide_how_to_unlock": "🔑  HOW TO UNLOCK:",
        "guide_how_to_lock": "🔒  HOW TO LOCK:",
        "guide_unlock_instruction": "Press {hotkey} together at any time while locked to reveal password entry and unlock.",

        # Section 1: Wallpaper
        "card_wallpaper_title": "LOCK SCREEN WALLPAPER",
        "card_wallpaper_subtitle": "Main display background image",
        "wp_badge_active": "🔒 Lock Screen Active",
        "wp_badge_glass": "Dark Blur Glass Mode (Default Display Pass-through)",

        # Section 2: Security
        "card_security_title": "SECURITY & CREDENTIALS",
        "badge_password_protected": "🔒 Password Protected",
        "badge_no_password": "🔓 No Password Required (Shortcut Only)",
        "badge_password_removed": "🔓 Password Removed (Apply to save)",
        "label_unlock_password": "Unlock Password (leave blank for immediate shortcut unlock)",
        "label_confirm_password": "Confirm Password",
        "btn_remove_password": "✕ Remove Password",
        "err_password_mismatch": "⚠ Passwords do not match.",
        "err_invalid_wallpaper": "File not found:\n{path}",
        "hint_unlock_flow": "💡 Unlock instruction: Press unlock combo when locked → Enter Password → Press Enter.",

        # Section 3: Shortcuts & Audio
        "card_shortcuts_title": "SHORTCUTS & AUDIO FEEDBACK",
        "card_shortcuts_subtitle": "Custom triggers & acoustic cues (FOH / Staging)",
        "label_lock_trigger": "Lock Trigger:",
        "label_unlock_combo": "Unlock Combo:",
        "chk_audio_feedback": "🔊 Play acoustic feedback chime on state transitions (lock / unlock)",
        "hint_audio_feedback": "Provides audible confirmation in dark front-of-house (FOH) booths and remote staging racks.",
        "err_invalid_lock_hotkey": "Invalid lock hotkey '{hotkey}':\n{error}",
        "err_invalid_unlock_hotkey": "Invalid unlock hotkey '{hotkey}':\n{error}",

        # Section 4: Preferences & Language
        "card_preferences_title": "PREFERENCES & LOCALIZATION",
        "label_language": "Language / Idioma / 言語:",
        "chk_auto_updates": "Automatically check for updates on launch (offline-safe, zero telemetry)",

        # System Tray Menu
        "tray_menu_lock": "Lock Screen",
        "tray_menu_unlock": "Unlock Screen",
        "tray_menu_settings": "Settings...",
        "tray_menu_about": "About...",
        "tray_menu_check_updates": "Check for Updates...",
        "tray_menu_exit": "Exit",

        # About Dialog
        "about_title": "About Input Locker",
        "about_project_repo": "PROJECT REPOSITORY",
        "about_created_by": "CREATED & MAINTAINED BY",
        "about_updates_title": "🔄  Software Version & Updates",
        "about_current_build": "Current build: v{version} (Production)",
        "about_whats_new": "WHAT'S NEW IN THIS RELEASE",
        "about_system_info": "SYSTEM INFORMATION",
        "about_open_source_msg": "💡 Built to be open-sourced for the AV & live production community.\nFeedback, feature requests, and contributions are warmly welcomed!",
        "about_up_to_date": "Input Locker v{version} is the latest version.",
        "about_update_avail": "Newer build: {version} available!",

        # Quick Start Guide / Tutorial
        "tut_title": "Welcome to Input Locker — Quick Start Guide",
        "tut_welcome": "Welcome to Input Locker",
        "tut_subtitle": "Quick start guide: how to lock, protect, and safely unlock your workstation.",
        "tut_step1_title": "Step 1: How to Lock the Screen",
        "tut_step1_badge": "{hotkey} or Click Lock",
        "tut_step1_desc": "Press {hotkey} at any time or click 'Lock Screen Now'. The screen locks with a secure visual overlay. Video playout engines (Resolume, Watchout, PowerPoint, DAWs) continue rendering visibly and uninterrupted.",
        "tut_step2_title": "Step 2: How to Unlock the Screen",
        "tut_step2_badge": "{hotkey}",
        "tut_step2_desc": "Press {hotkey} to unlock. If a password is configured, the password entry tab appears. If no password is set, the screen unlocks immediately and restores mouse/keyboard input.",
        "tut_step3_title": "Step 3: Staging Hardware Protection",
        "tut_step3_badge": "Win Key Blocked",
        "tut_step3_desc": "Accidental Windows Key taps and Win+L workstation switches are actively neutralized during locked mode to prevent disruptive desktop lockouts during live presentations.",
        "tut_step4_title": "Step 4: Tray Icon & Background Operation",
        "tut_step4_badge": "System Tray",
        "tut_step4_desc": "Right-click the Input Locker system tray icon anytime to toggle lock/unlock, open settings, or check for updates. Running in background keeps the utility ready for hotkey activation.",
        "tut_btn_got_it": "  ✓ Got It — Start Using Input Locker  ",
    },

    "es": {
        "app_name": "Input Locker",
        "app_tagline": "Bloqueo de Escenario AV e Intercepción de Entrada",
        "app_desc": "Utilidad de pantalla de bloqueo de alto rendimiento para escenarios AV en Windows, diseñada para interceptar teclado y ratón mientras los motores de renderizado siguen ejecutándose.",
        "version_tag": "v{version} Producción",
        "open_source": "Código Abierto",
        "mit_license": "Licencia MIT",
        "windows_tag": "Windows 10/11",

        "btn_lock_now": "🔒 Bloquear Pantalla Ahora",
        "btn_lock_now_header": "🔒 Bloquear Pantalla",
        "btn_check_updates": "🔄 Buscar Actualizaciones",
        "btn_checking": "Buscando...",
        "btn_about": "👤 Acerca de",
        "btn_guide": "📖 Guía",
        "btn_cancel": "Cancelar",
        "btn_run_background": "Ejecutar en Segundo Plano ({hotkey} para Bloquear)",
        "btn_save_apply": "Guardar y Aplicar",
        "btn_browse": "📁 Examinar...",
        "btn_remove": "✕ Quitar",
        "btn_close": "Cerrar",

        "guide_how_to_unlock": "🔑  CÓMO DESBLOQUEAR:",
        "guide_how_to_lock": "🔒  CÓMO BLOQUEAR:",
        "guide_unlock_instruction": "Presione {hotkey} a la vez en cualquier momento para ingresar la contraseña y desbloquear.",

        "card_wallpaper_title": "FONDO DE PANTALLA DE BLOQUEO",
        "card_wallpaper_subtitle": "Imagen de fondo para la pantalla principal",
        "wp_badge_active": "🔒 Pantalla de Bloqueo Activa",
        "wp_badge_glass": "Modo Cristal Oscuro (Visualización en directo por defecto)",

        "card_security_title": "SEGURIDAD Y CREDENCIALES",
        "badge_password_protected": "🔒 Protegido con Contraseña",
        "badge_no_password": "🔓 Sin Contraseña (Solo Atajo)",
        "badge_password_removed": "🔓 Contraseña Eliminada (Aplicar para guardar)",
        "label_unlock_password": "Contraseña de Desbloqueo (dejar vacío para desbloqueo directo)",
        "label_confirm_password": "Confirmar Contraseña",
        "btn_remove_password": "✕ Quitar Contraseña",
        "err_password_mismatch": "⚠ Las contraseñas no coinciden.",
        "err_invalid_wallpaper": "Archivo no encontrado:\n{path}",
        "hint_unlock_flow": "💡 Instrucción: Presione atajo cuando esté bloqueado → Ingrese contraseña → Enter.",

        "card_shortcuts_title": "ATAJOS Y RESPUESTA DE AUDIO",
        "card_shortcuts_subtitle": "Disparadores personalizados y señales acústicas (FOH / Escenario)",
        "label_lock_trigger": "Atajo de Bloqueo:",
        "label_unlock_combo": "Atajo de Desbloqueo:",
        "chk_audio_feedback": "🔊 Reproducir señal de audio en transiciones de estado (bloquear / desbloquear)",
        "hint_audio_feedback": "Proporciona confirmación auditiva en cabinas oscuras de FOH y racks de producción.",
        "err_invalid_lock_hotkey": "Atajo de bloqueo no válido '{hotkey}':\n{error}",
        "err_invalid_unlock_hotkey": "Atajo de desbloqueo no válido '{hotkey}':\n{error}",

        "card_preferences_title": "PREFERENCIAS Y LOCALIZACIÓN",
        "label_language": "Idioma / Language / 言語:",
        "chk_auto_updates": "Buscar actualizaciones automáticamente al iniciar (seguro sin conexión)",

        "tray_menu_lock": "Bloquear Pantalla",
        "tray_menu_unlock": "Desbloquear Pantalla",
        "tray_menu_settings": "Configuración...",
        "tray_menu_about": "Acerca de...",
        "tray_menu_check_updates": "Buscar Actualizaciones...",
        "tray_menu_exit": "Salir",

        "about_title": "Acerca de Input Locker",
        "about_project_repo": "REPOSITORIO DEL PROYECTO",
        "about_created_by": "CREADO Y MANTENIDO POR",
        "about_updates_title": "🔄  Versión de Software y Actualizaciones",
        "about_current_build": "Compilación actual: v{version} (Producción)",
        "about_whats_new": "NOVEDADES DE ESTA VERSIÓN",
        "about_system_info": "INFORMACIÓN DEL SISTEMA",
        "about_open_source_msg": "💡 Desarrollado como código abierto para la comunidad de producción AV.\n¡Comentarios, sugerencias y contribuciones son bienvenidos!",
        "about_up_to_date": "Input Locker v{version} es la versión más reciente.",
        "about_update_avail": "¡Nueva compilación {version} disponible!",

        "tut_title": "Bienvenido a Input Locker — Guía de Inicio Rápido",
        "tut_welcome": "Bienvenido a Input Locker",
        "tut_subtitle": "Guía rápida: cómo bloquear, proteger y desbloquear de forma segura su estación.",
        "tut_step1_title": "Paso 1: Cómo Bloquear la Pantalla",
        "tut_step1_badge": "{hotkey} o Clic en Bloquear",
        "tut_step1_desc": "Presione {hotkey} o haga clic en 'Bloquear Pantalla Ahora'. Los motores de vídeo (Resolume, Watchout, DAWs) continúan renderizando sin interrupciones.",
        "tut_step2_title": "Paso 2: Cómo Desbloquear la Pantalla",
        "tut_step2_badge": "{hotkey}",
        "tut_step2_desc": "Presione {hotkey} para desbloquear. Si configuró una contraseña, aparecerá el diálogo de entrada.",
        "tut_step3_title": "Paso 3: Protección de Hardware de Escenario",
        "tut_step3_badge": "Tecla Windows Bloqueada",
        "tut_step3_desc": "Las pulsaciones accidentales de la tecla Windows se neutralizan activamente para evitar bloqueos del sistema.",
        "tut_step4_title": "Paso 4: Icono en Bandeja y Segundo Plano",
        "tut_step4_badge": "Bandeja del Sistema",
        "tut_step4_desc": "Haga clic derecho en el icono de la bandeja del sistema en cualquier momento para bloquear/desbloquear o abrir ajustes.",
        "tut_btn_got_it": "  ✓ Entendido — Empezar a Usar Input Locker  ",
    },

    "fr": {
        "app_name": "Input Locker",
        "app_tagline": "Verrouillage Scène AV & Interception d'Entrées",
        "app_desc": "Utilitaire d'écran de verrouillage haute performance pour régie AV sous Windows, conçu pour intercepter le clavier et la souris tout en maintenant le rendu vidéo actif.",
        "version_tag": "v{version} Production",
        "open_source": "Open Source",
        "mit_license": "Licence MIT",
        "windows_tag": "Windows 10/11",

        "btn_lock_now": "🔒 Verrouiller l'Écran Maintenant",
        "btn_lock_now_header": "🔒 Verrouiller",
        "btn_check_updates": "🔄 Vérifier les Mises à Jour",
        "btn_checking": "Vérification...",
        "btn_about": "👤 À propos",
        "btn_guide": "📖 Guide",
        "btn_cancel": "Annuler",
        "btn_run_background": "Exécuter en Arrière-plan ({hotkey} pour Verrouiller)",
        "btn_save_apply": "Enregistrer et Appliquer",
        "btn_browse": "📁 Parcourir...",
        "btn_remove": "✕ Supprimer",
        "btn_close": "Fermer",

        "guide_how_to_unlock": "🔑  COMMENT DÉVERROUILLER :",
        "guide_how_to_lock": "🔒  COMMENT VERROUILLER :",
        "guide_unlock_instruction": "Appuyez sur {hotkey} simultanément à tout moment pour entrer le mot de passe et déverrouiller.",

        "card_wallpaper_title": "FOND D'ÉCRAN DE VERROUILLAGE",
        "card_wallpaper_subtitle": "Image d'arrière-plan pour l'affichage principal",
        "wp_badge_active": "🔒 Écran de Verrouillage Actif",
        "wp_badge_glass": "Mode Verre Sombre Dépoli (Pass-through d'Affichage par Défaut)",

        "card_security_title": "SÉCURITÉ & IDENTIFIANTS",
        "badge_password_protected": "🔒 Protégé par Mot de Passe",
        "badge_no_password": "🔓 Aucun Mot de Passe Requis (Raccourci Seul)",
        "badge_password_removed": "🔓 Mot de Passe Supprimé (Appliquer pour enregistrer)",
        "label_unlock_password": "Mot de passe de déverrouillage (laisser vide pour déverrouillage immédiat)",
        "label_confirm_password": "Confirmer le Mot de Passe",
        "btn_remove_password": "✕ Supprimer le Mot de Passe",
        "err_password_mismatch": "⚠ Les mots de passe ne correspondent pas.",
        "err_invalid_wallpaper": "Fichier introuvable :\n{path}",
        "hint_unlock_flow": "💡 Déverrouillage : Raccourci pendant le verrouillage → Entrer mot de passe → Entrée.",

        "card_shortcuts_title": "RACCOURCIS & RETOUR AUDIO",
        "card_shortcuts_subtitle": "Déclencheurs personnalisés et signaux acoustiques (Régie / Scène)",
        "label_lock_trigger": "Raccourci de Verrouillage :",
        "label_unlock_combo": "Raccourci de Déverrouillage :",
        "chk_audio_feedback": "🔊 Jouer un carillon audio lors des transitions d'état (verrouiller / déverrouiller)",
        "hint_audio_feedback": "Fournit une confirmation audible dans les cabines régie sombres et baies serveurs.",
        "err_invalid_lock_hotkey": "Raccourci de verrouillage non valide '{hotkey}' :\n{error}",
        "err_invalid_unlock_hotkey": "Raccourci de déverrouillage non valide '{hotkey}' :\n{error}",

        "card_preferences_title": "PRÉFÉRENCES & LOCALISATION",
        "label_language": "Langue / Language / Idioma :",
        "chk_auto_updates": "Vérifier automatiquement les mises à jour au démarrage (sécurisé hors-ligne)",

        "tray_menu_lock": "Verrouiller l'Écran",
        "tray_menu_unlock": "Déverrouiller l'Écran",
        "tray_menu_settings": "Paramètres...",
        "tray_menu_about": "À propos...",
        "tray_menu_check_updates": "Vérifier les Mises à Jour...",
        "tray_menu_exit": "Quitter",

        "about_title": "À propos de Input Locker",
        "about_project_repo": "DÉPÔT DU PROJET",
        "about_created_by": "CRÉÉ ET MAINTENU PAR",
        "about_updates_title": "🔄  Version du Logiciel & Mises à Jour",
        "about_current_build": "Version actuelle : v{version} (Production)",
        "about_whats_new": "NOUVEAUTÉS DANS CETTE VERSION",
        "about_system_info": "INFORMATIONS SYSTÈME",
        "about_open_source_msg": "💡 Développé en Open Source pour la communauté événementielle et régie AV.\nRetours, suggestions et contributions bienvenus !",
        "about_up_to_date": "Input Locker v{version} est la version la plus récente.",
        "about_update_avail": "Nouvelle version : {version} disponible !",

        "tut_title": "Bienvenue dans Input Locker — Guide de Démarrage Rapide",
        "tut_welcome": "Bienvenue dans Input Locker",
        "tut_subtitle": "Guide rapide : comment verrouiller, protéger et déverrouiller votre poste en sécurité.",
        "tut_step1_title": "Étape 1 : Comment Verrouiller l'Écran",
        "tut_step1_badge": "{hotkey} ou Cliquer Verrouiller",
        "tut_step1_desc": "Appuyez sur {hotkey} ou cliquez sur 'Verrouiller'. Les moteurs de rendu vidéo continuent de tourner visiblement et sans interruption.",
        "tut_step2_title": "Étape 2 : Comment Déverrouiller l'Écran",
        "tut_step2_badge": "{hotkey}",
        "tut_step2_desc": "Appuyez sur {hotkey} pour déverrouiller. Si un mot de passe est configuré, la saisie apparaît.",
        "tut_step3_title": "Étape 3 : Protection Régie & Matériel",
        "tut_step3_badge": "Touche Windows Bloquée",
        "tut_step3_desc": "Les touches Windows et Win+L sont neutralisées pendant le verrouillage pour éviter toute coupure inopinée.",
        "tut_step4_title": "Étape 4 : Icône dans la Barre des Tâches",
        "tut_step4_badge": "Zone de Notification",
        "tut_step4_desc": "Faites un clic droit sur l'icône dans la barre des tâches pour basculer le verrouillage ou accéder aux paramètres.",
        "tut_btn_got_it": "  ✓ Compris — Utiliser Input Locker  ",
    },

    "de": {
        "app_name": "Input Locker",
        "app_tagline": "AV-Bühnen-Eingabesperre & Signalabfang",
        "app_desc": "Hochleistungsfähiges Windows AV-Bühnen-Sperrbildschirm-Tool zum Abfangen von Tastatur- und Mauseingaben bei laufenden Rendering-Engines.",
        "version_tag": "v{version} Produktion",
        "open_source": "Open Source",
        "mit_license": "MIT-Lizenz",
        "windows_tag": "Windows 10/11",

        "btn_lock_now": "🔒 Bildschirm Jetzt Sperren",
        "btn_lock_now_header": "🔒 Bildschirm Sperren",
        "btn_check_updates": "🔄 Nach Updates Suchen",
        "btn_checking": "Suche...",
        "btn_about": "👤 Über",
        "btn_guide": "📖 Anleitung",
        "btn_cancel": "Abbrechen",
        "btn_run_background": "Im Hintergrund Ausführen ({hotkey} zum Sperren)",
        "btn_save_apply": "Speichern & Anwenden",
        "btn_browse": "📁 Durchsuchen...",
        "btn_remove": "✕ Entfernen",
        "btn_close": "Schließen",

        "guide_how_to_unlock": "🔑  ENTSPERREN:",
        "guide_how_to_lock": "🔒  SPERREN:",
        "guide_unlock_instruction": "Drücken Sie jederzeit {hotkey} gleichzeitig, um das Passwort einzugeben und zu entsperren.",

        "card_wallpaper_title": "SPERRBILDSCHIRM-HINTERGRUND",
        "card_wallpaper_subtitle": "Hintergrundbild für das Hauptdisplay",
        "wp_badge_active": "🔒 Sperrbildschirm Aktiv",
        "wp_badge_glass": "Dunkler Milchglas-Modus (Standard-Pass-Through)",

        "card_security_title": "SICHERHEIT & ANMELDEDATEN",
        "badge_password_protected": "🔒 Passwortgeschützt",
        "badge_no_password": "🔓 Kein Passwort Erforderlich (Nur Tastenkürzel)",
        "badge_password_removed": "🔓 Passwort Entfernt (Anwenden zum Speichern)",
        "label_unlock_password": "Entsperr-Passwort (leer lassen für sofortiges Entsperren)",
        "label_confirm_password": "Passwort Bestätigen",
        "btn_remove_password": "✕ Passwort Entfernen",
        "err_password_mismatch": "⚠ Passwörter stimmen nicht überein.",
        "err_invalid_wallpaper": "Datei nicht gefunden:\n{path}",
        "hint_unlock_flow": "💡 Entsperren: Tastenkombination drücken → Passwort eingeben → Enter.",

        "card_shortcuts_title": "TASTENKÜRZEL & AUDIO-FEEDBACK",
        "card_shortcuts_subtitle": "Benutzerdefinierte Trigger & akustische Signale (FOH / Bühne)",
        "label_lock_trigger": "Sperr-Trigger:",
        "label_unlock_combo": "Entsperr-Kombination:",
        "chk_audio_feedback": "🔊 Akustisches Signal bei Statusänderungen (Sperren / Entsperren) abspielen",
        "hint_audio_feedback": "Bietet hörbare Bestätigung in dunklen FOH-Regieräumen und AV-Racks.",
        "err_invalid_lock_hotkey": "Ungültiges Sperrkürzel '{hotkey}':\n{error}",
        "err_invalid_unlock_hotkey": "Ungültiges Entsperrkürzel '{hotkey}':\n{error}",

        "card_preferences_title": "EINSTELLUNGEN & SPRACHE",
        "label_language": "Sprache / Language / Idioma:",
        "chk_auto_updates": "Beim Start automatisch nach Updates suchen (offline-sicher)",

        "tray_menu_lock": "Bildschirm Sperren",
        "tray_menu_unlock": "Bildschirm Entsperren",
        "tray_menu_settings": "Einstellungen...",
        "tray_menu_about": "Über...",
        "tray_menu_check_updates": "Nach Updates Suchen...",
        "tray_menu_exit": "Beenden",

        "about_title": "Über Input Locker",
        "about_project_repo": "PROJEKT-REPOSITORY",
        "about_created_by": "ERSTELLT & BETREUT VON",
        "about_updates_title": "🔄  Softwareversion & Updates",
        "about_current_build": "Aktuelle Version: v{version} (Produktion)",
        "about_whats_new": "NEUERUNGEN IN DIESER VERSION",
        "about_system_info": "SYSTEMINFORMATIONEN",
        "about_open_source_msg": "💡 Als Open-Source für die AV- und Live-Produktions-Community entwickelt.\nFeedback und Beiträge sind herzlich willkommen!",
        "about_up_to_date": "Input Locker v{version} ist die neueste Version.",
        "about_update_avail": "Neuere Version {version} verfügbar!",

        "tut_title": "Willkommen bei Input Locker — Schnellanleitung",
        "tut_welcome": "Willkommen bei Input Locker",
        "tut_subtitle": "Schnellanleitung: Arbeitsstation sperren, schützen und sicher entsperren.",
        "tut_step1_title": "Schritt 1: Bildschirm Sperren",
        "tut_step1_badge": "{hotkey} oder Klick",
        "tut_step1_desc": "Drücken Sie {hotkey} oder klicken Sie auf 'Jetzt Sperren'. Videowiedergabe-Engines laufen ununterbrochen weiter.",
        "tut_step2_title": "Schritt 2: Bildschirm Entsperren",
        "tut_step2_badge": "{hotkey}",
        "tut_step2_desc": "Drücken Sie {hotkey} zum Entsperren. Falls ein Passwort gesetzt ist, erscheint die Passworteingabe.",
        "tut_step3_title": "Schritt 3: Hardware-Schutz auf der Bühne",
        "tut_step3_badge": "Windows-Taste Blockiert",
        "tut_step3_desc": "Versehentliches Betätigen der Windows-Taste wird aktiv neutralisiert.",
        "tut_step4_title": "Schritt 4: Tray-Symbol & Hintergrundbetrieb",
        "tut_step4_badge": "Infobereich",
        "tut_step4_desc": "Rechtsklick auf das Symbol im Infobereich öffnet Schnellaktionen und Einstellungen.",
        "tut_btn_got_it": "  ✓ Verstanden — Input Locker Starten  ",
    },

    "ja": {
        "app_name": "Input Locker",
        "app_tagline": "AVステージング ロック＆入力傍受ユーティリティ",
        "app_desc": "ライブAVステージング環境向けに設計された高性能Windowsロック画面。レンダリングエンジンを実行したままキーボード・マウス入力を完全に遮断します。",
        "version_tag": "v{version} プロダクション",
        "open_source": "オープンソース",
        "mit_license": "MITライセンス",
        "windows_tag": "Windows 10/11",

        "btn_lock_now": "🔒 今すぐ画面をロック",
        "btn_lock_now_header": "🔒 画面ロック",
        "btn_check_updates": "🔄 アップデートを確認",
        "btn_checking": "確認中...",
        "btn_about": "👤 詳細情報",
        "btn_guide": "📖 ガイド",
        "btn_cancel": "キャンセル",
        "btn_run_background": "バックグラウンドで待機 ({hotkey} でロック)",
        "btn_save_apply": "保存して適用",
        "btn_browse": "📁 参照...",
        "btn_remove": "✕ 削除",
        "btn_close": "閉じる",

        "guide_how_to_unlock": "🔑  ロック解除方法:",
        "guide_how_to_lock": "🔒  ロック方法:",
        "guide_unlock_instruction": "ロック中に {hotkey} を同時に押すとパスワード入力が表示され解除できます。",

        "card_wallpaper_title": "ロック画面の壁紙",
        "card_wallpaper_subtitle": "メインディスプレイの背景画像",
        "wp_badge_active": "🔒 ロック画面アクティブ",
        "wp_badge_glass": "ダークブラーグラスモード（デフォルト透過表示）",

        "card_security_title": "セキュリティ＆パスワード",
        "badge_password_protected": "🔒 パスワード保護中",
        "badge_no_password": "🔓 パスワードなし（ショートカットのみ）",
        "badge_password_removed": "🔓 パスワードを削除（適用で保存）",
        "label_unlock_password": "解除パスワード（即時解除する場合は空白）",
        "label_confirm_password": "パスワードの確認",
        "btn_remove_password": "✕ パスワードを削除",
        "err_password_mismatch": "⚠ パスワードが一致しません。",
        "err_invalid_wallpaper": "ファイルが見つかりません:\n{path}",
        "hint_unlock_flow": "💡 解除手順: ロック中にショートカット押下 → パスワード入力 → Enter",

        "card_shortcuts_title": "ショートカット＆オーディオフィードバック",
        "card_shortcuts_subtitle": "カスタムトリガー＆確認音（FOH・ステージング用）",
        "label_lock_trigger": "ロックキー:",
        "label_unlock_combo": "解除キー:",
        "chk_audio_feedback": "🔊 状態切り替え（ロック／解除）時に確認チャイムを再生",
        "hint_audio_feedback": "暗いFOHブースや機材ラックでも音声で状態を確認できます。",
        "err_invalid_lock_hotkey": "無効なロックショートカット '{hotkey}':\n{error}",
        "err_invalid_unlock_hotkey": "無効な解除ショートカット '{hotkey}':\n{error}",

        "card_preferences_title": "設定＆言語",
        "label_language": "言語 / Language / Idioma:",
        "chk_auto_updates": "起動時にアップデートを自動確認（オフライン対応・テレメトリなし）",

        "tray_menu_lock": "画面をロック",
        "tray_menu_unlock": "画面のロックを解除",
        "tray_menu_settings": "設定...",
        "tray_menu_about": "詳細情報...",
        "tray_menu_check_updates": "アップデートを確認...",
        "tray_menu_exit": "終了",

        "about_title": "Input Locker について",
        "about_project_repo": "プロジェクトリポジトリ",
        "about_created_by": "開発・メンテナンス",
        "about_updates_title": "🔄  ソフトウェアバージョン＆更新",
        "about_current_build": "現在のビルド: v{version} (プロダクション)",
        "about_whats_new": "このバージョンの新機能",
        "about_system_info": "システム情報",
        "about_open_source_msg": "💡 AV＆ライブ制作コミュニティ向けにオープンソースとして開発されています。\nご意見やフィードバックを歓迎します！",
        "about_up_to_date": "Input Locker v{version} は最新バージョンです。",
        "about_update_avail": "新しいビルド {version} が利用可能です！",

        "tut_title": "Input Locker へようこそ — クイックスタートガイド",
        "tut_welcome": "Input Locker へようこそ",
        "tut_subtitle": "ワークステーションを安全にロック・保護・解除するクイックガイド。",
        "tut_step1_title": "ステップ1: 画面をロックする方法",
        "tut_step1_badge": "{hotkey} またはクリック",
        "tut_step1_desc": "{hotkey} を押すか「今すぐ画面をロック」をクリックします。ビデオ再生エンジンは背景で途切れず描画を継続します。",
        "tut_step2_title": "ステップ2: ロックを解除する方法",
        "tut_step2_badge": "{hotkey}",
        "tut_step2_desc": "{hotkey} を押して解除します。パスワードが設定されている場合は入力画面が開きます。",
        "tut_step3_title": "ステップ3: ハードウェア誤操作防止",
        "tut_step3_badge": "Windowsキー無効化",
        "tut_step3_desc": "ロック中はWindowsキーの誤タップやWin+L画面切り替えを自動遮断します。",
        "tut_step4_title": "ステップ4: トレイアイコンと常駐動作",
        "tut_step4_badge": "システムトレイ",
        "tut_step4_desc": "システムトレイのアイコンを右クリックすることで、いつでもロックや設定変更を行えます。",
        "tut_btn_got_it": "  ✓ 確認 — Input Locker を開始  ",
    },

    "zh": {
        "app_name": "Input Locker",
        "app_tagline": "AV舞台演出锁屏与全局输入拦截",
        "app_desc": "专为舞台演出与AV控台设计的Windows高安全锁屏工具。在阻断键鼠输入的同时，确保背景渲染引擎（Resolume、Watchout、DAW）流畅播放。",
        "version_tag": "v{version} 正式版",
        "open_source": "开源项目",
        "mit_license": "MIT 开源协议",
        "windows_tag": "Windows 10/11",

        "btn_lock_now": "🔒 立即锁定屏幕",
        "btn_lock_now_header": "🔒 立即锁定",
        "btn_check_updates": "🔄 检查更新",
        "btn_checking": "正在检查...",
        "btn_about": "👤 关于",
        "btn_guide": "📖 指南",
        "btn_cancel": "取消",
        "btn_run_background": "后台常驻 ({hotkey} 快速锁定)",
        "btn_save_apply": "保存并应用",
        "btn_browse": "📁 浏览...",
        "btn_remove": "✕ 清除",
        "btn_close": "关闭",

        "guide_how_to_unlock": "🔑  解锁快捷键:",
        "guide_how_to_lock": "🔒  锁定快捷键:",
        "guide_unlock_instruction": "锁定状态下随时同时按下 {hotkey} 即可唤出密码框并解锁屏幕。",

        "card_wallpaper_title": "锁屏壁纸设置",
        "card_wallpaper_subtitle": "主显示器锁定画面背景图像",
        "wp_badge_active": "🔒 锁屏激活状态",
        "wp_badge_glass": "暗色磨砂玻璃模式（默认画面直接透出）",

        "card_security_title": "安全防护与访问凭据",
        "badge_password_protected": "🔒 已设置密码保护",
        "badge_no_password": "🔓 无密码（仅通过快捷键解锁）",
        "badge_password_removed": "🔓 密码已清除（点击应用保存）",
        "label_unlock_password": "解锁密码（留空则直接通过快捷键解锁）",
        "label_confirm_password": "确认密码",
        "btn_remove_password": "✕ 清除密码",
        "err_password_mismatch": "⚠ 两次输入的密码不一致。",
        "err_invalid_wallpaper": "找不到壁纸文件:\n{path}",
        "hint_unlock_flow": "💡 解锁步骤: 锁定状态下按下解锁快捷键 → 输入密码 → 回车确认。",

        "card_shortcuts_title": "快捷键与音频提示",
        "card_shortcuts_subtitle": "自定义触发按键与声效反馈（主控台 / 现场机柜）",
        "label_lock_trigger": "锁定触发键:",
        "label_unlock_combo": "解锁组合键:",
        "chk_audio_feedback": "🔊 状态切换（锁定 / 解锁）时播放提示音",
        "hint_audio_feedback": "在昏暗的主控台与远程机柜环境中提供明确的听觉确认。",
        "err_invalid_lock_hotkey": "无效的锁定快捷键 '{hotkey}':\n{error}",
        "err_invalid_unlock_hotkey": "无效的解锁快捷键 '{hotkey}':\n{error}",

        "card_preferences_title": "首选项与语言设置",
        "label_language": "语言 / Language / Idioma:",
        "chk_auto_updates": "启动时自动检查更新（纯本地离线运行，零遥测隐私）",

        "tray_menu_lock": "锁定屏幕",
        "tray_menu_unlock": "解锁屏幕",
        "tray_menu_settings": "设置...",
        "tray_menu_about": "关于...",
        "tray_menu_check_updates": "检查更新...",
        "tray_menu_exit": "退出",

        "about_title": "关于 Input Locker",
        "about_project_repo": "开源项目仓库",
        "about_created_by": "开发者与维护者",
        "about_updates_title": "🔄  软件版本与更新",
        "about_current_build": "当前版本: v{version} (正式版)",
        "about_whats_new": "本版本更新内容",
        "about_system_info": "系统环境信息",
        "about_open_source_msg": "💡 专为现场演出与 AV 工程社区打造的开源项目。\n欢迎提出改进意见与参与贡献！",
        "about_up_to_date": "Input Locker v{version} 已是最新版本。",
        "about_update_avail": "发现新版本: {version} 可供下载！",

        "tut_title": "欢迎使用 Input Locker — 快速上手指南",
        "tut_welcome": "欢迎使用 Input Locker",
        "tut_subtitle": "快速指南：如何安全锁定、保护与解锁您的演出工作站。",
        "tut_step1_title": "步骤 1: 如何锁定屏幕",
        "tut_step1_badge": "{hotkey} 或点击锁定",
        "tut_step1_desc": "随时按下 {hotkey} 或点击“立即锁定屏幕”。视频播放与渲染引擎保持正常输出与显示。",
        "tut_step2_title": "步骤 2: 如何解锁屏幕",
        "tut_step2_badge": "{hotkey}",
        "tut_step2_desc": "按下 {hotkey} 解锁。若配置了密码，系统将唤出密码框。",
        "tut_step3_title": "步骤 3: 演出硬件防误触保护",
        "tut_step3_badge": "锁定 Windows 徽标键",
        "tut_step3_desc": "在锁定状态下自动屏蔽 Windows 键及 Win+L 切换，杜绝误触事故。",
        "tut_step4_title": "步骤 4: 托盘图标与后台常驻",
        "tut_step4_badge": "任务栏托盘",
        "tut_step4_desc": "右键点击右下角托盘图标可随时进行锁定、解锁或调整设置。",
        "tut_btn_got_it": "  ✓ 已了解 — 开始使用 Input Locker  ",
    },

    "hi": {
        "app_name": "Input Locker",
        "app_tagline": "एवी स्टेजिंग लॉक और इनपुट नियंत्रण",
        "app_desc": "लाइव एवी स्टेजिंग के लिए उच्च-प्रदर्शन विंडोज लॉक स्क्रीन। बैकग्राउंड रेंडरिंग इंजन को बिना बाधा चलाए कीबोर्ड और माउस इनपुट को रोकता है।",
        "version_tag": "v{version} प्रोडक्शन",
        "open_source": "ओपन सोर्स",
        "mit_license": "एमआईटी लाइसेंस",
        "windows_tag": "Windows 10/11",

        "btn_lock_now": "🔒 अभी स्क्रीन लॉक करें",
        "btn_lock_now_header": "🔒 स्क्रीन लॉक करें",
        "btn_check_updates": "🔄 अपडेट जांचें",
        "btn_checking": "जांच जारी है...",
        "btn_about": "👤 बारे में",
        "btn_guide": "📖 गाइड",
        "btn_cancel": "रद्द करें",
        "btn_run_background": "बैकग्राउंड में चलाएं (लॉक करने के लिए {hotkey})",
        "btn_save_apply": "सहेजें और लागू करें",
        "btn_browse": "📁 ब्राउज़ करें...",
        "btn_remove": "✕ हटाएं",
        "btn_close": "बंद करें",

        "guide_how_to_unlock": "🔑  अनलॉक कैसे करें:",
        "guide_how_to_lock": "🔒  लॉक कैसे करें:",
        "guide_unlock_instruction": "लॉक होने पर पासवर्ड दर्ज करने और अनलॉक करने के लिए किसी भी समय {hotkey} एक साथ दबाएं।",

        "card_wallpaper_title": "लॉक स्क्रीन वॉलपेपर",
        "card_wallpaper_subtitle": "मुख्य डिस्प्ले बैकग्राउंड इमेज",
        "wp_badge_active": "🔒 लॉक स्क्रीन सक्रिय",
        "wp_badge_glass": "डार्क ब्लर ग्लास मोड (डिफ़ॉल्ट डिस्प्ले पास-थ्रू)",

        "card_security_title": "सुरक्षा और क्रेडेंशियल",
        "badge_password_protected": "🔒 पासवर्ड द्वारा सुरक्षित",
        "badge_no_password": "🔓 कोई पासवर्ड आवश्यक नहीं (केवल शॉर्टकट)",
        "badge_password_removed": "🔓 पासवर्ड हटाया गया (सहेजने के लिए लागू करें)",
        "label_unlock_password": "अनलॉक पासवर्ड (तत्काल शॉर्टकट अनलॉक के लिए खाली छोड़ें)",
        "label_confirm_password": "पासवर्ड की पुष्टि करें",
        "btn_remove_password": "✕ पासवर्ड हटाएं",
        "err_password_mismatch": "⚠ पासवर्ड मेल नहीं खाते।",
        "err_invalid_wallpaper": "फ़ाइल नहीं मिली:\n{path}",
        "hint_unlock_flow": "💡 अनलॉक निर्देश: लॉक होने पर शॉर्टकट दबाएं → पासवर्ड दर्ज करें → Enter दबाएं।",

        "card_shortcuts_title": "शॉर्टकट और ऑडियो फ़ीडबैक",
        "card_shortcuts_subtitle": "कस्टम ट्रिगर और ध्वनि संकेत (FOH / स्टेजिंग)",
        "label_lock_trigger": "लॉक ट्रिगर:",
        "label_unlock_combo": "अनलॉक कॉम्बो:",
        "chk_audio_feedback": "🔊 स्थिति बदलने पर (लॉक / अनलॉक) ध्वनि संकेत बजाएं",
        "hint_audio_feedback": "अंधेरे कंट्रोल रूम और स्टेजिंग रैक में स्पष्ट श्रव्य पुष्टि प्रदान करता है।",
        "err_invalid_lock_hotkey": "अमान्य लॉक शॉर्टकट '{hotkey}':\n{error}",
        "err_invalid_unlock_hotkey": "अमान्य अनलॉक शॉर्टकट '{hotkey}':\n{error}",

        "card_preferences_title": "प्राथमिकताएं और भाषा",
        "label_language": "भाषा / Language / Idioma:",
        "chk_auto_updates": "लॉन्च पर स्वचालित रूप से अपडेट जांचें (सुरक्षित ऑफलाइन)",

        "tray_menu_lock": "स्क्रीन लॉक करें",
        "tray_menu_unlock": "स्क्रीन अनलॉक करें",
        "tray_menu_settings": "सेटिंग्स...",
        "tray_menu_about": "बारे में...",
        "tray_menu_check_updates": "अपडेट जांचें...",
        "tray_menu_exit": "बाहर निकलें",

        "about_title": "Input Locker के बारे में",
        "about_project_repo": "प्रोजेक्ट रिपॉजिटरी",
        "about_created_by": "निर्माता और अनुरक्षक",
        "about_updates_title": "🔄  सॉफ्टवेयर संस्करण और अपडेट",
        "about_current_build": "वर्तमान संस्करण: v{version} (प्रोडक्शन)",
        "about_whats_new": "इस संस्करण में नया क्या है",
        "about_system_info": "सिस्टम जानकारी",
        "about_open_source_msg": "💡 लाइव प्रोडक्शन और एवी समुदाय के लिए ओपन सोर्स के रूप में निर्मित।\nसुझावों और योगदानों का हार्दिक स्वागत है!",
        "about_up_to_date": "Input Locker v{version} नवीनतम संस्करण है।",
        "about_update_avail": "नया संस्करण {version} उपलब्ध है!",

        "tut_title": "Input Locker में आपका स्वागत है — त्वरित शुरुआत गाइड",
        "tut_welcome": "Input Locker में आपका स्वागत है",
        "tut_subtitle": "त्वरित शुरुआत: अपने वर्कस्टेशन को कैसे लॉक, सुरक्षित और अनलॉक करें।",
        "tut_step1_title": "चरण 1: स्क्रीन कैसे लॉक करें",
        "tut_step1_badge": "{hotkey} या क्लिक",
        "tut_step1_desc": "{hotkey} दबाएं या 'अभी स्क्रीन लॉक करें' पर क्लिक करें। वीडियो इंजन बिना रुके पृष्ठभूमि में चलते रहते हैं।",
        "tut_step2_title": "चरण 2: स्क्रीन कैसे अनलॉक करें",
        "tut_step2_badge": "{hotkey}",
        "tut_step2_desc": "अनलॉक करने के लिए {hotkey} दबाएं। पासवर्ड होने पर पासवर्ड विंडो खुलेगी।",
        "tut_step3_title": "चरण 3: हार्डवेयर सुरक्षा",
        "tut_step3_badge": "विंडोज की ब्लॉक",
        "tut_step3_desc": "आकस्मिक रुकावटों को रोकने के लिए लॉक मोड में विंडोज की को निष्क्रिय कर दिया जाता है।",
        "tut_step4_title": "चरण 4: ट्रे आइकन और पृष्ठभूमि संचालन",
        "tut_step4_badge": "सिस्टम ट्रे",
        "tut_step4_desc": "ट्रे आइकन पर राइट-क्लिक करके कभी भी लॉक/अनलॉक या सेटिंग्स खोल सकते हैं।",
        "tut_btn_got_it": "  ✓ समझ गया — Input Locker का उपयोग शुरू करें  ",
    }
}


class TranslationManager:
    """Manages application locale, string catalog lookups, and parameter formatting."""

    _instance: Optional[TranslationManager] = None

    def __init__(self, default_lang: str = "en") -> None:
        self._current_lang: str = "en"
        self.set_language(default_lang)

    @classmethod
    def get_instance(cls) -> TranslationManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def detect_system_language() -> str:
        """Detect the OS UI language and return a supported 2-letter ISO code."""
        try:
            # Check Windows UI language
            if sys.platform == "win32":
                import ctypes
                windll = getattr(ctypes, "windll", None)
                if windll and hasattr(windll, "kernel32"):
                    lang_id = windll.kernel32.GetUserDefaultUILanguage() & 0xFF
                    # Mapping known PRIMARYLANGIDs
                    primary_map = {
                        0x09: "en",
                        0x0A: "es",
                        0x0C: "fr",
                        0x07: "de",
                        0x11: "ja",
                        0x04: "zh",
                        0x39: "hi",
                    }
                    if lang_id in primary_map:
                        return primary_map[lang_id]

            loc, _ = locale.getdefaultlocale()
            if loc:
                code = loc.split("_")[0].lower()
                if code in SUPPORTED_LANGUAGES:
                    return code
        except Exception as exc:
            logger.debug("Locale detection fallback: %s", exc)

        return "en"

    def set_language(self, lang_code: str) -> None:
        """Set the active language code with fallback to 'en'."""
        if lang_code == "auto" or not lang_code:
            lang_code = self.detect_system_language()

        clean_code = lang_code.strip().lower()
        if clean_code in TRANSLATIONS:
            self._current_lang = clean_code
        else:
            self._current_lang = "en"
        logger.info("Active locale set to: %s (%s)", self._current_lang, SUPPORTED_LANGUAGES.get(self._current_lang, "Unknown"))

    @property
    def current_language(self) -> str:
        return self._current_lang

    def get(self, key: str, **kwargs: Any) -> str:
        """Fetch string by key with language fallback and keyword interpolation."""
        catalog = TRANSLATIONS.get(self._current_lang, TRANSLATIONS["en"])
        template = catalog.get(key)

        if template is None:
            # Fallback to English catalog
            template = TRANSLATIONS["en"].get(key, key)

        if kwargs:
            try:
                return template.format(**kwargs)
            except Exception as exc:
                logger.debug("i18n formatting error for key '%s': %s", key, exc)
                return template

        return template


def t(key: str, **kwargs: Any) -> str:
    """Convenience helper for translation lookups: t('btn_lock_now')"""
    return TranslationManager.get_instance().get(key, **kwargs)


def set_locale(lang_code: str) -> None:
    """Convenience helper to set active language."""
    TranslationManager.get_instance().set_language(lang_code)


def get_current_locale() -> str:
    """Return current language code."""
    return TranslationManager.get_instance().current_language

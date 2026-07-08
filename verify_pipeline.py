"""
verify_pipeline.py
==================
Script de verification automatique a executer apres le merge
du collegue sur la branche main.

Usage :
    python verify_pipeline.py

Le script compare l'etat actuel de main avec le tag v1.0-poc-chrys
et verifie que tous les points critiques du pipeline sont intacts.
"""

import subprocess
import sys
import os

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

OK   = f"{GREEN}[OK]{RESET}"
FAIL = f"{RED}[FAIL]{RESET}"
WARN = f"{YELLOW}[WARN]{RESET}"

errors   = []
warnings = []

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.returncode

def check(label, condition, fatal=True):
    if condition:
        print(f"  {OK}  {label}")
    else:
        print(f"  {FAIL}  {label}")
        if fatal:
            errors.append(label)
        else:
            warnings.append(label)

def file_contains(filepath, *patterns):
    try:
        with open(filepath, encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
        return all(p in content for p in patterns)
    except FileNotFoundError:
        return False

print(f"\n{BOLD}{'='*60}{RESET}")
print(f"{BOLD}  WAGAN - Verification Integrite Pipeline Post-Merge{RESET}")
print(f"{BOLD}{'='*60}{RESET}\n")

# 1. GIT
print(f"{BOLD}[1/5] Verification Git{RESET}")
tag_out, _ = run("git tag -l v1.0-poc-chrys")
check("Tag de reference v1.0-poc-chrys present", bool(tag_out))

diff_out, _ = run("git diff v1.0-poc-chrys HEAD -- whatsapp_bot/ wagan_app/views/ wagan_app/urls.py wagan_project/")
if diff_out:
    print(f"  {WARN}  Differences dans les fichiers critiques - lancez :")
    print(f"         git diff v1.0-poc-chrys HEAD -- whatsapp_bot/ wagan_app/")
    warnings.append("Differences dans les fichiers critiques (verifier manuellement)")
else:
    print(f"  {OK}  Aucune difference dans les fichiers critiques depuis le tag")
print()

# 2. FICHIERS CRITIQUES
print(f"{BOLD}[2/5] Presence des fichiers critiques{RESET}")
CRITICAL_FILES = [
    "whatsapp_bot/celery_tasks.py",
    "whatsapp_bot/nlp_utils.py",
    "whatsapp_bot/qualification.py",
    "whatsapp_bot/views.py",
    "whatsapp_bot/models.py",
    "whatsapp_bot/whatsapp_sender.py",
    "wagan_app/views/users.py",
    "wagan_app/urls.py",
    "nginx/default.conf",
    "docker-compose.yml",
]
for f in CRITICAL_FILES:
    check(f, os.path.isfile(f))
print()

# 3. FONCTIONS CLES
print(f"{BOLD}[3/5] Fonctions cles dans le code{RESET}")
check("process_message_async dans celery_tasks.py",
      file_contains("whatsapp_bot/celery_tasks.py", "def process_message_async"))
check("Deduplication select_for_update dans celery_tasks.py",
      file_contains("whatsapp_bot/celery_tasks.py", "select_for_update"))
check("Machine a etats - mettre_a_jour_statut_prospect dans qualification.py",
      file_contains("whatsapp_bot/qualification.py", "mettre_a_jour_statut_prospect"))
check("NLP - analyser_sentiment_global presente",
      file_contains("whatsapp_bot/nlp_utils.py", "def analyser_sentiment_global"))
check("NLP - filet securite appliquer_filet_securite present",
      file_contains("whatsapp_bot/nlp_utils.py", "def appliquer_filet_securite"))
check("Route whatsapp dans urls.py",
      file_contains("wagan_app/urls.py", "whatsapp") or file_contains("wagan_project/urls.py", "whatsapp"))
check("Route admin/users/delete dans urls.py",
      file_contains("wagan_app/urls.py", "delete"))
check("DeleteUserView dans users.py",
      file_contains("wagan_app/views/users.py", "class DeleteUserView"))
check("ConversationState importe dans views.py",
      file_contains("whatsapp_bot/views.py", "ConversationState"))
print()

# 4. MIGRATIONS
print(f"{BOLD}[4/5] Migrations Django{RESET}")
migrations = [f for f in os.listdir("whatsapp_bot/migrations") if f.endswith(".py") and f != "__init__.py"]
check(f"Au moins 5 migrations presentes ({len(migrations)} trouvees)", len(migrations) >= 5)
check("Migration 0006 (statut_prospect) presente",
      any("0006" in m for m in migrations))
print()

# 5. DOCKER & SECURITE
print(f"{BOLD}[5/5] Docker et Securite{RESET}")
check(".env.example present", os.path.isfile(".env.example"))
tracked_env = subprocess.run("git ls-files .env", shell=True, capture_output=True, text=True).stdout.strip()
check(".env absent du depot git (securite)", not bool(tracked_env))
check(".gitignore contient .env", file_contains(".gitignore", ".env"))
check("celery_worker dans docker-compose.yml", file_contains("docker-compose.yml", "celery_worker"))
check("nginx dans docker-compose.yml", file_contains("docker-compose.yml", "nginx"))
print()

# RAPPORT
print(f"{BOLD}{'='*60}{RESET}")
if not errors and not warnings:
    print(f"{GREEN}{BOLD}  PIPELINE INTACT - Aucun probleme detecte.{RESET}")
elif not errors:
    print(f"{YELLOW}{BOLD}  PIPELINE OK avec {len(warnings)} avertissement(s).{RESET}")
    for w in warnings:
        print(f"    {WARN} {w}")
else:
    print(f"{RED}{BOLD}  ATTENTION - {len(errors)} probleme(s) critique(s) !{RESET}")
    for e in errors:
        print(f"    {FAIL} {e}")
    if warnings:
        for w in warnings:
            print(f"    {WARN} {w}")
print(f"{BOLD}{'='*60}{RESET}\n")
sys.exit(1 if errors else 0)

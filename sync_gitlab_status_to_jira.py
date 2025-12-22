import os
import requests
import json
from dotenv import load_dotenv
import time
import pandas as pd
import sys

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
MASTER_PROJECT_ID = os.getenv("MASTER_PROJECT_ID")
JIRA_URL = os.getenv("JIRA_URL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

CSV_FOLDER = "csv_folder"
UPLOADED_FILE = os.path.join(CSV_FOLDER, "jira_uploaded.csv")  

GITLAB_HEADERS = {
    "PRIVATE-TOKEN": GITLAB_TOKEN,
    "Content-Type": "application/json"
}

JIRA_HEADERS = {
    "Authorization": f"Bearer {JIRA_API_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# HEDEF STATÜLER
TARGET_STATUS_NAMES = ["Done", "Closed", "Bitti", "Tamamlandı", "Kapalı", "Çözülmüş"]
INTERMEDIATE_STATUS_NAMES = ["In Progress", "Devam", "Devam Ediyor", "Yapılıyor"]

def get_closed_gitlab_issues(project_id):
    url = f"https://gitlab.com/api/v4/projects/{project_id}/issues?state=closed&per_page=100"
    r = requests.get(url, headers=GITLAB_HEADERS)
    return r.json() if r.status_code == 200 else []

def get_jira_issue_status(jira_key):
    url = f"{JIRA_URL}/rest/api/2/issue/{jira_key}?fields=status"
    r = requests.get(url, headers=JIRA_HEADERS)
    if r.status_code == 200:
        return r.json()['fields']['status']['name']
    return None

def execute_transition(jira_key, transition_id):
    """Verilen ID ile statü değişikliği yapar."""
    url = f"{JIRA_URL}/rest/api/2/issue/{jira_key}/transitions"
    payload = {"transition": {"id": transition_id}}
    r = requests.post(url, headers=JIRA_HEADERS, json=payload)
    return r.status_code in [200, 204]

def find_transition_id(jira_key, possible_status_names):
    """Belirtilen isimlerden herhangi birine giden transition ID'sini bulur."""
    url = f"{JIRA_URL}/rest/api/2/issue/{jira_key}/transitions"
    r = requests.get(url, headers=JIRA_HEADERS)
    if r.status_code != 200:
        return None
    
    transitions = r.json().get("transitions", [])
    
    # Debug için mevcut yollar
    # print(f"   (Debug) {jira_key} için yollar: {[t['to']['name'] for t in transitions]}")

    for t in transitions:
        if t['to']['name'] in possible_status_names:
            return t['id']
    return None

def smart_transition_to_done(jira_key):
    print(f"   Checking direct path to Done for {jira_key}...")
    direct_id = find_transition_id(jira_key, TARGET_STATUS_NAMES)
    
    if direct_id:
        print(f"   🚀 Direkt yol bulundu (ID: {direct_id}).")
        if execute_transition(jira_key, direct_id):
            print("   ✅ İŞLEM TAMAM: Closed/Done.")
            return

    # 2. ADIM
    print("   ⚠️ Direkt yol yok. 'Devam' (Intermediate) yolu aranıyor...")
    intermediate_id = find_transition_id(jira_key, INTERMEDIATE_STATUS_NAMES)
    
    if intermediate_id:
        print(f"   🔄 Ara durak bulundu (ID: {intermediate_id}). Önce 'Devam'a çekiliyor...")
        if execute_transition(jira_key, intermediate_id):
            print("   ✔️ 'Devam' statüsüne alındı. Bekleniyor...")
            
            time.sleep(2) 
            
            # --- DEBUG BAŞLANGICI ---
            print(f"\n   🕵️  DEBUG: {jira_key} şu an 'In Progress'te. Peki buradan nereye gidilebilir?")
            url = f"{JIRA_URL}/rest/api/2/issue/{jira_key}/transitions"
            temp_r = requests.get(url, headers=JIRA_HEADERS)
            available = temp_r.json().get("transitions", [])
            
            print(f"   👉 Mevcut Seçenekler:")
            for t in available:
                print(f"      - ID: {t['id']} | Name: {t['name']} -> Gideceği Yer: {t['to']['name']}")
            print("   --------------------------------------------------\n")
            # --- DEBUG BİTİŞİ ---

            final_id = find_transition_id(jira_key, TARGET_STATUS_NAMES)
            print(f"   🧐 Aranan Hedef ID (final_id): {final_id}") # Burası None dönüyor diyorsun

            if final_id:
                if execute_transition(jira_key, final_id):
                    print("   ✅✅ İŞLEM TAMAM: Başarıyla kapatıldı.")
                    df = pd.read_csv(UPLOADED_FILE)
                    row_number = df.index[df["Issue key"] == jira_key][0]
                    df.loc[row_number, "Status"] = "Çözülmüş"
                    df.to_csv(UPLOADED_FILE, index=False, encoding="utf-8-sig")
                    print("f{jira_key} uploaded_file de status=çözülmüş olarak güncellendi." )
        
                else:
                    print("   ❌ HATA: 'Done' yapılamadı.")
            else:
                print("   ❌ HATA: Hedef statüye uygun geçiş bulunamadı. (Yukarıdaki listeyi kontrol et)")
           
def extract_jira_key_from_labels(labels):
    for label in labels:
        if "-" in label and label.split("-")[0].isupper() and label.split("-")[1].isdigit():
            return label
    return None

if __name__ == "__main__":
    print("🔄 Zeki GitLab -> Jira Status Senkronizasyonu Başlıyor...\n")
    
    closed_issues = get_closed_gitlab_issues(MASTER_PROJECT_ID)
    print(f"🔎 GitLab Master Projede {len(closed_issues)} kapalı issue bulundu.")
    
    for issue in closed_issues:
        gitlab_iid = issue['iid']
        labels = issue.get('labels', [])
        jira_key = extract_jira_key_from_labels(labels)
        
        if not jira_key:
            continue
            
        print(f"\n--- İşleniyor: GitLab #{gitlab_iid} -> Jira {jira_key} ---")
        
        current_jira_status = get_jira_issue_status(jira_key)
        
        if not current_jira_status:
            print("❌ Jira statusu okunamadı.")
            continue
            
        if current_jira_status in TARGET_STATUS_NAMES:
            print(f"ℹ️  Jira zaten kapalı ({current_jira_status}).")
            df = pd.read_csv(UPLOADED_FILE)
            row_number = df.index[df["Issue key"] == jira_key][0]
            df.loc[row_number, "Status"] = "Çözülmüş"
            df.to_csv(UPLOADED_FILE, index=False, encoding="utf-8-sig")
            print("f{jira_key} uploaded_file de status=çözülmüş olarak güncellendi." )
            continue
        
        # Fonksiyonu çağır
        smart_transition_to_done(jira_key)  
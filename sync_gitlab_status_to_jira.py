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

GITLAB_HEADERS = {"PRIVATE-TOKEN": GITLAB_TOKEN, "Content-Type": "application/json"}
JIRA_HEADERS = {
    "Authorization": f"Bearer {JIRA_API_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# --- DEBUG YÖNETİMİ ---
DEBUG_MODE = False
if "--debug" in sys.argv:
    DEBUG_MODE = True
    print("🐞 DEBUG MODU AKTİF: Status geçişleri detaylı incelenecek...")

TARGET_STATUS_NAMES = ["Done", "Closed", "Bitti", "Tamamlandı", "Kapalı", "Çözülmüş"]
INTERMEDIATE_STATUS_NAMES = ["In Progress", "Devam", "Devam Ediyor", "Yapılıyor"]

def debug_print(msg):
    if DEBUG_MODE: print(f"   🐛 [DEBUG] {msg}")

def get_closed_gitlab_issues(project_id):
    debug_print(f"GitLab kapalı issue'lar çekiliyor... (PID: {project_id})")
    url = f"https://gitlab.com/api/v4/projects/{project_id}/issues?state=closed&per_page=100"
    r = requests.get(url, headers=GITLAB_HEADERS)
    if r.status_code == 200:
        data = r.json()
        debug_print(f"GitLab'den {len(data)} adet kapalı issue geldi.")
        return data
    else:
        print(f"❌ GitLab Bağlantı Hatası: {r.status_code} - {r.text}")
        return []

def get_jira_issue_status(jira_key):
    url = f"{JIRA_URL}/rest/api/2/issue/{jira_key}?fields=status"
    r = requests.get(url, headers=JIRA_HEADERS)
    if r.status_code == 200:
        stat = r.json()['fields']['status']['name']
        debug_print(f"{jira_key} Mevcut Status: {stat}")
        return stat
    print(f"❌ HATA: Jira status alınamadı ({jira_key}): {r.status_code}")
    debug_print(f"Hata Detayı: {r.text}")
    return None

def execute_transition(jira_key, transition_id):
    url = f"{JIRA_URL}/rest/api/2/issue/{jira_key}/transitions"
    payload = {"transition": {"id": transition_id}}
    r = requests.post(url, headers=JIRA_HEADERS, json=payload)
    if r.status_code in [200, 204]: return True
    debug_print(f"Geçiş başarısız (ID: {transition_id}): {r.text}")
    return False

def find_transition_id(jira_key, possible_status_names, verbose=False):
    url = f"{JIRA_URL}/rest/api/2/issue/{jira_key}/transitions"
    r = requests.get(url, headers=JIRA_HEADERS)
    if r.status_code != 200: return None
    
    transitions = r.json().get("transitions", [])
    
    # Debug açıksa veya verbose istenirse tüm yolları göster
    if verbose or DEBUG_MODE:
        available = [f"{t['id']}->{t['to']['name']}" for t in transitions]
        debug_print(f"{jira_key} için mevcut yollar: {available}")

    for t in transitions:
        # Büyük küçük harf duyarsız kontrol
        if any(target.lower() == t['to']['name'].lower() for target in possible_status_names):
            return t['id']
    return None

def smart_transition_to_done(jira_key):
    print(f"   Analiz ediliyor: {jira_key} -> Hedef: {TARGET_STATUS_NAMES}")
    
    # 1. Direkt Yol
    direct_id = find_transition_id(jira_key, TARGET_STATUS_NAMES, verbose=False)
    if direct_id:
        print(f"   🚀 Direkt yol bulundu (ID: {direct_id}).")
        if execute_transition(jira_key, direct_id):
            print("   ✅ İŞLEM TAMAM: Statü güncellendi.")
            update_csv_status(jira_key)
            return

    debug_print("Direkt yol yok. Ara durak (Intermediate) aranıyor...")
    
    # 2. Ara Durak
    intermediate_id = find_transition_id(jira_key, INTERMEDIATE_STATUS_NAMES)
    if intermediate_id:
        print(f"   🔄 Ara durak bulundu (ID: {intermediate_id}). Önce buraya alınıyor...")
        if execute_transition(jira_key, intermediate_id):
            print("   ✔️ Ara durağa alındı. 2 saniye bekleniyor...")
            time.sleep(2) 
            
            # Şimdi tekrar Done arıyoruz
            final_id = find_transition_id(jira_key, TARGET_STATUS_NAMES, verbose=True)
            
            if final_id:
                if execute_transition(jira_key, final_id):
                    print("   ✅✅ İŞLEM TAMAM: Başarıyla kapatıldı.")
                    update_csv_status(jira_key)
                else:
                    print("   ❌ HATA: Son adımda statü değiştirilemedi.")
            else:
                print("   ❌ HATA: Ara durağa geldik ama buradan hedefe yol yok.")
                if DEBUG_MODE:
                    print("   👉 Config dosyasındaki statü isimlerini kontrol edin.")
    else:
        print("   ❌ HATA: Ne direkt ne de dolaylı yol bulundu.")
        # Kullanıcıya mevcut yolları gösterelim ki hatayı görsün
        find_transition_id(jira_key, [], verbose=True)

def update_csv_status(jira_key):
    try:
        if os.path.exists(UPLOADED_FILE):
            df = pd.read_csv(UPLOADED_FILE)
            if jira_key in df["Issue key"].values:
                idx = df.index[df["Issue key"] == jira_key][0]
                df.at[idx, "Status"] = "Çözülmüş"
                df.to_csv(UPLOADED_FILE, index=False, encoding="utf-8-sig")
                debug_print(f"CSV güncellendi: {jira_key} -> Çözülmüş")
    except Exception as e:
        debug_print(f"CSV güncelleme hatası: {e}")

def extract_jira_key_from_labels(labels):
    for label in labels:
        if "-" in label and label.split("-")[0].isupper() and label.split("-")[1].isdigit():
            return label
    return None

if __name__ == "__main__":
    print("🔄 Zeki GitLab -> Jira Status Senkronizasyonu Başlıyor...\n")
    
    try:
        closed_issues = get_closed_gitlab_issues(MASTER_PROJECT_ID)
    except Exception as e:
        print(f"❌ GitLab Bağlantı Hatası: {e}")
        sys.exit(1)

    print(f"🔎 GitLab Master Projede {len(closed_issues)} kapalı issue bulundu.")
    
    for issue in closed_issues:
        gitlab_iid = issue['iid']
        labels = issue.get('labels', [])
        jira_key = extract_jira_key_from_labels(labels)
        
        if not jira_key: continue
            
        print(f"\n--- İşleniyor: GitLab #{gitlab_iid} -> Jira {jira_key} ---")
        
        current_jira_status = get_jira_issue_status(jira_key)
        
        if not current_jira_status: continue
            
        if any(s.lower() == current_jira_status.lower() for s in TARGET_STATUS_NAMES):
            print(f"ℹ️  Jira zaten kapalı ({current_jira_status}).")
            update_csv_status(jira_key)
            continue
        
        smart_transition_to_done(jira_key)
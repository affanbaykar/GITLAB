import requests
import csv
import os
from dotenv import load_dotenv
import sys
import json

# Windows konsolunda emoji hatasını önlemek için UTF-8 zorlaması
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
                           
load_dotenv()

JIRA_URL = os.getenv("JIRA_URL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

OUTPUT_FOLDER = "csv_folder"
OUTPUT_FILE = os.path.join(OUTPUT_FOLDER, "jira_latest.csv")
SEARCH_URL = f"{JIRA_URL}/rest/api/2/search"

def debug_print(msg, debug_mode):
    if debug_mode:
        print(f"   🐛 [DEBUG] {msg}")

def fetch_jira_csv(jql_query="", debug_mode=False):
    """
    Jira'dan verileri çeker. Debug modu açıksa her adımı raporlar.
    """
    print(f"🔄 Jira Veri Çekme İşlemi Başlatıldı... (Debug: {'AÇIK' if debug_mode else 'KAPALI'})")
    
    debug_print(f"Hedef URL: {JIRA_URL}", debug_mode)
    debug_print(f"Kullanılan JQL: {jql_query}", debug_mode)

    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        debug_print(f"Klasör oluşturuldu: {OUTPUT_FOLDER}", debug_mode)

    # İstenen alanlar
    fields_to_fetch = "key,summary,description,status,assignee,priority,created,duedate,customfield_10601,labels,timetracking,attachment"
    
    params = {
        "jql": jql_query,
        "maxResults": 100,
        "fields": fields_to_fetch
    }
    
    headers = {
        "Authorization": f"Bearer {JIRA_API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        debug_print("API İsteği gönderiliyor...", debug_mode)
        response = requests.get(SEARCH_URL, headers=headers, params=params)
        
        debug_print(f"API Cevap Kodu: {response.status_code}", debug_mode)

        if response.status_code != 200:
            print(f"❌ Jira API Bağlantı Hatası! Kod: {response.status_code}")
            print(f"   Detay: {response.text}")
            return 0

        data = response.json()
        issues = data.get("issues", [])
        
        debug_print(f"Çekilen Ham Issue Sayısı: {len(issues)}", debug_mode)
        
        if not issues:
            print("⚠️ UYARI: Sorgu çalıştı ama 0 kayıt döndü.")
            if debug_mode:
                print("   👉 İpucu: JQL tarih aralığını veya Proje ismini kontrol et.")
            
            # Boş dosya oluştur (Hata almamak için)
            with open(OUTPUT_FILE, mode='w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["Issue key", "Summary", "Description", "Status", "Assignee", 
                                 "Priority", "Created", "Due Date", "İlgili Stajyerler", 
                                 "Labels", "Original Estimate", "Time Spent", "Attachments"])
            return 0

        # --- DETAYLI SÜTUN KONTROLÜ (X-RAY) ---
        if debug_mode and issues:
            print("   🔎 [X-RAY] İlk kaydın sütunları inceleniyor...")
            sample_fields = issues[0].get("fields", {})
            
            # Kritik alan kontrolü
            check_list = {
                "customfield_10601": "İlgili Stajyerler",
                "priority": "Öncelik",
                "status": "Statü",
                "assignee": "Atanan Kişi"
            }
            
            for field_key, field_name in check_list.items():
                if field_key not in sample_fields:
                    print(f"   🚩 [UYARI] '{field_name}' ({field_key}) alanı Jira'dan gelen veride YOK! (None döndü)")
                else:
                    val = sample_fields.get(field_key)
                    print(f"      ✅ {field_name} okundu. Örnek Veri: {val if val else 'Boş'}")

        # CSV Yazma
        with open(OUTPUT_FILE, mode='w', newline='', encoding='utf-8-sig') as file:
            writer = csv.writer(file)
            headers = ["Issue key", "Summary", "Description", "Status", "Assignee", 
                       "Priority", "Created", "Due Date", "İlgili Stajyerler", 
                       "Labels", "Original Estimate", "Time Spent", "Attachments"]
            writer.writerow(headers)

            for issue in issues:
                fields = issue.get("fields", {})
                
                key = issue.get("key")
                summary = fields.get("summary", "")
                description = fields.get("description", "")
                status = fields.get("status", {}).get("name", "")
                assignee = fields.get("assignee", {}).get("name", "") if fields.get("assignee") else ""
                priority = fields.get("priority", {}).get("name", "")
                created = fields.get("created", "")
                duedate = fields.get("duedate", "")
                
                # Özel Alan: İlgili Stajyerler
                stajyerler_raw = fields.get("customfield_10601")
                stajyerler = ""
                if stajyerler_raw:
                    if isinstance(stajyerler_raw, list):
                        stajyerler = ",".join([s.get("name", "") for s in stajyerler_raw if isinstance(s, dict)])
                    elif isinstance(stajyerler_raw, dict):
                        stajyerler = stajyerler_raw.get("name", "")

                labels = ",".join(fields.get("labels", []))
                
                timetracking = fields.get("timetracking", {})
                original_estimate = timetracking.get("originalEstimateSeconds", "")
                time_spent = timetracking.get("timeSpentSeconds", "")

                attachments_raw = fields.get("attachment", [])
                attachment_urls = []
                if attachments_raw:
                    for att in attachments_raw:
                        filename = att.get("filename", "unknown")
                        content_url = att.get("content", "")
                        attachment_urls.append(f"{filename}::{content_url}")
                attachments_str = " | ".join(attachment_urls)

                writer.writerow([
                    key, summary, description, status, assignee, 
                    priority, created, duedate, stajyerler, 
                    labels, original_estimate, time_spent, attachments_str
                ])

        print(f"✅ Jira'dan {len(issues)} kayıt başarıyla CSV'ye aktarıldı.")
        return len(issues)

    except Exception as e:
        print(f"❌ KRİTİK HATA (fetch_jira_csv): {e}")
        if debug_mode:
            import traceback
            traceback.print_exc()
        return 0

if __name__ == "__main__":
    # Test amaçlı manuel çalıştırma
    fetch_jira_csv(debug_mode=True)
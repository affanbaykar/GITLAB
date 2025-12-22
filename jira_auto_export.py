import requests
import csv
import os
from dotenv import load_dotenv
import sys

# Windows konsolunda emoji hatasını önlemek için UTF-8 zorlaması
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
                           
# .env dosyasını yükle
load_dotenv()

# Ortam değişkenlerini al
JIRA_URL = os.getenv("JIRA_URL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN") # Buraya PAT (Personal Access Token) gelecek

# Çıktı klasörü ve dosya yolu
OUTPUT_FOLDER = "csv_folder"
OUTPUT_FILE = os.path.join(OUTPUT_FOLDER, "jira_latest.csv")

# Jira API Endpoint
SEARCH_URL = f"{JIRA_URL}/rest/api/2/search"

def fetch_jira_csv(jql_query=""):
    """
    Jira'dan verilen JQL sorgusuna göre issue'ları çeker ve CSV'ye yazar.
    Artık 'Attachment' (Dosya Ekleri) bilgisini de çekiyor.
    """
    
    # Klasör yoksa oluştur
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    # 1. API İsteği Hazırlığı
    # 'fields' parametresine 'attachment' ekledik!
    params = {
        "jql": jql_query,
        "maxResults": 100,
        "fields": "key,summary,description,status,assignee,priority,created,duedate,customfield_10601,labels,timetracking,attachment" 
    }
    
    # --- YENİ YETKİLENDİRME (Bearer Token) ---
    # Az önce testte çalışan yöntem budur.
    headers = {
        "Authorization": f"Bearer {JIRA_API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        #print(f"🔄 Jira Sorgusu Çalıştırılıyor: {jql_query}")
        # auth=(...) yerine headers=headers kullanıyoruz
        response = requests.get(SEARCH_URL, headers=headers, params=params)
        
        if response.status_code != 200:
            print(f"❌ Jira API Hatası: {response.status_code} {response.text}")
            return 0

        data = response.json()
        issues = data.get("issues", [])
        
        if not issues:
            print("⚠️ Sorgu sonucu boş döndü (0 issue).")
            # Boş dosya oluştur (Hata almamak için)
            with open(OUTPUT_FILE, mode='w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["Issue key", "Summary", "Description", "Status", "Assignee", 
                                 "Priority", "Created", "Due Date", "İlgili Stajyerler", 
                                 "Labels", "Original Estimate", "Time Spent", "Attachments"])
            return 0

        # 2. CSV Yazma İşlemi
        with open(OUTPUT_FILE, mode='w', newline='', encoding='utf-8-sig') as file:
            writer = csv.writer(file)
            
            # Başlık Satırı (Attachments eklendi)
            headers = ["Issue key", "Summary", "Description", "Status", "Assignee", 
                       "Priority", "Created", "Due Date", "İlgili Stajyerler", 
                       "Labels", "Original Estimate", "Time Spent", "Attachments"]
            writer.writerow(headers)

            for issue in issues:
                fields = issue.get("fields", {})
                
                # --- Temel Alanlar ---
                key = issue.get("key")
                summary = fields.get("summary", "")
                description = fields.get("description", "")
                status = fields.get("status", {}).get("name", "")
                
                assignee_raw = fields.get("assignee")
                assignee = assignee_raw.get("name", "") if assignee_raw else ""
                
                priority = fields.get("priority", {}).get("name", "")
                created = fields.get("created", "")
                duedate = fields.get("duedate", "")
                
                # Özel Alan: İlgili Stajyerler (customfield_10601)
                stajyerler_raw = fields.get("customfield_10601")
                stajyerler = ""
                if stajyerler_raw:
                    if isinstance(stajyerler_raw, list):
                        stajyer_names = [s.get("name", "") for s in stajyerler_raw if isinstance(s, dict)]
                        stajyerler = ",".join(stajyer_names)
                    elif isinstance(stajyerler_raw, dict):
                        stajyerler = stajyerler_raw.get("name", "")

                # Etiketler
                labels = ",".join(fields.get("labels", []))

                # Zaman Takibi
                timetracking = fields.get("timetracking", {})
                original_estimate = timetracking.get("originalEstimateSeconds", "")
                time_spent = timetracking.get("timeSpentSeconds", "")

                # --- YENİ: ATTACHMENTS İŞLEME ---
                attachments_raw = fields.get("attachment", [])
                attachment_urls = []
                
                if attachments_raw:
                    for att in attachments_raw:
                        # Format: "DosyaAdi::URL"
                        filename = att.get("filename", "unknown")
                        content_url = att.get("content", "")
                        attachment_urls.append(f"{filename}::{content_url}")
                
                # Linkleri " | " ile ayırarak tek hücreye yaz
                attachments_str = " | ".join(attachment_urls)

                # Satırı Yaz
                writer.writerow([
                    key, summary, description, status, assignee, 
                    priority, created, duedate, stajyerler, 
                    labels, original_estimate, time_spent, attachments_str
                ])

        print(f"✅ Jira'dan sorgu ile eşleşen --{len(issues)}-- issue çekildi.")
        #print(f"🆕 '{OUTPUT_FILE}' dosyası güncellendi (Ekler Dahil).")
        return len(issues)

    except Exception as e:
        print(f"❌ Hata oluştu: {e}")
        return 0

if __name__ == "__main__":
    fetch_jira_csv()
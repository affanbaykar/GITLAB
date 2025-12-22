import csv
import requests
import pandas as pd
import os
from dateutil import parser
from dotenv import load_dotenv
from jira_auto_export import fetch_jira_csv
from compare_issues import compare_issues
import sys
import json
import tempfile 

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    
# .env dosyasını yükle
load_dotenv()

# --- .ENV DEĞİŞKENLERİ ---
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
MASTER_PROJECT_ID = os.getenv("MASTER_PROJECT_ID")
GROUP_ID = os.getenv("GROUP_ID")
JIRA_URL = os.getenv("JIRA_URL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

# --- JIRA İNDİRME İÇİN AUTH HEADER ---
JIRA_AUTH_HEADERS = {
    "Authorization": f"Bearer {JIRA_API_TOKEN}",
    "Accept": "application/json"
}

# --- KONFİGÜRASYON VE MAP DEĞİŞKENLERİ ---
CONFIG_FILE = "config.json"

ASSIGNEE_MAP = {}         
TEAM_PROJECT_MAP = {}     
TEAM_NAME_MAP = {}        

JQL = "" 

def load_config():
    global ASSIGNEE_MAP, TEAM_PROJECT_MAP, TEAM_NAME_MAP, JQL
    
    if not os.path.exists(CONFIG_FILE):
        print(f"⚠️ UYARI: {CONFIG_FILE} bulunamadı! Varsayılan ayarlar kullanılacak.")
        return

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if "settings" in data and "default_jql" in data["settings"]:
            if len(sys.argv) <= 1: 
                JQL = data["settings"]["default_jql"]
                print(f"⚙️ Config dosyasından JQL yüklendi: {JQL}")

        if "user_mappings" in data:
            for item in data["user_mappings"]:
                j_user = item.get("jira_user")
                g_user_id = item.get("gitlab_user_id")
                if j_user and g_user_id: ASSIGNEE_MAP[j_user] = g_user_id

        if "team_mappings" in data:
            for item in data["team_mappings"]:
                j_team = item.get("jira_team_name")
                g_proj_id = item.get("gitlab_project_id")
                f_name = item.get("friendly_name")
                if j_team:
                    if g_proj_id: TEAM_PROJECT_MAP[j_team] = g_proj_id
                    if f_name: TEAM_NAME_MAP[j_team] = f_name
            
        #print("✅ Ayarlar ve veriler config dosyasından başarıyla yüklendi.")

    except Exception as e:
        print(f"❌ Config yükleme hatası: {e}")

# --- YÜKLEMEYİ BAŞLAT ---
load_config()

# --- ARGÜMAN YÖNETİMİ ---
if len(sys.argv) > 1: JQL = sys.argv[1]
MODE = "--preview"
if len(sys.argv) > 2: MODE = sys.argv[2]

HEADERS = {
    "PRIVATE-TOKEN": GITLAB_TOKEN,
}

CSV_FOLDER = "csv_folder"
TO_ADD_FILE = os.path.join(CSV_FOLDER, "jira_to_add.csv")
UPLOADED_FILE = os.path.join(CSV_FOLDER, "jira_uploaded.csv")

# ------------------- ŞABLON YÖNETİMİ -------------------
def load_template(template_name, context):
    template_path = os.path.join("templates", template_name)
    if not os.path.exists(template_path):
        return f"# {context.get('title')}\n\n{context.get('orig_desc')}"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read().format(**context)
    except Exception as e:
        print(f"❌ Şablon hatası: {e}")
        return f"# {context.get('title')}\n\n{context.get('orig_desc')}"

# ------------------- ROBUST CSV OKUYUCU -------------------
def read_jira_csv_robustly(filename):
    issues = []
    try:
        with open(filename, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = [h.strip() for h in next(reader)]
            stajyer_indices = [i for i, col_name in enumerate(header) if "İlgili Stajyerler" in col_name]

            for row_data in reader:
                issue = {}
                stajyer_list_raw = []
                for idx in stajyer_indices:
                    if idx < len(row_data):
                        val = row_data[idx].strip()
                        if val:
                            stajyer_list_raw.extend([s.strip() for s in val.split(",") if s.strip()])
                
                for h, v in zip(header, row_data):
                    issue[h.strip()] = v.strip()
                
                issue["_team_list"] = list(set(stajyer_list_raw))
                issues.append(issue)
                
    except FileNotFoundError:
        print(f"❌ Hata: '{filename}' dosyası bulunamadı.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Hata: CSV okunamadı. Hata: {e}")
        sys.exit(1)
    return issues

# ------------------- DOSYA İŞLEMLERİ -------------------
def process_attachments_for_gitlab(attachments_str, target_project_id):
    if not attachments_str or not attachments_str.strip():
        return None

    markdown_links = []
    file_entries = attachments_str.split(" | ")
    
    print(f"   📎 {len(file_entries)} adet dosya işleniyor...")

    for entry in file_entries:
        if "::" not in entry: continue
        
        filename, download_url = entry.split("::", 1)
        filename = filename.strip()
        download_url = download_url.strip()

        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                with requests.get(download_url, headers=JIRA_AUTH_HEADERS, stream=True) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=8192):
                        tmp_file.write(chunk)
                tmp_path = tmp_file.name
            
            gl_upload_url = f"https://gitlab.com/api/v4/projects/{target_project_id}/uploads"
            
            with open(tmp_path, 'rb') as f:
                files = {'file': (filename, f)}
                upload_headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
                up_resp = requests.post(gl_upload_url, headers=upload_headers, files=files)
            
            os.remove(tmp_path)

            if up_resp.status_code == 201:
                uploaded_data = up_resp.json()
                md_link = uploaded_data.get("markdown")
                if md_link:
                    markdown_links.append(md_link)
                    print(f"     ✅ Yüklendi: {filename}")
            else:
                print(f"     ⚠️ Yükleme Hatası ({filename}): {up_resp.status_code}")

        except Exception as e:
            print(f"     ❌ Dosya İşleme Hatası ({filename}): {e}")

    if markdown_links:
        return ", ".join(markdown_links)
    return None

# ------------------- YARDIMCI FONKSİYONLAR -------------------
def parse_date(date_str):
    if not date_str: return None
    try: return parser.parse(date_str).strftime("%Y-%m-%d")
    except: return None

def seconds_to_gitlab_duration(seconds):
    if not seconds: return None
    try: sec = int(float(seconds))
    except: return None
    if sec <= 0: return None
    hours = sec // 3600
    minutes = (sec % 3600) // 60
    parts = []
    if hours > 0: parts.append(f"{hours}h")
    if minutes > 0: parts.append(f"{minutes}m")
    return " ".join(parts) if parts else "0m"

def link_issues(parent_project_id, parent_iid, target_project_id, target_iid):
    url = f"https://gitlab.com/api/v4/projects/{parent_project_id}/issues/{parent_iid}/links"
    data = {"target_project_id": target_project_id, "target_issue_iid": target_iid, "link_type": "relates_to"}
    requests.post(url, headers={"PRIVATE-TOKEN": GITLAB_TOKEN, "Content-Type": "application/json"}, json=data)

def find_or_create_group_milestone(title):
    url = f"https://gitlab.com/api/v4/groups/{GROUP_ID}/milestones"
    r = requests.get(url, headers={"PRIVATE-TOKEN": GITLAB_TOKEN})
    if r.status_code == 200:
        for m in r.json():
            if m["title"].strip().lower() == title.strip().lower():
                return m
    payload = {"title": title}
    r = requests.post(url, headers={"PRIVATE-TOKEN": GITLAB_TOKEN, "Content-Type": "application/json"}, json=payload)
    if r.status_code == 201:
        print(f"✨ Issue Milestone'u oluşturuldu: {title}")
        return r.json()
    return None

def get_readable_team_names(team_list):
    readable_list = []
    for t in team_list:
        readable_list.append(TEAM_NAME_MAP.get(t, t))
    return readable_list

# ==============================================================================
#                             ANA BLOK
# ==============================================================================
if __name__ == "__main__":
    
    if MODE == "--preview":
        #print(f"📡 Arayüzden Gelen JQL Kullanılıyor: {JQL}")
        try:
            test_resp = requests.get(f"{JIRA_URL}/rest/api/2/myself", headers=JIRA_AUTH_HEADERS)
            if test_resp.status_code == 200: print("✅ Jira API Bağlantısı Başarılı.")
        except: pass

        new_issue_count = fetch_jira_csv(JQL)
        
        if new_issue_count == 0:
            print("\n---------------------------------------------------------")
            print("🛑 Sorgu sonucunda JIRA'dan hiç veri dönmedi veya hata oluştu.")
            print("---------------------------------------------------------")
            sys.exit(0)

        compare_issues()
        
        if not os.path.exists(TO_ADD_FILE):
             print("⚠️ Eklenecek dosya bulunamadı.")
             sys.exit(0)

        rows = read_jira_csv_robustly(TO_ADD_FILE)
        count = len(rows)
        
        if count == 0:
            print("\n✅ Tüm issue'lar zaten güncel. Yeni aktarılacak kayıt yok.")
            sys.exit(0)

        print(f"\nGitlab'e aktarılacak toplam {count} issue tespit edildi.\n")
        
        for i, row in enumerate(rows, start=1):
            jira_key = row.get("Issue key", "")
            summary = row.get("Summary", "")
            teams = row.get("_team_list", [])
            takim_isimleri = get_readable_team_names(teams)
            print(f"--- {i}/{count}: {jira_key} - {summary} ---")
            print(f"➡️  Tespit Edilen Takımlar: {', '.join(takim_isimleri) if takim_isimleri else 'Yok'}\n")
            
        #print("✅ ÖN İZLEME TAMAMLANDI. Devam etmek için 'AKTARIMI ONAYLA' butonuna basın.")

    elif MODE == "--execute":
        
        # Eğer argüman olarak şablon adı geldiyse onu al, yoksa varsayılanı kullan
        SELECTED_TEMPLATE = "standard_template.md"
        if len(sys.argv) > 3:
            SELECTED_TEMPLATE = sys.argv[3]
            print(f"🎨 Seçilen Şablon Kullanılıyor: {SELECTED_TEMPLATE}")
        # --- YENİ EKLENEN KISIM BİTİŞİ ---

        if not os.path.exists(TO_ADD_FILE):
             print("❌ HATA: Önce sorgulama yapmalısınız (jira_to_add.csv yok).")
             sys.exit(1)
             
        rows = read_jira_csv_robustly(TO_ADD_FILE)
        count = len(rows)
        
        if count == 0:
            print("⚠️ Aktarılacak issue bulunamadı.")
            sys.exit(0)

        print(f"🚀 Aktarım Başlıyor... Toplam {count} kayıt işlenecek.\n")
        synced_count = 0

        for i, row in enumerate(rows, start=1):
            title = (row.get("Summary") or "Untitled").strip()
            jira_key = row.get("Issue key") or ""
            
            print(f"\n--- {i}/{count}: İşleniyor {jira_key} - {title} ---")
            
            teams = row.get("_team_list", [])
            takim_isimleri = get_readable_team_names(teams)
            print(f"➡️  Tespit Edilen Takımlar: {', '.join(takim_isimleri) if takim_isimleri else 'Yok'}")
            
            # --- VERİ HAZIRLIĞI ---
            template_context = {
                "jira_key": jira_key,
                "title": title,
                "orig_desc": (row.get("Description") or "Açıklama girilmemiş.").strip(),
                "assignee_name": row.get("Assignee") or "Atanmamış",
                "orig_est": seconds_to_gitlab_duration(row.get("Original Estimate")) or 'Belirtilmemiş',
                "time_spent": seconds_to_gitlab_duration(row.get("Time Spent")) or '0m',
                "due_date": parse_date(row.get("Due Date")) or 'Belirtilmemiş',
                "priority": row.get("Priority") or "Normal",
                "attachment_section": process_attachments_for_gitlab(row.get("Attachments", ""), MASTER_PROJECT_ID) or "_Ek dosya yok._",
                "created_now": pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')
            }

            # Master Template
            full_desc = load_template(SELECTED_TEMPLATE, template_context)

            # Etiketler ve Tarihler
            labels = [l for l in [jira_key, row.get("Priority")] if l]
            if row.get("Labels"): labels += [x.strip() for x in row["Labels"].split(",") if x.strip()]
            labels_str = ",".join(labels)
            due_date = template_context["due_date"] if template_context["due_date"] != 'Belirtilmemiş' else None
            
            # --- 1. Milestone ---
            milestone = find_or_create_group_milestone(title)
            
            # --- 2. Master Issue ---
            assignee_id = ASSIGNEE_MAP.get(row.get("Assignee"))
            master_data = {
                "title": title, "description": full_desc, "labels": labels_str,
                "time_estimate": template_context["orig_est"], "spent_time": template_context["time_spent"]
            }
            if due_date: master_data["due_date"] = due_date
            if assignee_id: master_data["assignee_ids"] = [assignee_id]
            if milestone: master_data["milestone_id"] = milestone["id"]
            
            json_headers = {"PRIVATE-TOKEN": GITLAB_TOKEN, "Content-Type": "application/json"}

            m_resp = requests.post(f"https://gitlab.com/api/v4/projects/{MASTER_PROJECT_ID}/issues", headers=json_headers, json=master_data)
            
            if m_resp.status_code == 201:
                m_issue = m_resp.json()
                m_iid = m_issue["iid"]
                print(f"✅ Ana Issue Oluşturuldu: {title}")
            else:
                print(f"❌ Master issue oluşturulamadı: {m_resp.text}")
                continue 
            
            # --- 3. Child Issues (GÜNCELLENDİ) ---
            for team in teams:
                proj_id = TEAM_PROJECT_MAP.get(team)
                if not proj_id:
                    print(f"  ⚠️  -> '{team}' takımı için Proje ID bulunamadı.")
                    continue
                
                c_assignee = ASSIGNEE_MAP.get(team)
                
                # --- GÜNCEL CHILD ISSUE FORMATI ---
                # 1. Başlık küçültüldü (H3 - ###)
                # 2. Master Template'deki tablo buraya da eklendi
                c_desc = (
                    f"### 🔗 [{jira_key}] {title} (Takım Kopyası)\n\n"
                    f"> **⚠️ DİKKAT:** Bu görev, ana göreve bağlı bir alt görevdir. Kontrol listesi (DoD), dosya ekleri ve detaylı ilerleme takibi için lütfen aşağıdaki **ANA GÖREV** linkini kullanınız.\n"
                    f"> Buradaki değişiklikler diğer takımlara yansımaz.\n\n"
                    f"👉 **[ANA GÖREVE GİT]({m_issue['web_url']})**\n\n"
                    f"--- \n"
                    f"## 📌 Görev Özeti\n{template_context['orig_desc']}\n\n"
                    f"--- \n"
                    f"## 📊 Operasyonel Bilgiler\n\n"
                    f"| Alan | Değer |\n"
                    f"| :--- | :--- |\n"
                    f"| **Tahmin** | `{template_context['orig_est']}` |\n"
                    f"| **Bitiş Tarihi** | `{template_context['due_date']}` |\n"
                    f"| **Öncelik** | `{template_context['priority']}` |\n"
                    f"\n---\n"
                    f"**Ana Görev Linki:** {m_issue['web_url']}"
                )
                
                try: p_name = requests.get(f"https://gitlab.com/api/v4/projects/{proj_id}", headers=json_headers).json().get("name", "Team")
                except: p_name = "Team"

                c_data = {
                    "title": f"{title} ({p_name})", "description": c_desc, "labels": labels_str,
                    "time_estimate": template_context["orig_est"], "spent_time": template_context["time_spent"]
                }
                if due_date: c_data["due_date"] = due_date
                if c_assignee: c_data["assignee_ids"] = [c_assignee]
                if milestone: c_data["milestone_id"] = milestone["id"]

                c_resp = requests.post(f"https://gitlab.com/api/v4/projects/{proj_id}/issues", headers=json_headers, json=c_data)
                
                if c_resp.status_code == 201:
                    c_iid = c_resp.json()["iid"]
                    link_issues(int(MASTER_PROJECT_ID), m_iid, proj_id, c_iid)
                    print(f"  ✅ -> Child Issue Oluşturuldu ({p_name}) ve linklendi.")
                else:
                    print(f"  ⚠️ Child Issue hatası: {c_resp.status_code}")

            # --- 4. CSV Güncelle ---
            if os.path.exists(UPLOADED_FILE) and os.path.getsize(UPLOADED_FILE) > 0:
                udf = pd.read_csv(UPLOADED_FILE, encoding="utf-8-sig")
            else:
                udf = pd.DataFrame(columns=row.keys())
            
            if not ((udf.get('Issue key') == row['Issue key']).any()):
                udf = pd.concat([udf, pd.DataFrame([row])], ignore_index=True)
                udf.to_csv(UPLOADED_FILE, index=False, encoding="utf-8-sig")
                print(f"✔️  '{jira_key}' uploaded CSV'ye eklendi.")
                synced_count += 1
        
        print(f"\n✅ SÜREÇ TAMAMLANDI. Toplam {synced_count} issue aktarıldı.\n")
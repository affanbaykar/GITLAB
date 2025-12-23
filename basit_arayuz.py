import customtkinter as ctk
import subprocess
import threading
import sys
import os
import re
import json
from dotenv import load_dotenv
from PIL import Image

# Görünüm Ayarları
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

class DualSyncApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("GIT ⇌ JIRA Operasyon Merkezi")
        self.geometry("1250x950")

        self.font_title = ("Roboto Medium", 20)
        self.font_console = ("JetBrains Mono", 12)
        self.font_ui = ("Roboto", 12)

        # --- RESİM VE KLASÖR AYARLARI ---
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        logo_folder = os.path.join(self.current_dir, "logo")
        self.csv_folder_path = os.path.join(self.current_dir, "csv_folder")
        self.templates_folder = os.path.join(self.current_dir, "templates")

        # Klasör yoksa oluştur
        if not os.path.exists(self.templates_folder):
            os.makedirs(self.templates_folder)
            # Varsayılan bir şablon oluşturalım
            default_path = os.path.join(self.templates_folder, "standard_template.md")
            if not os.path.exists(default_path):
                with open(default_path, "w", encoding="utf-8") as f:
                    f.write("# {title}\n\n{orig_desc}\n\n---\n**Jira Key:** {jira_key}\n**Ekler:**\n{attachment_section}")

        def load_and_clean_image(filename):
            try:
                path = os.path.join(logo_folder, filename)
                if not os.path.exists(path): return None
                img = Image.open(path).convert("RGBA")
                data = img.getdata()
                new_data = []
                for item in data:
                    if item[0] > 220 and item[1] > 220 and item[2] > 220:
                        new_data.append((255, 255, 255, 0))
                    else:
                        new_data.append(item)
                img.putdata(new_data)
                return ctk.CTkImage(light_image=img, dark_image=img, size=(30, 30))
            except Exception:
                return None

        self.jira_icon = load_and_clean_image("jira-software-logo.png")
        self.git_icon = load_and_clean_image("gitlab-logo.png")

        # ========================================================
        #              ANA SEKMELİ YAPI (TABVIEW)
        # ========================================================
        self.tabview = ctk.CTkTabview(self, width=1200, height=850)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(10, 10))

        # Sekmeleri Oluştur
        self.tab_main = self.tabview.add("🔄 Aktarım Merkezi")
        self.tab_settings = self.tabview.add("⚙️ Ayarlar")

        self.btn_toggle_filter = ctk.CTkButton(self.tab_main, text="🔍 Filtre Paneli (Aç/Kapat)", 
                                        fg_color="#555555", hover_color="#333333",
                                        command=self.toggle_filter_panel)
        self.btn_toggle_filter.pack(fill="x", padx=10, pady=(5, 0))

        # Filtre arayüzünü oluştur (ancak henüz pack etme, toggle yönetecek)
        self.create_filter_ui(self.tab_main) 
        self.filter_frame.pack_forget() # Başlangıçta gizli

        # ========================================================
        #           SEKME 1: AKTARIM MERKEZİ & FİLTRELER
        # ========================================================
        
        # --- BÖLÜNMÜŞ EKRAN YAPISI ---
        self.split_frame = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        self.split_frame.pack(fill="both", expand=True, pady=(10, 10))

        # >>> SOL PANEL (MAVİ) <<<
        self.left_frame = ctk.CTkFrame(self.split_frame, fg_color="#CEE3FA", corner_radius=15)
        self.left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.lbl_left = ctk.CTkLabel(self.left_frame, text="  JIRA ➔ GITLAB", font=self.font_title, text_color="#2B709B", image=self.jira_icon, compound="left")
        self.lbl_left.pack(pady=(15, 10))

        self.btn_left = ctk.CTkButton(
            self.left_frame, text="AKTARIMI BAŞLAT (ÖN İZLEME)", 
            fg_color="#0065FF", hover_color="#0747A6",
            height=50, corner_radius=10, font=("Roboto", 14, "bold"),
            command=self.baslat_sol_thread_preview
        )
        self.btn_left.pack(fill="x", padx=15, pady=10)

        self.console_left = ctk.CTkTextbox(self.left_frame, font=self.font_console, fg_color="#0f0f0f", text_color="#D4D4D4", corner_radius=10)
        self.console_left.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.setup_tags(self.console_left)
        self.console_left.insert("0.0", "Hazır. Verileri çekmek ve ön izlemek için MAVİ butona basın.\n", "dim")

        # --- Aksiyon Paneli ---
        self.action_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        
        self.btn_confirm_left = ctk.CTkButton(self.action_frame, text="✅ ONAYLA VE BAŞLAT", fg_color="#27AE60", hover_color="#1E8449", height=50, corner_radius=10, font=("Roboto", 14, "bold"), command=self.basit_sol_thread_execute)
        self.btn_cancel_left = ctk.CTkButton(self.action_frame, text="❌ İPTAL", fg_color="#C0392B", hover_color="#922B21", height=50, width=100, corner_radius=10, font=("Roboto", 14, "bold"), command=self.islem_iptal_et)
        self.progress_bar = ctk.CTkProgressBar(self.action_frame, height=20, corner_radius=10, progress_color="#27AE60")
        self.progress_bar.set(0)
        self.progress_label = ctk.CTkLabel(self.action_frame, text="İşleniyor: 0%", font=("Roboto", 12))
        self.btn_reset = ctk.CTkButton(self.action_frame, text="🔄 EKRANI TEMİZLE VE YENİ SORGU YAP", fg_color="#2980B9", hover_color="#1F618D", height=50, corner_radius=10, font=("Roboto", 14, "bold"), command=self.ekrani_sifirla)

        # >>> SAĞ PANEL (TURUNCU) <<<
        self.right_frame = ctk.CTkFrame(self.split_frame, fg_color="#F7E1C0", corner_radius=15)
        self.right_frame.pack(side="right", fill="both", expand=True, padx=(10, 0))

        self.lbl_right = ctk.CTkLabel(self.right_frame, text="  GITLAB ➔ JIRA", font=self.font_title, text_color="#E67E22", image=self.git_icon, compound="left")
        self.lbl_right.pack(pady=(15, 10))

        self.btn_right = ctk.CTkButton(
            self.right_frame, text="STATÜLERİ GÜNCELLE", 
            fg_color="#E67E22", hover_color="#D35400",
            height=50, corner_radius=10, font=("Roboto", 14, "bold"),
            command=self.baslat_sag_thread
        )
        self.btn_right.pack(fill="x", padx=15, pady=10)

        self.console_right = ctk.CTkTextbox(self.right_frame, font=self.font_console, fg_color="#0f0f0f", text_color="#D4D4D4", corner_radius=10)
        self.console_right.pack(fill="both", expand=True, padx=10, pady=10)
        self.setup_tags(self.console_right)
        self.console_right.insert("0.0", "Hazır. Status güncellemek için TURUNCU butona basın.\n", "dim")

        # ========================================================
        #           SEKME 2: AYARLAR PANELİ
        # ========================================================
        self.create_settings_tab() 
        self.refresh_dropdown_data() # Dropdownları doldur
        
    def get_template_list(self):
        """templates klasöründeki .md dosyalarını listeler."""
        if not os.path.exists(self.templates_folder):
            os.makedirs(self.templates_folder)
            return ["standard_template.md"]
        
        files = [f for f in os.listdir(self.templates_folder) if f.endswith(".md")]
        if not files:
            return ["standard_template.md"]
        return files

    # --- VERİ YÜKLEME ---
    def get_config_data(self):
        users = []
        teams = []
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            for u in data.get("user_mappings", []):
                name = u.get("jira_user", "").strip()
                if name: users.append(name)
            for t in data.get("team_mappings", []):
                tech_name = t.get("jira_team_name", "").strip()
                if tech_name: teams.append(tech_name)
        except Exception: pass
        return users, teams

    def refresh_dropdown_data(self):
        users, teams = self.get_config_data()
        if hasattr(self, 'combo_assignee'):
            self.combo_assignee.configure(values=users)
            self.combo_assignee.set("Seçiniz...")
        if hasattr(self, 'combo_team'):
            self.combo_team.configure(values=teams)
            self.combo_team.set("Seçiniz...")

    # --- ÇOKLU SEÇİM YARDIMCILARI ---
    def add_to_selection(self, value, container, storage_list):
        if value == "Seçiniz..." or not value: return
        if value in storage_list: return

        storage_list.append(value)
        btn = ctk.CTkButton(container, text=f"{value} ✖", height=24, fg_color="#DDDDDD", text_color="black", hover_color="#C0392B")
        btn.configure(command=lambda b=btn, v=value: self.remove_from_selection(b, v, storage_list))
        btn.pack(side="left", padx=2, pady=2)
        
        # --- OTOMATİK GÜNCELLEME ---
        self.generate_jql_from_ui()

    def remove_from_selection(self, btn, value, storage_list):
        if value in storage_list: storage_list.remove(value)
        btn.destroy()
        # --- OTOMATİK GÜNCELLEME ---
        self.generate_jql_from_ui()
    
    def generate_jql_from_ui(self):
        """Bu metod sadece filtreler değiştiğinde çalışır, manuel JQL'i etkilemez ama tetikleyici olarak durur."""
        pass # Şimdilik sadece tetikleyici olarak tutuyoruz, asıl iş get_jql_from_filters'da.

    def toggle_filter_panel(self):
        if self.filter_frame.winfo_manager(): 
            self.filter_frame.pack_forget()
            self.btn_toggle_filter.configure(text="🔍 Filtre Panelini Göster")
        else: 
            self.filter_frame.pack(fill="x", padx=10, pady=(0, 10), before=self.split_frame)
            self.btn_toggle_filter.configure(text="🔼 Filtre Panelini Gizle")

    def toggle_all(self, var_dict, state):
        for var in var_dict.values(): var.set(state)

    # --- FİLTRELEME ARAYÜZÜ ---
    def create_filter_ui(self, parent):
        self.filter_frame = ctk.CTkFrame(parent, fg_color="#E8E8E8", corner_radius=10)

        # ---------------- 1. SATIR: Proje, Key, Zaman ----------------
        row1 = ctk.CTkFrame(self.filter_frame, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=2)

        ctk.CTkLabel(row1, text="Proje:", font=self.font_ui, text_color="black").pack(side="left", padx=(0, 2))
        self.entry_project = ctk.CTkEntry(row1, width=60)
        self.entry_project.pack(side="left", padx=(0, 10))
        self.entry_project.insert(0, "GYT")

        ctk.CTkLabel(row1, text="Key:", font=self.font_ui, text_color="black").pack(side="left", padx=(0, 2))
        self.entry_key = ctk.CTkEntry(row1, placeholder_text="149", width=60)
        self.entry_key.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(row1, text="Zaman:", font=self.font_ui, text_color="black").pack(side="left", padx=(0, 2))
        self.combo_time = ctk.CTkComboBox(row1, values=["Seçiniz...","Son 1 Saat", "Son 6 Saat", "Son 12 Saat", "Son 24 Saat", "Son 7 Gün", "Son 15 Gün", "Son 30 Gün", "Tüm Zamanlar"], width=110)
        self.combo_time.pack(side="left", padx=(0, 10))
        self.combo_time.set("Seçiniz...")

        ctk.CTkLabel(row1, text="Label:", font=self.font_ui, text_color="black").pack(side="left", padx=(0, 2))
        self.entry_label = ctk.CTkEntry(row1, placeholder_text="frontend", width=90)
        self.entry_label.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(row1, text="Priority:", font=self.font_ui, text_color="black").pack(side="left", padx=(0, 5))
        p_frame = ctk.CTkFrame(row1, fg_color="white", corner_radius=6, border_width=1, border_color="#CCC")
        p_frame.pack(side="left", fill="x", padx=(0, 10))
        
        self.vars_priority = {}
        priorities = ["Ölümcül", "Majör", "Kritik", "Minör", "Düşük"]

        def on_prio_change(selected_p):
            if self.vars_priority[selected_p].get():
                for p_name, var in self.vars_priority.items():
                    if p_name != selected_p: var.set(False)

        for p in priorities:
            var = ctk.BooleanVar(value=False) 
            cb = ctk.CTkCheckBox(p_frame, text=p, variable=var, width=45, 
                                checkbox_width=16, checkbox_height=16, 
                                text_color="black", font=("Roboto", 11),
                                command=lambda p_name=p: on_prio_change(p_name))
            cb.pack(side="left", padx=5, pady=2)
            self.vars_priority[p] = var

        # ---------------- 3. SATIR: Atanan & Takım ----------------
        row3 = ctk.CTkFrame(self.filter_frame, fg_color="transparent")
        row3.pack(fill="x", padx=10, pady=5)

        # Atanan
        assignee_box = ctk.CTkFrame(row3, fg_color="white", corner_radius=6, border_width=1, border_color="#CCC")
        assignee_box.pack(side="left", fill="x", expand=True, padx=(0, 10))
        a_head = ctk.CTkFrame(assignee_box, fg_color="transparent")
        a_head.pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(a_head, text="Atanan Kişiler", font=("Roboto", 11, "bold"), text_color="gray").pack(side="left")
        self.selected_assignees = []
        self.assignee_container = ctk.CTkScrollableFrame(assignee_box, height=35, fg_color="transparent", orientation="horizontal")
        self.assignee_container.pack(fill="x", padx=5, pady=0)
        self.combo_assignee = ctk.CTkComboBox(a_head, values=["Yükleniyor..."], width=130, 
                                              command=lambda val: self.add_to_selection(val, self.assignee_container, self.selected_assignees))
        self.combo_assignee.pack(side="right")

        # Takım
        team_box = ctk.CTkFrame(row3, fg_color="white", corner_radius=6, border_width=1, border_color="#CCC")
        team_box.pack(side="left", fill="x", expand=True, padx=(0, 0))
        t_head = ctk.CTkFrame(team_box, fg_color="transparent")
        t_head.pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(t_head, text="Takımlar (Stajyerler)", font=("Roboto", 11, "bold"), text_color="gray").pack(side="left")
        self.selected_teams = []
        self.team_container = ctk.CTkScrollableFrame(team_box, height=35, fg_color="transparent", orientation="horizontal")
        self.team_container.pack(fill="x", padx=5, pady=0)
        self.combo_team = ctk.CTkComboBox(t_head, values=["Yükleniyor..."], width=130,
                                          command=lambda val: self.add_to_selection(val, self.team_container, self.selected_teams))
        self.combo_team.pack(side="right")

        # ---------------- 4. SATIR: Statü ve Tip ----------------
        row4 = ctk.CTkFrame(self.filter_frame, fg_color="transparent")
        row4.pack(fill="x", padx=10, pady=5)

        # Statü
        status_frame = ctk.CTkFrame(row4, fg_color="white", corner_radius=6, border_width=1, border_color="#CCC")
        status_frame.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=5)
        s_head = ctk.CTkFrame(status_frame, fg_color="transparent", height=20)
        s_head.pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(s_head, text="Statüler", font=("Roboto", 12, "bold"), text_color="gray").pack(side="left")
        ctk.CTkButton(s_head, text="Hepsini Seç", width=60, height=20, font=("Roboto", 10), fg_color="#DDD", text_color="black", hover_color="#CCC", command=lambda: self.toggle_all(self.vars_status, True)).pack(side="right")
        ctk.CTkButton(s_head, text="Temizle", width=50, height=20, font=("Roboto", 10), fg_color="#DDD", text_color="black", hover_color="#CCC", command=lambda: self.toggle_all(self.vars_status, False)).pack(side="right", padx=2)

        self.vars_status = {}
        statuses = ["Başlanmamış", "Devam", "Çözülmüş"]
        s_box_frame = ctk.CTkFrame(status_frame, fg_color="transparent")
        s_box_frame.pack(fill="x", padx=5)
        for s in statuses:
            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(s_box_frame, text=s, variable=var, width=60, checkbox_width=18, checkbox_height=18, text_color="black")
            cb.pack(side="left", padx=5)
            self.vars_status[s] = var

        # Tip
        type_frame = ctk.CTkFrame(row4, fg_color="white", corner_radius=6, border_width=1, border_color="#CCC")
        type_frame.pack(side="left", fill="x", expand=True, padx=(0, 0), ipady=5)
        t_head = ctk.CTkFrame(type_frame, fg_color="transparent", height=20)
        t_head.pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(t_head, text="Type", font=("Roboto", 12, "bold"), text_color="gray").pack(side="left")
        ctk.CTkButton(t_head, text="Hepsini Seç", width=60, height=20, font=("Roboto", 10), fg_color="#DDD", text_color="black", hover_color="#CCC", command=lambda: self.toggle_all(self.vars_type, True)).pack(side="right")
        ctk.CTkButton(t_head, text="Temizle", width=50, height=20, font=("Roboto", 10), fg_color="#DDD", text_color="black", hover_color="#CCC", command=lambda: self.toggle_all(self.vars_type, False)).pack(side="right", padx=2)
        self.vars_type = {}
        types = ["Araştırma", "Dokümantasyon", "Görev", "Sunum", "Faaliyet", "Sub-task"]
        t_box_frame = ctk.CTkFrame(type_frame, fg_color="transparent")
        t_box_frame.pack(fill="x", padx=5)
        for t in types:
            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(t_box_frame, text=t, variable=var, width=60, checkbox_width=18, checkbox_height=18, text_color="black")
            cb.pack(side="left", padx=5)
            self.vars_type[t] = var

        # ---------------- 5. SATIR: SADECE MANUEL GİRİŞ KUTUSU ----------------
        action_box = ctk.CTkFrame(self.filter_frame, fg_color="transparent")
        action_box.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(action_box, text="Manuel JQL (Boş bırakırsanız üstteki filtreler geçerli olur):", text_color="gray").pack(anchor="w")
        self.jql_entry = ctk.CTkEntry(action_box, height=35, font=("Consolas", 13), placeholder_text="Manuel sorgu girmek isterseniz buraya yazın...")
        self.jql_entry.pack(side="left", fill="x", expand=True)

    def get_jql_from_filters(self):
        """Arayüzdeki filtreleri okuyup JQL String'i döndürür."""
        parts = []
        
        proj = self.entry_project.get().strip()
        specific_key_input = self.entry_key.get().strip()
        
        # Eğer özel Key girilmişse
        if specific_key_input:
            if specific_key_input.isdigit() and proj:
                return f"key = {proj}-{specific_key_input}" 
            else:
                return f"key = {specific_key_input}"

        if proj: parts.append(f"project = {proj}")

        # Zaman
        time_map = {"Son 1 Saat": "-1h", "Son 6 Saat": "-6h", "Son 12 Saat": "-12h", "Son 24 Saat": "-24h", "Son 7 Gün": "-7d", "Son 15 Gün": "-15d", "Son 30 Gün": "-30d"}
        sel_time = self.combo_time.get()
        if sel_time in time_map: parts.append(f"created >= {time_map[sel_time]}")

        # Atanan
        if self.selected_assignees:
            assignee_str = ", ".join([f'"{u}"' for u in self.selected_assignees])
            parts.append(f"assignee in ({assignee_str})")

        # Takım
        if self.selected_teams:
            team_str = ", ".join([f'"{t}"' for t in self.selected_teams])
            parts.append(f'"İlgili Stajyerler" in ({team_str})')

        # Labels
        label = self.entry_label.get().strip()
        if label: parts.append(f'labels = "{label}"')

        # Öncelik
        sel_prio = [p for p, var in self.vars_priority.items() if var.get()]
        if sel_prio:
            prio_str = ", ".join([f'"{p}"' for p in sel_prio])
            parts.append(f"priority in ({prio_str})")

        # Statüler
        sel_stats = [s for s, var in self.vars_status.items() if var.get()]
        if sel_stats:
            status_str = ", ".join([f'"{s}"' for s in sel_stats])
            parts.append(f"status in ({status_str})")

        # Tipler
        sel_types = [t for t, var in self.vars_type.items() if var.get()]
        if sel_types:
            type_str = ", ".join([f'"{t}"' for t in sel_types])
            parts.append(f"issuetype in ({type_str})")

        return " AND ".join(parts)


    # --- AYARLAR FONKSİYONLARI ---
    def create_settings_tab(self):
        settings_tab = self.tab_settings
        
        # 1. Kaydet Butonu (Sabit En Üstte)
        btn_save = ctk.CTkButton(settings_tab, text="💾 TÜM AYARLARI KAYDET VE UYGULA", 
                                 fg_color="#27AE60", hover_color="#1E8449", height=40, font=("Roboto", 14, "bold"),
                                 command=self.save_settings)
        btn_save.pack(fill="x", padx=10, pady=10)

        # --- ANA SCROLLABLE FRAME ---
        self.main_scroll = ctk.CTkScrollableFrame(settings_tab, fg_color="transparent")
        self.main_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # --- A) GLOBAL AYARLAR (.env) ---
        self.global_frame = ctk.CTkFrame(self.main_scroll)
        self.global_frame.pack(fill="x", padx=5, pady=10)
        
        ctk.CTkLabel(self.global_frame, text="1. Global API & Proje Ayarları (.env)", font=("Roboto", 14, "bold")).pack(anchor="w", padx=10, pady=5)

        self.api_entries = {}
        fields = [
            ("GITLAB_TOKEN", "GitLab Token", True), ("MASTER_PROJECT_ID", "Master Project ID", False),
            ("GROUP_ID", "Group ID (Milestone)", False), ("JIRA_URL", "Jira URL", False), ("JIRA_API_TOKEN", "Jira API Token", True)
        ]
        
        grid_api = ctk.CTkFrame(self.global_frame, fg_color="transparent")
        grid_api.pack(fill="x", padx=10, pady=5)
        grid_api.columnconfigure(1, weight=1)

        for i, (key, label, is_secret) in enumerate(fields):
            ctk.CTkLabel(grid_api, text=f"{label}:", anchor="w").grid(row=i, column=0, padx=5, pady=2, sticky="w")
            entry = ctk.CTkEntry(grid_api, show="*" if is_secret else None)
            entry.grid(row=i, column=1, padx=5, pady=2, sticky="ew")
            self.api_entries[key] = entry

        # --- B) MAPPING TABLOLARI ---
        self.team_frame = ctk.CTkFrame(self.main_scroll)
        self.team_frame.pack(fill="x", padx=5, pady=10)
        
        # Takım Başlık ve Ekle Butonu
        t_header_box = ctk.CTkFrame(self.team_frame, fg_color="transparent")
        t_header_box.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(t_header_box, text="2. Takım & Kullanıcı Eşleşmeleri", font=("Roboto", 14, "bold"), text_color="#E67E22").pack(side="left")
        ctk.CTkButton(t_header_box, text="+ Takım Ekle", width=90, height=25, command=lambda: self.add_team_row({})).pack(side="right", padx=2)
        ctk.CTkButton(t_header_box, text="+ Kullanıcı Ekle", width=90, height=25, command=lambda: self.add_user_row({})).pack(side="right", padx=2)

        # Takım Tablosu
        t_head = ctk.CTkFrame(self.team_frame, fg_color="gray", height=30)
        t_head.pack(fill="x", padx=5)
        for i, t in enumerate(["Jira Takım", "GitLab PID", "İsim", "Sil"]):
            t_head.columnconfigure(i, weight=1 if i==3 else 3)
            ctk.CTkLabel(t_head, text=t, font=("Roboto", 12, "bold"), text_color="white").grid(row=0, column=i, sticky="ew")

        self.team_scroll_container = ctk.CTkScrollableFrame(self.team_frame, height=50, fg_color="transparent") 
        self.team_scroll_container.pack(fill="x", padx=5, pady=(0,5))
        self.team_entries = []

        

        # Kullanıcı Tablosu
        u_head = ctk.CTkFrame(self.team_frame, fg_color="gray", height=30)
        u_head.pack(fill="x", padx=5, pady=(10,0))
        for i, t in enumerate(["Jira User", "GitLab UID", "Sil"]):
            u_head.columnconfigure(i, weight=1 if i==2 else 3)
            ctk.CTkLabel(u_head, text=t, font=("Roboto", 12, "bold"), text_color="white").grid(row=0, column=i, sticky="ew")

        self.user_scroll_container = ctk.CTkScrollableFrame(self.team_frame, height=120, fg_color="transparent") 
        self.user_scroll_container.pack(fill="x", padx=5, pady=(0, 5))
        self.user_entries = []

        # --- C) ŞABLON YÖNETİMİ (YENİ EKLENEN KISIM) ---
        self.create_template_settings_ui(self.main_scroll)

        # Yükle
        self.load_global_settings()
        self.load_mapping_settings()

    def create_template_settings_ui(self, parent_frame):
        """Ayarlar sekmesine Şablon Yönetimi bölümü ekler."""
        self.template_frame_container = ctk.CTkFrame(parent_frame, fg_color="#F0F0F0")
        self.template_frame_container.pack(fill="x", padx=5, pady=15)

        # Başlık
        header = ctk.CTkFrame(self.template_frame_container, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(header, text="3. Şablon Yönetimi (Markdown)", font=("Roboto", 14, "bold"), text_color="#8E44AD").pack(side="left")

        # Alt Bölge: Liste ve Editör
        editor_area = ctk.CTkFrame(self.template_frame_container, fg_color="transparent")
        editor_area.pack(fill="x", padx=5, pady=5)

        # SOL: Liste
        left_list = ctk.CTkFrame(editor_area, width=200)
        left_list.pack(side="left", fill="y", padx=(0, 5))
        
        ctk.CTkLabel(left_list, text="Mevcut Şablonlar", font=("Roboto", 12, "bold")).pack(pady=5)
        self.template_list_scroll = ctk.CTkScrollableFrame(left_list, width=220, height=250)
        self.template_list_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        
        # SAĞ: Editör
        right_editor = ctk.CTkFrame(editor_area)
        right_editor.pack(side="left", fill="both", expand=True)

        # Dosya Adı ve Butonlar
        toolbar = ctk.CTkFrame(right_editor, fg_color="transparent")
        toolbar.pack(fill="x", padx=5, pady=5)

        ctk.CTkLabel(toolbar, text="Dosya Adı:").pack(side="left", padx=5)
        self.entry_template_name = ctk.CTkEntry(toolbar, width=200)
        self.entry_template_name.pack(side="left", padx=5)
        
        # Butonlar
        ctk.CTkButton(toolbar, text="Yeni", width=60, fg_color="#F39C12", command=self.new_template).pack(side="left", padx=5)
        ctk.CTkButton(toolbar, text="Kaydet", width=60, fg_color="#27AE60", command=self.save_template).pack(side="left", padx=5)
        ctk.CTkButton(toolbar, text="Sil", width=60, fg_color="#C0392B", command=self.delete_template).pack(side="right", padx=5)

        # Text Alanı
        self.txt_template_content = ctk.CTkTextbox(right_editor, font=("Consolas", 12), height=200)
        self.txt_template_content.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Durum Çubuğu
        self.lbl_template_status = ctk.CTkLabel(right_editor, text="Hazır.", text_color="gray", font=("Roboto", 10))
        self.lbl_template_status.pack(anchor="w", padx=10, pady=(0, 5))

        # Listeyi ilk kez doldur
        self.refresh_template_list_ui()

    # --- ŞABLON FONKSİYONLARI ---
    def refresh_template_list_ui(self):
        # Önce temizle
        for widget in self.template_list_scroll.winfo_children():
            widget.destroy()
        
        templates = self.get_template_list()
        for tmpl in templates:
            btn = ctk.CTkButton(self.template_list_scroll, text=tmpl, fg_color="transparent", 
                                text_color="black", hover_color="#DDD", anchor="w",
                                command=lambda t=tmpl: self.load_template_content(t))
            btn.pack(fill="x", pady=2)

    def load_template_content(self, filename):
        path = os.path.join(self.templates_folder, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.entry_template_name.delete(0, "end")
            self.entry_template_name.insert(0, filename)
            self.txt_template_content.delete("0.0", "end")
            self.txt_template_content.insert("0.0", content)
            self.lbl_template_status.configure(text=f"Yüklendi: {filename}", text_color="green")

    def new_template(self):
        self.entry_template_name.delete(0, "end")
        self.txt_template_content.delete("0.0", "end")
        self.entry_template_name.insert(0, "yeni_sablon.md")
        self.lbl_template_status.configure(text="Yeni şablon oluşturuluyor...", text_color="blue")

    def save_template(self):
        filename = self.entry_template_name.get().strip()
        if not filename:
            self.lbl_template_status.configure(text="Hata: Dosya adı boş olamaz.", text_color="red")
            return
        
        if not filename.endswith(".md"):
            filename += ".md"

        content = self.txt_template_content.get("0.0", "end-1c") # Sondaki newline'ı alma
        path = os.path.join(self.templates_folder, filename)
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.lbl_template_status.configure(text=f"Kaydedildi: {filename}", text_color="green")
            self.refresh_template_list_ui()
        except Exception as e:
            self.lbl_template_status.configure(text=f"Hata: {str(e)}", text_color="red")

    def delete_template(self):
        filename = self.entry_template_name.get().strip()
        if not filename: return
        
        path = os.path.join(self.templates_folder, filename)
        if os.path.exists(path):
            try:
                os.remove(path)
                self.new_template() # Ekranı temizle
                self.refresh_template_list_ui()
                self.lbl_template_status.configure(text=f"Silindi: {filename}", text_color="#C0392B")
            except Exception as e:
                self.lbl_template_status.configure(text=f"Silme Hatası: {str(e)}", text_color="red")

    # --- AYARLARI YÜKLEME ---
    def load_global_settings(self):
        load_dotenv() 
        for key, entry in self.api_entries.items():
            entry.delete(0, "end")
            entry.insert(0, os.getenv(key, ""))

    def load_mapping_settings(self):
        for frame, _ in self.team_entries: frame.destroy()
        for frame, _ in self.user_entries: frame.destroy()
        self.team_entries = []
        self.user_entries = []

        try:
            with open("config.json", "r", encoding="utf-8") as f:
                data = json.load(f)
        except: data = {}

        for item in data.get("team_mappings", []):
            self.add_team_row(item)
        
        for item in data.get("user_mappings", []):
            self.add_user_row(item)

    # --- SATIR EKLEME METOTLARI ---
    def add_team_row(self, data):
        row = ctk.CTkFrame(self.team_scroll_container, fg_color="transparent")
        row.pack(fill="x", pady=2)
        for i in range(4): row.columnconfigure(i, weight=1 if i==3 else 3)
        
        entries = {}
        keys = ["jira_team_name", "gitlab_project_id", "friendly_name"]
        
        for i, k in enumerate(keys):
            e = ctk.CTkEntry(row, text_color="black")
            e.insert(0, str(data.get(k, "")))
            e.grid(row=0, column=i, sticky="ew", padx=2)
            entries[k] = e
            
        btn_del = ctk.CTkButton(row, text="X", width=30, fg_color="#C0392B", command=lambda: self.remove_row(row, self.team_entries))
        btn_del.grid(row=0, column=3, padx=2)
        
        self.team_entries.append((row, entries))

    def add_user_row(self, data):
        row = ctk.CTkFrame(self.user_scroll_container, fg_color="transparent")
        row.pack(fill="x", pady=2)
        for i in range(3): row.columnconfigure(i, weight=1 if i==2 else 3)
        
        entries = {}
        keys = ["jira_user", "gitlab_user_id"]
        
        for i, k in enumerate(keys):
            e = ctk.CTkEntry(row, text_color="black")
            e.insert(0, str(data.get(k, "")))
            e.grid(row=0, column=i, sticky="ew", padx=2)
            entries[k] = e
            
        btn_del = ctk.CTkButton(row, text="X", width=30, fg_color="#C0392B", command=lambda: self.remove_row(row, self.user_entries))
        btn_del.grid(row=0, column=2, padx=2)
        
        self.user_entries.append((row, entries))

    def remove_row(self, row_frame, list_ref):
        row_frame.destroy()
        # listeden silme işlemi tam doğru çalışması için liste indekslemesi yerine
        # görsel öğe silinince logic'ten de silinir.
        
    # --- KAYDETME ---
    def save_settings(self):
        env_lines = [f"{k}={e.get()}" for k, e in self.api_entries.items()]
        try:
            with open(".env", "w") as f: f.write("\n".join(env_lines))
            self.log_yaz(self.console_left, "✅ Global Ayarlar (.env) kaydedildi.\n", "success")
        except Exception as e:
            self.log_yaz(self.console_left, f"❌ .env Hatası: {e}\n", "error")

        try:
            with open("config.json", "r", encoding="utf-8") as f: 
                settings = json.load(f).get("settings", {})
        except: 
            settings = {"default_jql": "project = GYT AND created >= -15d"}

        new_teams = []
        for row, ent in self.team_entries:
            if row.winfo_exists() and ent["jira_team_name"].get().strip():
                try:
                    new_teams.append({
                        "jira_team_name": ent["jira_team_name"].get(),
                        "gitlab_project_id": int(ent["gitlab_project_id"].get() or 0),
                        "friendly_name": ent["friendly_name"].get()
                    })
                except ValueError:
                    self.log_yaz(self.console_left, "❌ HATA: Proje ID sayı olmalı.\n", "error"); return

        new_users = []
        for row, ent in self.user_entries:
            if row.winfo_exists() and ent["jira_user"].get().strip():
                try:
                    new_users.append({
                        "jira_user": ent["jira_user"].get(),
                        "gitlab_user_id": int(ent["gitlab_user_id"].get() or 0)
                    })
                except ValueError:
                    self.log_yaz(self.console_left, "❌ HATA: User ID sayı olmalı.\n", "error"); return

        final_data = {
            "team_mappings": new_teams,
            "user_mappings": new_users,
            "settings": settings
        }
        
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(final_data, f, indent=2, ensure_ascii=False)
            self.log_yaz(self.console_left, "✅ Config Ayarları (config.json) kaydedildi.\n", "success")
            
            self.refresh_dropdown_data()
            
        except Exception as e:
            self.log_yaz(self.console_left, f"❌ config.json Hatası: {e}\n", "error")
            
        self.log_yaz(self.console_left, "🔄 Değişiklikler için uygulamayı yeniden başlatın (Görsel öğeler için).\n", "warning")

    def setup_tags(self, textbox):
        textbox._textbox.tag_config("error", foreground="#FF5555")
        textbox._textbox.tag_config("success", foreground="#50FA7B")
        textbox._textbox.tag_config("warning", foreground="#FFB86C")
        textbox._textbox.tag_config("info", foreground="#8BE9FD")
        textbox._textbox.tag_config("dim", foreground="#8FA0D4")

    # --- AKSİYONLAR ---
    def goster_onay_iptal(self):
        self.action_frame.pack(fill="x", padx=15, pady=10)
        
        # Temizle
        self.progress_bar.pack_forget()
        self.progress_label.pack_forget()
        self.btn_reset.pack_forget()
        
        for widget in self.action_frame.winfo_children():
            if isinstance(widget, ctk.CTkFrame) and getattr(widget, "is_template_frame", False):
                widget.destroy()

        self.template_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.template_frame.is_template_frame = True 
        self.template_frame.pack(fill="x", pady=(0, 10))

        lbl = ctk.CTkLabel(self.template_frame, text="Kullanılacak Şablon:", font=("Roboto", 12, "bold"))
        lbl.pack(side="left", padx=(0, 10))

        # Şablon listesini her seferinde diskten oku
        templates = self.get_template_list()
        self.combo_templates = ctk.CTkComboBox(self.template_frame, values=templates, width=250)
        self.combo_templates.pack(side="left")
        if "standard_template.md" in templates:
            self.combo_templates.set("standard_template.md")
        elif templates:
             self.combo_templates.set(templates[0])

        self.btn_confirm_left.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.btn_cancel_left.pack(side="right", padx=(5, 0))
        
    def goster_progress_bar(self):
        self.btn_confirm_left.pack_forget()
        self.btn_cancel_left.pack_forget()
        self.progress_label.pack(pady=(0, 5))
        self.progress_bar.pack(fill="x", pady=(0, 10))
        self.progress_bar.set(0)
        self.progress_label.configure(text="Başlatılıyor...")

    def goster_reset_butonu(self):
        self.action_frame.pack(fill="x", padx=15, pady=10)
        self.btn_confirm_left.pack_forget()
        self.btn_cancel_left.pack_forget()
        self.progress_bar.pack_forget()
        self.progress_label.pack_forget()
        self.btn_reset.pack(fill="x", pady=0)

    def ekrani_sifirla(self):
        self.islem_iptal_et(silent=True)
        self.console_left.delete("0.0", "end")
        self.log_yaz(self.console_left, "✨ Ekran temizlendi. Yeni işlem için hazır.\n", "info")
        self.action_frame.pack_forget()
        self.btn_left.configure(state="normal")
        self.jql_entry.configure(state="normal")

    def islem_iptal_et(self, silent=False):
        to_add_file = os.path.join(self.csv_folder_path, "jira_to_add.csv")
        try:
            if os.path.exists(to_add_file):
                os.remove(to_add_file)
                if not silent: print("🧹 Geçici dosya silindi.")
        except Exception: pass
        if not silent:
            self.console_left.delete("0.0", "end")
            self.log_yaz(self.console_left, "🚫 İşlem iptal edildi.\n", "warning")
            self.action_frame.pack_forget()
            self.btn_left.configure(state="normal", text="AKTARIMI BAŞLAT (ÖN İZLEME)")

    # --- THREAD İŞLEMLERİ (SOL TARAF) ---
    def baslat_sol_thread_preview(self):
        # --- KARAR MEKANİZMASI ---
        manual_input = self.jql_entry.get().strip()
        
        if manual_input:
            jql = manual_input
            self.log_yaz(self.console_left, "ℹ️ Manuel JQL Kullanılıyor.\n", "info")
        else:
            jql = self.get_jql_from_filters()
            self.log_yaz(self.console_left, "ℹ️ Filtrelerden Oluşturulan JQL Kullanılıyor.\n", "info")
        # -------------------------

        if not jql.strip():
            self.log_yaz(self.console_left, "⚠️ HATA: JQL boş olamaz! Lütfen filtre seçin veya manuel giriş yapın.\n", "error")
            return
        
        self.console_left.delete("0.0", "end")
        self.btn_left.configure(state="disabled", text="⏳ VERİ ÇEKİLİYOR...")
        self.action_frame.pack_forget()

        t = threading.Thread(
            target=self.scripti_calistir, 
            args=("sync_to_gitlab.py", self.console_left, self.btn_left, "AKTARIMI BAŞLAT (ÖN İZLEME)", jql, "--preview", self.on_preview_complete)
        )
        t.start()

    def basit_sol_thread_execute(self):
        # --- KARAR MEKANİZMASI ---
        manual_input = self.jql_entry.get().strip()
        if manual_input:
            jql = manual_input
        else:
            jql = self.get_jql_from_filters()
        # -------------------------
        
        selected_template = "standard_template.md"
        if hasattr(self, 'combo_templates'):
            selected_template = self.combo_templates.get()

        self.btn_left.configure(state="disabled")
        self.jql_entry.configure(state="disabled")
        
        if hasattr(self, 'template_frame'):
            self.template_frame.pack_forget()

        self.goster_progress_bar()

        # sync_to_gitlab.py artık 3. argüman olarak template adını bekliyor (extra_arg)
        t = threading.Thread(
            target=self.scripti_calistir, 
            args=("sync_to_gitlab.py", self.console_left, None, "", jql, "--execute", self.on_execute_complete, selected_template)
        )
        t.start()
      
    def on_preview_complete(self, return_code, output_text):
        if return_code != 0:
            self.btn_left.configure(state="normal")
            self.action_frame.pack_forget()
            return

        is_empty = ("Aktarılacak toplam 0 issue tespit edildi" in output_text or 
                    "Aktarılacak yeni kayıt bulunamadı" in output_text or 
                    "Tüm issue'lar zaten güncel" in output_text)

        if is_empty:
            self.log_yaz(self.console_left, "\nℹ️ Aktarılacak yeni kayıt bulunamadı.\n", "warning")
            self.goster_reset_butonu()
            self.btn_left.configure(state="disabled")
        elif "Gitlab'e aktarılacak toplam" in output_text:
            self.goster_onay_iptal()
            self.btn_left.configure(state="normal")

    def on_execute_complete(self, return_code, output_text):
        self.goster_reset_butonu()
        if return_code == 0:
             self.log_yaz(self.console_left, "\n✅ Tüm aktarım tamamlandı.\n", "success")
             self.progress_label.configure(text="Tamamlandı: 100%")
             self.progress_bar.set(1)

    def baslat_sag_thread(self):
        self.btn_right.configure(state="disabled", text="⏳ GİTLAB BAĞLANIYOR...")
        self.console_right.delete("0.0", "end")
        t = threading.Thread(target=self.scripti_calistir, args=("sync_gitlab_status_to_jira.py", self.console_right, self.btn_right, "STATÜLERİ GÜNCELLE"))
        t.start()

    def scripti_calistir(self, script_name, target_console, target_btn, btn_reset_text, arguman=None, mode_flag=None, callback=None, extra_arg=None):
        full_output = ""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(current_dir, script_name)
            python_exe = sys.executable

            self.log_yaz(target_console, f"📂 Script: {script_name}\n", "dim")
            if arguman: self.log_yaz(target_console, f"📡 JQL: {arguman}\n", "info")
            if extra_arg: self.log_yaz(target_console, f"🎨 Şablon: {extra_arg}\n", "dim")

            cmd = [python_exe, "-u", script_path]
            if arguman: cmd.append(arguman)
            if mode_flag: cmd.append(mode_flag)
            if extra_arg: cmd.append(extra_arg)

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, cwd=current_dir, encoding='utf-8', errors='replace', env=env)
            progress_pattern = re.compile(r"--- (\d+)/(\d+):")

            for line in process.stdout: 
                self.akilli_log_yaz(target_console, line)
                full_output += line
                if mode_flag == "--execute":
                    match = progress_pattern.search(line)
                    if match:
                        current, total = int(match.group(1)), int(match.group(2))
                        if total > 0:
                            percent = current / total
                            self.progress_bar.set(percent)
                            self.progress_label.configure(text=f"İşleniyor: {current}/{total} (%{int(percent*100)})")

            for line in process.stderr: self.log_yaz(target_console, f"⚠️ {line}", "warning")
            process.wait()
            
            if mode_flag != "--execute" and target_btn: self.btn_left.configure(state="normal")
            if callback: self.after(100, lambda: callback(process.returncode, full_output))

        except Exception as e: 
            self.log_yaz(target_console, f"\n❌ Kritik Hata: {e}\n", "error")
            if target_btn: target_btn.configure(state="normal")
        finally: 
            if target_btn and mode_flag != "--execute": target_btn.configure(state="normal", text=btn_reset_text)

    def akilli_log_yaz(self, console, line):
        tag = "normal"
        if "❌" in line or "Hata" in line: tag = "error"
        elif "⚠️" in line: tag = "warning"
        elif "✅" in line or "Başarılı" in line: tag = "success"
        elif "➡️" in line: tag = "info"
        elif "---" in line: tag = "dim"
        self.log_yaz(console, line, tag)

    def log_yaz(self, console, mesaj, tag=None):
        console.configure(state="normal")
        if tag: console.insert("end", mesaj, tag)
        else: console.insert("end", mesaj)
        console.see("end")

if __name__ == "__main__":
    app = DualSyncApp()
    app.mainloop()
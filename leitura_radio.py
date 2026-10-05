#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor Automático AirOS/MikroTik - v5.0 (Alta Velocidade com Garantia de Coleta)
Coleta equipamentos AirOS (Ubiquiti) via Web e MikroTik via SSH
"""

import ipaddress
import socket
import time
import re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime
import pandas as pd
import threading
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from openpyxl.styles import PatternFill
import queue
import paramiko
from paramiko.ssh_exception import AuthenticationException, SSHException
from dataclasses import dataclass, asdict

# Configurações padrão
DEFAULT_USUARIO = "user"
DEFAULT_SENHA = "senha"
DEFAULT_PORTA_AIROS = "porta ubnt"
DEFAULT_PORTA_SSH_MIKROTIK = "porta ssh mikrotik"

# Configurações de tentativas
MAX_RETRIES = 3  # Número máximo de tentativas
RETRY_DELAY = 2  # Delay entre tentativas em segundos

def extract_colon(text: str, key: str) -> str:
    """
    Extrai valor no formato 'chave: valor' com tolerância a variações.
    Aceita maiúsculas/minúsculas, espaços extras e traduções comuns.
    """
    # Normaliza texto para evitar problemas de acentuação/maiúsculas
    normalized_text = text.lower()
    normalized_key = key.lower()

    # Regex flexível: aceita ':' ou '=' e ignora espaços extras
    pattern = rf"{re.escape(normalized_key)}\s*[:=]\s*([^\n\r]+)"
    match = re.search(pattern, normalized_text, re.IGNORECASE)
    return match.group(1).strip() if match else "N/A"


def extract_equals(text: str, key: str) -> str:
    """
    Extrai valor no formato 'chave=valor' com tolerância a aspas e espaços.
    """
    normalized_text = text.lower()
    normalized_key = key.lower()

    # Regex flexível: aceita aspas simples/dobras e ignora espaços
    pattern = rf'{re.escape(normalized_key)}\s*=\s*["\']?([^"\'\s]+)["\']?'
    match = re.search(pattern, normalized_text, re.IGNORECASE)
    return match.group(1).strip() if match else "N/A"

@dataclass
class DeviceInfo:
    """Estrutura para dados do dispositivo"""
    ip: str
    hostname: str = "N/A"
    equipment: str = "N/A"
    mode: str = "N/A"
    signal: str = "N/A"
    lan: str = "N/A"
    success: bool = False
    message: str = ""
    device_type: str = "unknown"
    ssid: str = "N/A"
    frequency: str = "N/A"
    channel_width: str = "N/A"
    
    def to_dict(self) -> dict:
        return asdict(self)

class ColetorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Coletor Automático AirOS/MikroTik - v5.0 (Garantia de Coleta)")
        self.root.geometry("950x750")
        self.root.resizable(True, True)
        
        # Configurar estilo
        self.setup_style()
        
        # Variáveis de controle
        self.running = False
        self.pause = False
        self.coletando = False
        
        # Arquivo de saída
        self.arquivo_saida = None
        
        # Fila para resultados
        self.result_queue = queue.Queue()
        
        # Setup UI
        self.setup_ui()
        
        # Centralizar janela
        self.center_window()
        
        # Iniciar processamento da fila
        self.process_queue()
    
    def center_window(self):
        """Centraliza a janela na tela"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
    
    def setup_style(self):
        """Configura o estilo da interface"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Cores
        self.bg_color = "#2b2b2b"
        self.fg_color = "#ffffff"
        self.accent_color = "#007acc"
        self.success_color = "#4ec9b0"
        self.error_color = "#f48771"
        self.warning_color = "#ce9178"
        self.mikrotik_color = "#dcdcaa"
        
        # Configurar estilo
        style.configure("TFrame", background=self.bg_color)
        style.configure("TLabel", background=self.bg_color, foreground=self.fg_color)
        style.configure("TLabelframe", background=self.bg_color, foreground=self.fg_color)
        style.configure("TLabelframe.Label", background=self.bg_color, foreground=self.fg_color)
        style.configure("Accent.TButton", background=self.accent_color, foreground="white")
    
    def setup_ui(self):
        """Configura a interface completa"""
        # Container principal
        main_container = ttk.Frame(self.root, padding="10")
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # ========== CABEÇALHO ==========
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(header_frame, text="Coletor Automático AirOS/MikroTik - Alta Velocidade", 
                 font=("Segoe UI", 16, "bold")).pack()
        ttk.Label(header_frame, text="Coleta paralela com múltiplas threads | AirOS (Web) | MikroTik (SSH) | Timeouts estendidos",
                 font=("Segoe UI", 9)).pack()
        
        # ========== PAINEL DE CONFIGURAÇÃO ==========
        config_panel = ttk.LabelFrame(main_container, text="Configuração da Rede", padding="10")
        config_panel.pack(fill=tk.X, pady=(0, 10))
        
        # Primeira linha: IPs
        row1 = ttk.Frame(config_panel)
        row1.pack(fill=tk.X, pady=5)
        
        ttk.Label(row1, text="IP Inicial:", width=12).pack(side=tk.LEFT)
        self.ip_inicio_entry = ttk.Entry(row1, width=20, font=("Consolas", 10))
        self.ip_inicio_entry.pack(side=tk.LEFT, padx=5)
        self.ip_inicio_entry.insert(0, "")
        
        ttk.Label(row1, text="IP Final:", width=12).pack(side=tk.LEFT, padx=(20,0))
        self.ip_fim_entry = ttk.Entry(row1, width=20, font=("Consolas", 10))
        self.ip_fim_entry.pack(side=tk.LEFT, padx=5)
        self.ip_fim_entry.insert(0, "")
        
        # Segunda linha: Credenciais AirOS
        row2 = ttk.Frame(config_panel)
        row2.pack(fill=tk.X, pady=5)
        
        ttk.Label(row2, text="Usuário AirOS:", width=12).pack(side=tk.LEFT)
        self.usuario_entry = ttk.Entry(row2, width=20)
        self.usuario_entry.pack(side=tk.LEFT, padx=5)
        self.usuario_entry.insert(0, DEFAULT_USUARIO)
        
        ttk.Label(row2, text="Senha AirOS:", width=12).pack(side=tk.LEFT, padx=(20,0))
        self.senha_entry = ttk.Entry(row2, width=20, show="*")
        self.senha_entry.pack(side=tk.LEFT, padx=5)
        self.senha_entry.insert(0, DEFAULT_SENHA)
        
        ttk.Label(row2, text="Porta AirOS:", width=12).pack(side=tk.LEFT, padx=(20,0))
        self.porta_entry = ttk.Entry(row2, width=10)
        self.porta_entry.pack(side=tk.LEFT, padx=5)
        self.porta_entry.insert(0, DEFAULT_PORTA_AIROS)
        
        # Terceira linha: Credenciais MikroTik SSH
        row3 = ttk.Frame(config_panel)
        row3.pack(fill=tk.X, pady=5)
        
        ttk.Label(row3, text="Usuário MikroTik:", width=12).pack(side=tk.LEFT)
        self.usuario_mikrotik_entry = ttk.Entry(row3, width=20)
        self.usuario_mikrotik_entry.pack(side=tk.LEFT, padx=5)
        self.usuario_mikrotik_entry.insert(0, DEFAULT_USUARIO)
        
        ttk.Label(row3, text="Senha MikroTik:", width=12).pack(side=tk.LEFT, padx=(20,0))
        self.senha_mikrotik_entry = ttk.Entry(row3, width=20, show="*")
        self.senha_mikrotik_entry.pack(side=tk.LEFT, padx=5)
        self.senha_mikrotik_entry.insert(0, DEFAULT_SENHA)
        
        ttk.Label(row3, text="Porta SSH:", width=12).pack(side=tk.LEFT, padx=(20,0))
        self.porta_ssh_entry = ttk.Entry(row3, width=10)
        self.porta_ssh_entry.pack(side=tk.LEFT, padx=5)
        self.porta_ssh_entry.insert(0, DEFAULT_PORTA_SSH_MIKROTIK)
        
        # Quarta linha: Performance
        row4 = ttk.Frame(config_panel)
        row4.pack(fill=tk.X, pady=5)
        
        ttk.Label(row4, text="Threads Simultâneas:", width=15).pack(side=tk.LEFT)
        self.threads_spin = ttk.Spinbox(row4, from_=1, to=30, width=10)
        self.threads_spin.pack(side=tk.LEFT, padx=5)
        self.threads_spin.set(10)
        
        ttk.Label(row4, text="Timeout (s):", width=12).pack(side=tk.LEFT, padx=(20,0))
        self.timeout_spin = ttk.Spinbox(row4, from_=10, to=60, width=10)
        self.timeout_spin.pack(side=tk.LEFT, padx=5)
        self.timeout_spin.set(20)
        
        ttk.Label(row4, text="Delay entre IPs (ms):", width=15).pack(side=tk.LEFT, padx=(20,0))
        self.delay_spin = ttk.Spinbox(row4, from_=100, to=2000, width=10)
        self.delay_spin.pack(side=tk.LEFT, padx=5)
        self.delay_spin.set(500)
        
        ttk.Label(row4, text="Tentativas por IP:", width=15).pack(side=tk.LEFT, padx=(20,0))
        self.retries_spin = ttk.Spinbox(row4, from_=1, to=5, width=10)
        self.retries_spin.pack(side=tk.LEFT, padx=5)
        self.retries_spin.set(3)
        
        # ========== PAINEL DE ARQUIVO ==========
        file_panel = ttk.LabelFrame(main_container, text="Arquivo de Saída", padding="10")
        file_panel.pack(fill=tk.X, pady=(0, 10))
        
        file_row = ttk.Frame(file_panel)
        file_row.pack(fill=tk.X)
        
        self.file_path_var = tk.StringVar(value="Nenhum arquivo selecionado")
        ttk.Label(file_row, textvariable=self.file_path_var, foreground="#888888").pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Button(file_row, text="📁 Selecionar Arquivo", command=self.selecionar_arquivo).pack(side=tk.RIGHT, padx=5)
        
        # ========== PAINEL DE CONTROLE ==========
        control_panel = ttk.Frame(main_container)
        control_panel.pack(fill=tk.X, pady=(0, 10))
        
        button_frame = ttk.Frame(control_panel)
        button_frame.pack()
        
        self.btn_iniciar = ttk.Button(button_frame, text="▶ Iniciar Coleta", command=self.iniciar_coleta,
                                      style="Accent.TButton", width=18)
        self.btn_iniciar.pack(side=tk.LEFT, padx=5)
        
        self.btn_pausar = ttk.Button(button_frame, text="⏸ Pausar", command=self.pausar_coleta,
                                     state="disabled", width=12)
        self.btn_pausar.pack(side=tk.LEFT, padx=5)
        
        self.btn_parar = ttk.Button(button_frame, text="⏹ Parar", command=self.parar_coleta,
                                    state="disabled", width=12)
        self.btn_parar.pack(side=tk.LEFT, padx=5)
        
        # ========== PAINEL DE ESTATÍSTICAS ==========
        stats_panel = ttk.LabelFrame(main_container, text="Estatísticas em Tempo Real", padding="10")
        stats_panel.pack(fill=tk.X, pady=(0, 10))
        
        stats_frame = ttk.Frame(stats_panel)
        stats_frame.pack()
        
        # Cards de estatísticas
        self.stats_vars = {}
        stats_config = [
            ("total", "📊 Total", "#007acc"),
            ("success", "✅ Sucesso", "#4ec9b0"),
            ("failed", "❌ Falhas", "#f48771"),
            ("active", "⚡ Ativas", "#ce9178"),
            ("airos", "📡 AirOS", "#9cdcfe"),
            ("mikrotik", "🔷 MikroTik", "#dcdcaa")
        ]
        
        for i, (key, label, color) in enumerate(stats_config):
            card = ttk.Frame(stats_frame, relief="ridge", borderwidth=1)
            card.pack(side=tk.LEFT, padx=8, pady=5, fill=tk.BOTH, expand=True)
            
            ttk.Label(card, text=label, font=("Segoe UI", 9)).pack(pady=(5,0))
            self.stats_vars[key] = tk.StringVar(value="0")
            ttk.Label(card, textvariable=self.stats_vars[key], font=("Segoe UI", 18, "bold"),
                     foreground=color).pack(pady=(0,5))
        
        # ========== BARRA DE PROGRESSO ==========
        progress_panel = ttk.Frame(main_container)
        progress_panel.pack(fill=tk.X, pady=(0, 10))
        
        self.progress_var = tk.StringVar(value="0%")
        self.progress_bar = ttk.Progressbar(progress_panel, mode="determinate")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        ttk.Label(progress_panel, textvariable=self.progress_var, width=8).pack(side=tk.RIGHT)
        
        # Indicador de velocidade
        self.speed_var = tk.StringVar(value="0 IPs/min")
        ttk.Label(progress_panel, textvariable=self.speed_var, foreground="#4ec9b0").pack(side=tk.RIGHT, padx=10)
        
        # ========== LOG ==========
        log_panel = ttk.LabelFrame(main_container, text="Log de Execução", padding="10")
        log_panel.pack(fill=tk.BOTH, expand=True)
        
        log_control = ttk.Frame(log_panel)
        log_control.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(log_control, text="🗑️ Limpar Log", command=self.limpar_log, width=12).pack(side=tk.RIGHT)
        ttk.Button(log_control, text="💾 Salvar Log", command=self.salvar_log, width=12).pack(side=tk.RIGHT, padx=5)
        
        # Área de log
        log_text_frame = ttk.Frame(log_panel)
        log_text_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_text_frame, wrap=tk.WORD, height=12,
                                font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(log_text_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # Configurar tags
        self.log_text.tag_config("success", foreground="#4ec9b0")
        self.log_text.tag_config("error", foreground="#f48771")
        self.log_text.tag_config("warning", foreground="#ce9178")
        self.log_text.tag_config("info", foreground="#9cdcfe")
        self.log_text.tag_config("mikrotik", foreground="#dcdcaa")
        
        # Status bar
        self.status_var = tk.StringVar(value="Pronto para iniciar coleta")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def selecionar_arquivo(self):
        """Abre diálogo para selecionar local e nome do arquivo Excel"""
        arquivo = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            title="Salvar coleta como"
        )
        if arquivo:
            self.arquivo_saida = arquivo
            self.file_path_var.set(os.path.basename(arquivo))
            self.log(f"📁 Arquivo de saída definido: {arquivo}", "success")
    
    def log(self, mensagem, nivel="info"):
        """Enfileira mensagem de log para processamento na thread principal."""
        self.result_queue.put({"type": "log", "text": mensagem, "level": nivel})

    def _append_log(self, mensagem, nivel="info"):
        """Insere mensagem diretamente no widget de log na thread principal."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        icones = {"success": "✅", "error": "❌", "warning": "⚠️", "info": "ℹ️", "mikrotik": "🔷"}
        icon = icones.get(nivel, "📝")

        formatted_msg = f"[{timestamp}] {icon} {mensagem}\n"
        self.log_text.insert(tk.END, formatted_msg)
        tag = nivel if nivel in ["success", "error", "warning", "info", "mikrotik"] else "info"
        self.log_text.tag_add(tag, "end-2l", "end-1l")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def enqueue_stats(self, stats):
        self.result_queue.put({"type": "stats", "stats": stats.copy()})

    def enqueue_progress(self, progresso, speed_text=None):
        self.result_queue.put({"type": "progress", "value": progresso, "text": f"{progresso:.1f}%", "speed": speed_text})

    def enqueue_finish(self, status_text, info_text=None):
        self.result_queue.put({"type": "finish", "status": status_text, "info": info_text})

    def limpar_log(self):
        """Limpa o log"""
        self.log_text.delete(1.0, tk.END)
        self.log("Log limpo", "info")
    
    def salvar_log(self):
        """Salva o log"""
        arquivo = filedialog.asksaveasfilename(defaultextension=".txt")
        if arquivo:
            with open(arquivo, 'w', encoding='utf-8') as f:
                f.write(self.log_text.get(1.0, tk.END))
            self.log(f"Log salvo em {arquivo}", "success")
    
    def atualizar_estatisticas(self, stats):
        """Atualiza os cards de estatísticas"""
        for key, value in stats.items():
            if key in self.stats_vars:
                self.stats_vars[key].set(str(value))
    
    def ip_to_int(self, ip):
        """Converte IP para número inteiro para ordenação"""
        partes = ip.split('.')
        return (int(partes[0]) << 24) + (int(partes[1]) << 16) + (int(partes[2]) << 8) + int(partes[3])
    
    def coletar_mikrotik_ssh(self, ip, usuario, senha, porta, timeout):
        """Coleta informações de um MikroTik via SSH"""
        tempo_inicio = time.time()
        ssh = None

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, port=int(porta), username=usuario, password=senha, timeout=timeout)
            
            # Coletar informações
            dados = {
                "Device Name": "N/A",
                "SSID": "N/A",
                "IP": ip,
                "Modo": "N/A",
                "Equipamento": "N/A",
                "TX/RX Signal/Clientes": "N/A",
                "Frequency": "N/A",
                "Channel Width": "N/A",
                "LAN Speed": "N/A"
            }
            
            # System Resource
            stdin, stdout, stderr = ssh.exec_command('/system resource print')
            resource_output = stdout.read().decode(errors="ignore")
            dados["Equipamento"] = extract_colon(resource_output, 'board-name')
            
            # System Identity
            stdin, stdout, stderr = ssh.exec_command('/system identity print')
            identity_output = stdout.read().decode(errors="ignore")
            dados["Device Name"] = extract_colon(identity_output, 'name')
            
            # LAN Speed
            stdin, stdout, stderr = ssh.exec_command('/interface ethernet monitor ether1 once')
            lan_output = stdout.read().decode(errors="ignore")
            dados["LAN Speed"] = extract_colon(lan_output, 'rate')
            
            # Wireless
            stdin, stdout, stderr = ssh.exec_command('/interface wireless print terse where !disabled')
            wireless_output = stdout.read().decode(errors="ignore")
            
            if wireless_output.strip():
                # SSID
                ssid = extract_equals(wireless_output, 'ssid')
                dados["SSID"] = ssid if ssid != "N/A" else "N/A"
                
                # Modo
                mode_wlan = extract_equals(wireless_output, 'mode')
                if mode_wlan != "N/A":
                    mode_lower = mode_wlan.lower()
                    if "ap" in mode_lower or mode_lower == "bridge":
                        dados["Modo"] = "Access Point"
                    elif "station" in mode_lower:
                        dados["Modo"] = "Station"
                    else:
                        dados["Modo"] = mode_wlan
                
                # Frequency
                frequency = extract_equals(wireless_output, 'frequency')
                if frequency != "N/A":
                    dados["Frequency"] = f"{frequency} MHz"
                
                # Channel Width
                channel_width = extract_equals(wireless_output, 'channel-width')
                if channel_width != "N/A":
                    dados["Channel Width"] = f"{channel_width} MHz"
                
                # Nome da interface
                wlan_name = extract_equals(wireless_output, 'name')
                if wlan_name == "N/A":
                    wlan_name = "wlan1"
                
                # TX/RX Signal/Clientes
                if dados["Modo"] == "Access Point":
                    stdin, stdout, stderr = ssh.exec_command('/interface wireless registration-table print count-only')
                    clientes = stdout.read().decode().strip()
                    dados["TX/RX Signal/Clientes"] = clientes if clientes.isdigit() else "0"
                elif dados["Modo"] == "Station":
                    stdin, stdout, stderr = ssh.exec_command(f'/interface wireless monitor "{wlan_name}" once')
                    monitor_output = stdout.read().decode(errors="ignore")
                    rx_signal = extract_colon(monitor_output, 'tx-signal-strength').split('@')[0].strip()
                    tx_signal = extract_colon(monitor_output, 'signal-strength').split('@')[0].strip()
                    if tx_signal != "N/A" and rx_signal != "N/A":
                        dados["TX/RX Signal/Clientes"] = f"{tx_signal}/{rx_signal}"
            
            tempo_total = time.time() - tempo_inicio
            return dados, tempo_total, "mikrotik"
        except AuthenticationException as e:
            self.log(f"❌ Autenticação SSH falhou para {ip}: {e}", "error")
        except (SSHException, socket.timeout, OSError) as e:
            self.log(f"❌ Erro SSH para {ip}: {e}", "error")
        except Exception as e:
            self.log(f"❌ Erro inesperado MikroTik {ip}: {e}", "error")
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass

        return {
            "Device Name": "N/A", "SSID": "N/A", "IP": ip, "Modo": "N/A",
            "Equipamento": "N/A", "TX/RX Signal/Clientes": "N/A",
            "Frequency": "N/A", "Channel Width": "N/A", "LAN Speed": "N/A"
        }, time.time() - tempo_inicio, "error"
    
    def coletar_airos_web_com_retry(self, ip, usuario, senha, porta, timeout, max_retries):
        """Coleta equipamento AirOS via Web com sistema de retry e reload"""
        
        for tentativa in range(1, max_retries + 1):
            self.log(f"🔄 Tentativa {tentativa}/{max_retries} para {ip}", "info")
            
            resultado = self.coletar_airos_web(ip, usuario, senha, porta, timeout)
            
            if resultado[0] is not None:
                # Verificar se conseguiu dados válidos
                dados = resultado[0]
                if dados["Device Name"] != "N/A" or dados["Equipamento"] != "N/A":
                    return resultado
            
            if tentativa < max_retries:
                self.log(f"⏳ Aguardando {RETRY_DELAY}s antes da próxima tentativa...", "warning")
                time.sleep(RETRY_DELAY)
        
        # Se todas as tentativas falharam
        self.log(f"❌ Todas as {max_retries} tentativas falharam para {ip}", "error")
        return {
            "Device Name": "N/A", "SSID": "N/A", "IP": ip, "Modo": "N/A",
            "Equipamento": "N/A", "TX/RX Signal/Clientes": "N/A",
            "Frequency": "N/A", "Channel Width": "N/A", "LAN Speed": "N/A"
        }, time.time() - timeout, "error"
    
    def coletar_airos_web(self, ip, usuario, senha, porta, timeout):
        """Coleta equipamento AirOS via Web utilizando os elementos do DOM."""

        url = f"http://{ip}:{porta}"
        driver = None
        tempo_inicio = time.time()

        try:
            # ============================================================
            # CONFIGURAÇÃO DO CHROME
            # ============================================================

            chrome_options = webdriver.ChromeOptions()

            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-images")
            chrome_options.add_argument("--window-size=1024,768")
            chrome_options.add_argument("--log-level=3")

            chrome_options.page_load_strategy = "normal"

            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )

            driver.set_page_load_timeout(timeout)

            # ============================================================
            # ACESSA O EQUIPAMENTO
            # ============================================================

            driver.get(url)

            time.sleep(2)

            # ============================================================
            # LOGIN
            # ============================================================

            try:
                wait = WebDriverWait(driver, 15)

                wait.until(
                    EC.presence_of_element_located(
                        (By.ID, "username")
                    )
                )

                campo_usuario = driver.find_element(
                    By.ID,
                    "username"
                )

                campo_senha = driver.find_element(
                    By.ID,
                    "password"
                )

                campo_usuario.clear()
                campo_usuario.send_keys(usuario)

                campo_senha.clear()
                campo_senha.send_keys(senha)

                # Tenta localizar o botão de login
                botoes_submit = driver.find_elements(
                    By.XPATH,
                    '//input[@type="submit"]'
                )

                if botoes_submit:
                    botoes_submit[0].click()
                else:
                    campo_senha.send_keys(Keys.ENTER)

                time.sleep(3)

            except Exception:
                # Alguns equipamentos podem já estar autenticados
                pass

            # ============================================================
            # AGUARDA O AIR OS CARREGAR OS DADOS
            # ============================================================

            time.sleep(3)

            # ============================================================
            # FUNÇÃO AUXILIAR PARA LER ELEMENTOS DO DOM
            # ============================================================

            def obter_valor(element_id):
                """
                Obtém o valor diretamente do elemento HTML.

                Prioridade:
                1. innerText
                2. text
                3. textContent
                """

                try:
                    elemento = driver.find_element(
                        By.ID,
                        element_id
                    )

                    # innerText
                    valor = elemento.get_attribute("innerText")

                    if valor is not None:
                        valor = valor.strip()

                        if valor:
                            return valor

                    # Selenium .text
                    valor = elemento.text

                    if valor is not None:
                        valor = valor.strip()

                        if valor:
                            return valor

                    # textContent
                    valor = elemento.get_attribute("textContent")

                    if valor is not None:
                        valor = valor.strip()

                        if valor:
                            return valor

                    return ""

                except Exception:
                    return ""

            # ============================================================
            # FUNÇÃO AUXILIAR PARA OBTER INNERHTML
            # ============================================================

            def obter_inner_html(element_id):
                """
                Retorna o innerHTML do elemento.
                Útil principalmente para elementos
                preenchidos dinamicamente pelo JavaScript do AirOS.
                """

                try:
                    elemento = driver.find_element(
                        By.ID,
                        element_id
                    )

                    return elemento.get_attribute("innerHTML") or ""

                except Exception:
                    return ""

            # ============================================================
            # FUNÇÃO AUXILIAR PARA LIMPAR VALORES
            # ============================================================

            def limpar_valor(valor):
                if valor is None:
                    return "N/A"

                valor = str(valor).replace("\xa0", " ").strip()

                if not valor:
                    return "N/A"

                return valor

            # ============================================================
            # AGUARDA OS DADOS PRINCIPAIS
            #
            # O AirOS preenche vários campos através de JavaScript.
            # Portanto, não basta o HTML ter carregado.
            # ============================================================

            try:
                wait = WebDriverWait(driver, 15)

                wait.until(
                    lambda d: (
                        d.find_element(By.ID, "hostname")
                        .get_attribute("innerText") or ""
                    ).strip() != ""
                )

            except Exception:
                # Continua mesmo se o campo não ficar preenchido
                pass

            # Pequena margem para o reloadStatus() do AirOS
            time.sleep(1)

            # ============================================================
            # DADOS PRINCIPAIS
            # ============================================================

            device_name = limpar_valor(
                obter_valor("hostname")
            )

            device_model = limpar_valor(
                obter_valor("devmodel")
            )

            network_mode = limpar_valor(
                obter_valor("netmode")
            )

            wireless_mode = limpar_valor(
                obter_valor("wmode")
            )

            ssid = limpar_valor(
                obter_valor("essid")
            )

            channel = limpar_valor(
                obter_valor("channel")
            )

            frequency = limpar_valor(
                obter_valor("frequency")
            )

            channel_width = limpar_valor(
                obter_valor("wd")
            )

            # ============================================================
            # DADOS DE RÁDIO
            # ============================================================

            distance = limpar_valor(
                obter_valor("ack")
            )

            tx_power = limpar_valor(
                obter_valor("txpower")
            )

            antenna = limpar_valor(
                obter_valor("antenna")
            )

            # ============================================================
            # HARDWARE
            # ============================================================

            cpu = limpar_valor(
                obter_valor("cpu")
            )

            memory = limpar_valor(
                obter_valor("memory")
            )

            # ============================================================
            # CONEXÃO
            # ============================================================

            ap_mac = limpar_valor(
                obter_valor("apmac")
            )

            signal = limpar_valor(
                obter_valor("signal")
            )

            signal_0 = limpar_valor(
                obter_valor("signal_0")
            )

            signal_1 = limpar_valor(
                obter_valor("signal_1")
            )

            clients = limpar_valor(
                obter_valor("count")
            )

            # ============================================================
            # QUALIDADE DO LINK
            # ============================================================

            noise_floor = limpar_valor(
                obter_valor("noisef")
            )

            ccq = limpar_valor(
                obter_valor("ccq")
            )

            tx_rate = limpar_valor(
                obter_valor("txrate")
            )

            rx_rate = limpar_valor(
                obter_valor("rxrate")
            )

            # ============================================================
            # AIRMAX
            # ============================================================

            airmax = limpar_valor(
                obter_valor("polling")
            )

            airmax_quality = limpar_valor(
                obter_valor("amq")
            )

            airmax_capacity = limpar_valor(
                obter_valor("amc")
            )

            # ============================================================
            # LARGURA / FREQUÊNCIA
            # ============================================================

            freq_start = limpar_valor(
                obter_valor("freqstart")
            )

            freq_stop = limpar_valor(
                obter_valor("freqstop")
            )

            # ============================================================
            # INTERFACE DE REDE
            #
            # #ifinfo é preenchido dinamicamente pelo AirOS.
            # Aqui lemos somente o conteúdo desse elemento,
            # em vez de procurar "LAN" no body inteiro.
            # ============================================================

            lan_speed = "N/A"

            try:
                ifinfo_element = driver.find_element(
                    By.ID,
                    "ifinfo"
                )

                lan_text = (
                    ifinfo_element.get_attribute("innerText")
                    or ifinfo_element.text
                    or ""
                ).strip()

                if lan_text:
                    # Mantém a compatibilidade com o formato
                    # que o código antigo esperava.
                    match_lan = re.search(
                        r'(\d+Mbps-[A-Za-z]+)',
                        lan_text,
                        re.IGNORECASE
                    )

                    if match_lan:
                        lan_speed = match_lan.group(1).strip()
                    else:
                        lan_speed = lan_text

            except Exception:
                lan_speed = "N/A"

            # ============================================================
            # DICIONÁRIO PRINCIPAL
            #
            # Mantidos os nomes usados pelo restante do programa.
            # ============================================================

            dados = {
                "Device Name": device_name,
                "SSID": ssid,
                "IP": ip,
                "Modo": wireless_mode,
                "Equipamento": device_model,
                "TX/RX Signal/Clientes": "N/A",
                "Frequency": frequency,
                "Channel Width": channel_width,
                "LAN Speed": lan_speed,

                # Informações adicionais
                "Network Mode": network_mode,
                "Channel": channel,
                "Distance": distance,
                "TX Power": tx_power,
                "Antenna": antenna,
                "CPU": cpu,
                "Memory": memory,
                "AP MAC": ap_mac,
                "Signal": signal,
                "Signal 0": signal_0,
                "Signal 1": signal_1,
                "Clients": clients,
                "Noise Floor": noise_floor,
                "CCQ": ccq,
                "TX Rate": tx_rate,
                "RX Rate": rx_rate,
                "airMAX": airmax,
                "airMAX Quality": airmax_quality,
                "airMAX Capacity": airmax_capacity,
                "Frequency Start": freq_start,
                "Frequency Stop": freq_stop
            }

            # ============================================================
            # STATION
            # ============================================================

            if "station" in wireless_mode.lower():

                # --------------------------------------------------------
                # Primeiro tenta utilizar diretamente os dados da página
                # principal.
                # --------------------------------------------------------

                tx_signal = "N/A"
                rx_signal = "N/A"

                # O campo #signal normalmente representa o sinal do
                # Station na página principal.
                if signal != "N/A":
                    rx_signal = signal

                # Em alguns AirOS o sinal das chains também representa
                # os níveis individuais.
                #
                # Não vamos assumir que signal_0/signal_1 sejam TX/RX,
                # portanto não os utilizamos como TX.
                # --------------------------------------------------------

                # --------------------------------------------------------
                # AP INFORMATION
                # --------------------------------------------------------

                try:
                    wait = WebDriverWait(driver, 10)

                    aba_ap = wait.until(
                        EC.element_to_be_clickable(
                            (
                                By.XPATH,
                                "//a[contains(text(), 'AP Information')]"
                            )
                        )
                    )

                    driver.execute_script(
                        "arguments[0].click();",
                        aba_ap
                    )

                    time.sleep(3)

                    # ----------------------------------------------------
                    # O AirOS carrega o conteúdo dentro de #extraFrame.
                    # Primeiro tentamos ler diretamente esse elemento.
                    # ----------------------------------------------------

                    texto_ap = ""

                    try:
                        extra_frame = driver.find_element(
                            By.ID,
                            "extraFrame"
                        )

                        texto_ap = (
                            extra_frame.get_attribute("innerText")
                            or extra_frame.text
                            or ""
                        ).strip()

                    except Exception:
                        pass

                    # ----------------------------------------------------
                    # O HTML dessa aba não foi fornecido junto com o
                    # HTML principal. Portanto, aqui mantemos uma
                    # pequena compatibilidade por texto apenas para
                    # RX/TX Signal da página AP Information.
                    # ----------------------------------------------------

                    if texto_ap:

                        match_rx = re.search(
                            r'RX Signal:\s*([^\n]+)',
                            texto_ap,
                            re.IGNORECASE
                        )

                        if match_rx:
                            valor_rx = match_rx.group(1).strip()

                            match_num = re.search(
                                r'(-?\d+)',
                                valor_rx
                            )

                            if match_num:
                                rx_signal = match_num.group(1)

                        match_tx = re.search(
                            r'TX Signal:\s*([^\n]+)',
                            texto_ap,
                            re.IGNORECASE
                        )

                        if match_tx:
                            valor_tx = match_tx.group(1).strip()

                            match_num = re.search(
                                r'(-?\d+)',
                                valor_tx
                            )

                            if match_num:
                                tx_signal = match_num.group(1)

                    # ----------------------------------------------------
                    # Monta TX/RX
                    # ----------------------------------------------------

                    if tx_signal != "N/A" and rx_signal != "N/A":
                        dados["TX/RX Signal/Clientes"] = (
                            f"{tx_signal}/{rx_signal}"
                        )

                    elif rx_signal != "N/A":
                        dados["TX/RX Signal/Clientes"] = (
                            f"N/A/{rx_signal}"
                        )

                    elif tx_signal != "N/A":
                        dados["TX/RX Signal/Clientes"] = (
                            f"{tx_signal}/N/A"
                        )

                    else:
                        dados["TX/RX Signal/Clientes"] = "N/A"

                except Exception:
                    # Se não conseguir acessar AP Information,
                    # ainda preservamos o sinal encontrado na página
                    # principal.
                    if signal != "N/A":
                        dados["TX/RX Signal/Clientes"] = (
                            f"N/A/{signal}"
                        )
                    else:
                        dados["TX/RX Signal/Clientes"] = "N/A"

            # ============================================================
            # ACCESS POINT
            # ============================================================

            elif (
                "access point" in wireless_mode.lower()
                or wireless_mode.lower() == "ap"
            ):

                # #count é o elemento oficial do AirOS para Connections
                # na página principal.
                count = obter_valor("count")

                if count:
                    dados["TX/RX Signal/Clientes"] = count
                else:
                    dados["TX/RX Signal/Clientes"] = "0"

            # ============================================================
            # OUTROS MODOS
            # ============================================================

            else:
                dados["TX/RX Signal/Clientes"] = "N/A"

            # ============================================================
            # FINALIZA
            # ============================================================

            try:
                driver.quit()
            except Exception:
                pass

            tempo_total = time.time() - tempo_inicio

            return dados, tempo_total, "airos"

        # ================================================================
        # ERRO GERAL
        # ================================================================

        except Exception as e:

            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

            tempo_total = time.time() - tempo_inicio

            return None, tempo_total, "error"
    def coletar_equipamento_rapido(self, ip, usuario_airos, senha_airos, porta_airos, 
                                   usuario_mikrotik, senha_mikrotik, porta_ssh, timeout, max_retries):
        """Tenta coletar via SSH (MikroTik) primeiro, depois via Web (AirOS) com retry"""
        
        # Primeiro tentar SSH para MikroTik
        dados_mik, tempo_mik, tipo_mik = self.coletar_mikrotik_ssh(ip, usuario_mikrotik, senha_mikrotik, porta_ssh, timeout)
        
        # Se conseguiu coletar via SSH e encontrou um MikroTik válido
        if dados_mik["Equipamento"] != "N/A" or dados_mik["Device Name"] != "N/A":
            return dados_mik, tempo_mik, "mikrotik"
        
        # Se não, tentar via Web para AirOS com retry
        dados_airos, tempo_airos, tipo_airos = self.coletar_airos_web_com_retry(ip, usuario_airos, senha_airos, porta_airos, timeout, max_retries)
        
        return dados_airos, tempo_airos, tipo_airos
    
    def executar_coleta_paralela(self, ips, usuario_airos, senha_airos, porta_airos,
                                  usuario_mikrotik, senha_mikrotik, porta_ssh, 
                                  timeout, max_workers, delay_ms, max_retries):
        """Executa coleta paralela com múltiplas threads"""
        resultados = []
        total = len(ips)
        stats = {"total": total, "success": 0, "failed": 0, "active": 0, "airos": 0, "mikrotik": 0}
        tempo_inicio = time.time()
        
        self.log(f"🚀 Iniciando coleta paralela com {max_workers} threads simultâneas!", "success")
        self.log(f"⚡ Timeout: {timeout}s | Delay: {delay_ms}ms", "info")
        self.log(f"🔄 Tentativas por IP: {max_retries}", "info")
        self.log(f"🔷 Tentando MikroTik via SSH primeiro, depois AirOS via Web", "info")
        self.log(f"⏱️ Timeouts estendidos para garantir coleta completa", "info")
        self.enqueue_stats(stats)
        
        futures = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for ip in ips:
                if not self.running:
                    break
                
                while self.pause and self.running:
                    time.sleep(0.1)
                
                future = executor.submit(
                    self.coletar_equipamento_rapido, 
                    ip, usuario_airos, senha_airos, porta_airos,
                    usuario_mikrotik, senha_mikrotik, porta_ssh, timeout, max_retries
                )
                futures.append(future)
                
                stats["active"] = len([f for f in futures if not f.done()])
                self.enqueue_stats(stats)
                
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000)
            
            for future in as_completed(futures):
                if not self.running:
                    break
                try:
                    dados, tempo, tipo = future.result()
                    resultados.append(dados)
                    
                    if dados["Device Name"] != "N/A" or dados["Equipamento"] != "N/A":
                        stats["success"] += 1
                        if tipo == "mikrotik":
                            stats["mikrotik"] += 1
                            nivel_log = "mikrotik"
                            icon = "🔷"
                        else:
                            stats["airos"] += 1
                            nivel_log = "success"
                            icon = "✅"
                        
                        tx_rx = dados["TX/RX Signal/Clientes"]
                        freq = dados["Frequency"]
                        canal = dados["Channel Width"]
                        
                        if freq != "N/A" or dados["SSID"] != "N/A":
                            self.log(f"{icon} {dados['IP']} - {dados['Device Name']} | {dados['Modo']} | TX/RX: {tx_rx} | {freq} | {canal} ({tempo:.1f}s)", nivel_log)
                        else:
                            self.log(f"{icon} {dados['IP']} - {dados['Device Name']} ({tempo:.1f}s)", nivel_log)
                    else:
                        stats["failed"] += 1
                        self.log(f"❌ {dados['IP']} - Falha na coleta após {max_retries} tentativas ({tempo:.1f}s)", "error")
                    
                    stats["active"] = len([f for f in futures if not f.done()])
                    elapsed = time.time() - tempo_inicio
                    speed = (len(resultados) / elapsed) * 60 if elapsed > 0 else 0
                    self.enqueue_progress((len(resultados) / total) * 100, f"{speed:.0f} IPs/min")
                    self.enqueue_stats(stats)
                except Exception as e:
                    stats["failed"] += 1
                    self.log(f"❌ Erro na coleta de future: {e}", "error")
                    stats["active"] = len([f for f in futures if not f.done()])
                    self.enqueue_stats(stats)
                    self.enqueue_progress((len(resultados) / total) * 100)
        
        if not self.running:
            for future in futures:
                if not future.done():
                    future.cancel()

        failed_ips = [dados['IP'] for dados in resultados if dados.get('Device Name') == 'N/A' and dados.get('Equipamento') == 'N/A']
        if self.running and failed_ips:
            self.log(f"🔍 Última verificação calma para {len(failed_ips)} equipamentos sem leitura N/A...", "info")
            calm_timeout = min(timeout * 2, 120)
            calm_delay = max(delay_ms * 2, 1000)
            calm_workers = min(3, max_workers)
            calm_results = {}

            with ThreadPoolExecutor(max_workers=calm_workers) as calm_executor:
                calm_futures = {
                    calm_executor.submit(
                        self.coletar_equipamento_rapido,
                        ip, usuario_airos, senha_airos, porta_airos,
                        usuario_mikrotik, senha_mikrotik, porta_ssh,
                        calm_timeout, max_retries
                    ): ip
                    for ip in failed_ips
                }

                for future in as_completed(calm_futures):
                    ip = calm_futures[future]
                    if not self.running:
                        break
                    try:
                        dados, tempo, tipo = future.result()
                        calm_results[ip] = (dados, tempo, tipo)

                        if dados.get('Device Name') != 'N/A' or dados.get('Equipamento') != 'N/A':
                            self.log(f"✅ Rechecagem calma válida para {ip}: {dados.get('Device Name', 'N/A')} ({tempo:.1f}s)", "success")
                            stats['success'] += 1
                            if tipo == 'mikrotik':
                                stats['mikrotik'] += 1
                            else:
                                stats['airos'] += 1
                        else:
                            self.log(f"❌ Rechecagem calma sem resultado para {ip} ({tempo:.1f}s)", "error")
                            stats['failed'] += 1
                    except Exception as e:
                        self.log(f"❌ Erro na rechecagem calma de {ip}: {e}", "error")
                        stats['failed'] += 1

                    stats['active'] = len([f for f in futures if not f.done()])
                    elapsed = time.time() - tempo_inicio
                    speed = (len(resultados) / elapsed) * 60 if elapsed > 0 else 0
                    self.enqueue_progress((len(resultados) / total) * 100, f"{speed:.0f} IPs/min")
                    self.enqueue_stats(stats)

            for index, dados in enumerate(resultados):
                ip = dados.get('IP')
                if ip in calm_results and calm_results[ip][0] is not None:
                    resultados[index] = calm_results[ip][0]

        tempo_total = time.time() - tempo_inicio
        velocidade = (len(resultados) / tempo_total) * 60 if tempo_total > 0 else 0
        
        self.log(f"\n{'='*50}", "info")
        self.log(f"✅ Coleta finalizada em {tempo_total:.1f} segundos!", "success")
        self.log(f"⚡ Velocidade média: {velocidade:.0f} IPs por minuto", "success")
        self.log(f"📊 Sucesso: {stats['success']}/{stats['total']} ({stats['success']*100/stats['total']:.1f}%)", "success")
        self.log(f"📡 AirOS: {stats['airos']} | 🔷 MikroTik: {stats['mikrotik']}", "info")
        
        if resultados and self.arquivo_saida and self.running:
            self.salvar_excel_rapido(resultados)
        
        self.coletando = False
        self.enqueue_finish(
            f"Coleta finalizada! {stats['airos']} AirOS, {stats['mikrotik']} MikroTik",
            None
        )
    
    def salvar_excel_rapido(self, resultados):
        """Salva resultados em Excel ordenados por IP com formatação condicional"""
        try:
            df = pd.DataFrame(resultados)
            
            df['IP_Num'] = df['IP'].apply(self.ip_to_int)
            df = df.sort_values('IP_Num').reset_index(drop=True)
            df = df.drop('IP_Num', axis=1)
            
            colunas = ['Device Name', 'SSID', 'IP', 'Modo', 'Equipamento',
                      'TX/RX Signal/Clientes', 'Frequency', 'Channel Width', 'LAN Speed']
            df = df[colunas]
            
            with pd.ExcelWriter(self.arquivo_saida, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Coleta', index=False)
                
                workbook = writer.book
                worksheet = writer.sheets['Coleta']
                
                # Cores
                red_fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
                orange_fill = PatternFill(start_color="FFB347", end_color="FFB347", fill_type="solid")
                
                # Percorrer todas as linhas
                for row in range(2, len(resultados) + 2):
                    device_name_cell = worksheet.cell(row=row, column=1)
                    
                    if device_name_cell.value == "N/A":
                        modo_cell = worksheet.cell(row=row, column=4)
                        equipamento_cell = worksheet.cell(row=row, column=5)
                        
                        if modo_cell.value == "N/A" and equipamento_cell.value == "N/A":
                            for col in range(1, 10):
                                worksheet.cell(row=row, column=col).fill = orange_fill
                    
                    lan_speed_cell = worksheet.cell(row=row, column=9)
                    if lan_speed_cell.value and "10" in str(lan_speed_cell.value):
                        if "100" not in str(lan_speed_cell.value):
                            lan_speed_cell.fill = red_fill
                
                # Ajustar largura das colunas
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    worksheet.column_dimensions[column_letter].width = min(max_length + 2, 35)
                
                # Adicionar aba de resumo
                stats_resumo = {
                    "Data da Coleta": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "Total de IPs": len(resultados),
                    "Equipamentos Encontrados": len([r for r in resultados if r.get('Device Name') != 'N/A']),
                    "AirOS": len([r for r in resultados if 'Station' in r.get('Modo', '') or 'Access Point' in r.get('Modo', '')]),
                    "MikroTik": len([r for r in resultados if r.get('Equipamento') != 'N/A' and r.get('Device Name') != 'N/A' and 'Access Point' not in r.get('Modo', '')])
                }
                
                resumo_df = pd.DataFrame(list(stats_resumo.items()), columns=['Informação', 'Valor'])
                resumo_df.to_excel(writer, sheet_name='Resumo', index=False)
            
            self.log(f"💾 Dados salvos em: {self.arquivo_saida} (ordenado por IP)", "success")
            self.log(f"📊 Total de equipamentos encontrados: {len([r for r in resultados if r.get('Device Name') != 'N/A'])}", "success")
            
        except Exception as e:
            self.log(f"❌ Erro ao salvar: {e}", "error")
    
    def process_queue(self):
        """Processa fila de resultados"""
        try:
            while True:
                msg = self.result_queue.get_nowait()
                msg_type = msg.get("type", "log")

                if msg_type == "log":
                    self._append_log(msg["text"], msg.get("level", "info"))
                elif msg_type == "stats":
                    self.atualizar_estatisticas(msg["stats"])
                elif msg_type == "progress":
                    self.progress_bar["value"] = msg["value"]
                    self.progress_var.set(msg.get("text", "0%"))
                    if msg.get("speed") is not None:
                        self.speed_var.set(msg["speed"])
                elif msg_type == "finish":
                    if msg.get("status"):
                        self.status_var.set(msg["status"])
                    if msg.get("info"):
                        self._append_log(msg["info"], "info")
                    self.btn_iniciar.config(state="normal")
                    self.btn_pausar.config(state="disabled", text="⏸ Pausar")
                    self.btn_parar.config(state="disabled")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_queue)
    
    def iniciar_coleta(self):
        """Inicia coleta"""
        if not self.arquivo_saida:
            messagebox.showwarning("Atenção", "Selecione o arquivo Excel primeiro!")
            self.selecionar_arquivo()
            if not self.arquivo_saida:
                return
        
        ip_inicio = self.ip_inicio_entry.get().strip()
        ip_fim = self.ip_fim_entry.get().strip()
        
        usuario_airos = self.usuario_entry.get().strip()
        senha_airos = self.senha_entry.get().strip()
        porta_airos = self.porta_entry.get().strip()
        
        usuario_mikrotik = self.usuario_mikrotik_entry.get().strip()
        senha_mikrotik = self.senha_mikrotik_entry.get().strip()
        porta_ssh = self.porta_ssh_entry.get().strip()
        
        max_workers = int(self.threads_spin.get())
        timeout = int(self.timeout_spin.get())
        delay_ms = int(self.delay_spin.get())
        max_retries = int(self.retries_spin.get())
        
        try:
            inicio_ip = ipaddress.ip_address(ip_inicio)
            fim_ip = ipaddress.ip_address(ip_fim)
            if inicio_ip > fim_ip:
                raise ValueError
            if inicio_ip.version != 4 or fim_ip.version != 4:
                raise ValueError
            ips = [str(ipaddress.ip_address(int(inicio_ip) + i)) for i in range(int(fim_ip) - int(inicio_ip) + 1)]
        except Exception:
            messagebox.showerror("Erro", "IPs inválidos! Use o formato: 192.168.1.1 e forneça um intervalo válido.")
            return
        
        self.running = True
        self.coletando = True
        self.pause = False
        
        self.btn_iniciar.config(state="disabled")
        self.btn_pausar.config(state="normal")
        self.btn_parar.config(state="normal")
        
        self.progress_bar["value"] = 0
        self.progress_var.set("0%")
        self.speed_var.set("0 IPs/min")
        
        self.log("="*60, "info")
        self.log(f"📋 Coleta configurada:", "info")
        self.log(f"   IPs: {len(ips)} equipamentos", "info")
        self.log(f"   Threads: {max_workers} simultâneas", "info")
        self.log(f"   Timeout: {timeout}s por equipamento", "info")
        self.log(f"   Delay: {delay_ms}ms entre requisições", "info")
        self.log(f"   Tentativas por IP: {max_retries}", "info")
        self.log(f"   🔷 MikroTik SSH: porta {porta_ssh}", "info")
        self.log(f"   📡 AirOS Web: porta {porta_airos}", "info")
        self.log("="*60, "info")
        
        self.status_var.set(f"Coletando {len(ips)} equipamentos com {max_retries} tentativas por IP...")
        
        thread = threading.Thread(target=self.executar_coleta_paralela, 
                                  args=(ips, usuario_airos, senha_airos, porta_airos,
                                        usuario_mikrotik, senha_mikrotik, porta_ssh,
                                        timeout, max_workers, delay_ms, max_retries))
        thread.daemon = True
        thread.start()
    
    def pausar_coleta(self):
        self.pause = not self.pause
        if self.pause:
            self.btn_pausar.config(text="▶ Continuar")
            self.status_var.set("Coleta pausada")
            self.log("⏸️ Coleta pausada", "warning")
        else:
            self.btn_pausar.config(text="⏸ Pausar")
            self.status_var.set("Coleta em andamento...")
            self.log("▶️ Coleta retomada", "info")
    
    def parar_coleta(self):
        self.running = False
        self.pause = False
        self.status_var.set("Parando coleta...")
        self.log("⏹️ Parando coleta...", "warning")

def main():
    root = tk.Tk()
    app = ColetorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
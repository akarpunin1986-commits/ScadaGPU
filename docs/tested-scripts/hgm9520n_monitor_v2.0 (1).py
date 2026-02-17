#!/usr/bin/env python3
"""
HGM9520N Generator Controller Monitor & Control
GUI Application for Windows

Requirements:
    pip install pymodbus

Usage:
    python hgm9520n_monitor.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from datetime import datetime

# Detect pymodbus version
PYMODBUS_VERSION = "unknown"

try:
    import pymodbus
    PYMODBUS_VERSION = getattr(pymodbus, '__version__', 'unknown')
    print(f"[INIT] pymodbus version: {PYMODBUS_VERSION}")
except:
    pass

try:
    from pymodbus.client import ModbusTcpClient
    print(f"[INIT] Imported from pymodbus.client")
except ImportError:
    try:
        from pymodbus.client.sync import ModbusTcpClient
        print(f"[INIT] Imported from pymodbus.client.sync")
    except ImportError:
        print("[INIT] pymodbus not found, installing...")
        import subprocess
        subprocess.check_call(['pip', 'install', 'pymodbus'])
        from pymodbus.client import ModbusTcpClient

# Special value meaning "no data" in Smartgen protocol
NO_DATA_VALUE = 32766


class HGM9520NMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("HGM9520N Monitor v2.0")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        # Modbus client
        self.client = None
        self.connected = False
        self.polling = False
        self.poll_thread = None
        
        # Detected working method
        self.read_method = None
        
        # Default connection settings
        self.ip_var = tk.StringVar(value="10.11.6.51")
        self.port_var = tk.StringVar(value="502")
        self.slave_var = tk.StringVar(value="1")
        self.poll_interval_var = tk.StringVar(value="1000")
        
        # Data variables
        self.data_vars = {}
        
        self.create_widgets()
        self.log(f"pymodbus version: {PYMODBUS_VERSION}")
        
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="5")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Connection Frame
        conn_frame = ttk.LabelFrame(main_frame, text="Подключение", padding="5")
        conn_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(conn_frame, text="IP:").grid(row=0, column=0, padx=2)
        ttk.Entry(conn_frame, textvariable=self.ip_var, width=15).grid(row=0, column=1, padx=2)
        ttk.Label(conn_frame, text="Port:").grid(row=0, column=2, padx=2)
        ttk.Entry(conn_frame, textvariable=self.port_var, width=6).grid(row=0, column=3, padx=2)
        ttk.Label(conn_frame, text="Slave ID:").grid(row=0, column=4, padx=2)
        ttk.Entry(conn_frame, textvariable=self.slave_var, width=4).grid(row=0, column=5, padx=2)
        ttk.Label(conn_frame, text="Интервал (мс):").grid(row=0, column=6, padx=2)
        ttk.Entry(conn_frame, textvariable=self.poll_interval_var, width=6).grid(row=0, column=7, padx=2)
        
        self.connect_btn = ttk.Button(conn_frame, text="Подключить", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=8, padx=10)
        
        self.status_label = ttk.Label(conn_frame, text="● Отключено", foreground="red")
        self.status_label.grid(row=0, column=9, padx=10)
        
        # Notebook
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=5)
        
        tab1 = ttk.Frame(notebook, padding="5")
        notebook.add(tab1, text="Основные параметры")
        self.create_main_params_tab(tab1)
        
        tab2 = ttk.Frame(notebook, padding="5")
        notebook.add(tab2, text="Мощность")
        self.create_power_tab(tab2)
        
        tab3 = ttk.Frame(notebook, padding="5")
        notebook.add(tab3, text="Двигатель")
        self.create_engine_tab(tab3)
        
        tab4 = ttk.Frame(notebook, padding="5")
        notebook.add(tab4, text="Статус и аварии")
        self.create_status_tab(tab4)
        
        # Control Frame
        ctrl_frame = ttk.LabelFrame(main_frame, text="Управление", padding="10")
        ctrl_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(ctrl_frame, text="▶ ПУСК", command=self.cmd_start, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="⬛ СТОП", command=self.cmd_stop, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="AUTO", command=self.cmd_auto, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="MANUAL", command=self.cmd_manual, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="GEN ВКЛ", command=self.cmd_gen_close, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="GEN ОТКЛ", command=self.cmd_gen_open, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="СБРОС", command=self.cmd_reset, width=10).pack(side=tk.LEFT, padx=5)
        
        # Log Frame
        log_frame = ttk.LabelFrame(main_frame, text="Лог", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_frame, height=8, width=80)
        self.log_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
    def create_main_params_tab(self, parent):
        gen_v_frame = ttk.LabelFrame(parent, text="Напряжение генератора", padding="5")
        gen_v_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.create_param_row(gen_v_frame, "gen_uab", "UAB:", "В", 0)
        self.create_param_row(gen_v_frame, "gen_ubc", "UBC:", "В", 1)
        self.create_param_row(gen_v_frame, "gen_uca", "UCA:", "В", 2)
        self.create_param_row(gen_v_frame, "gen_freq", "Частота:", "Гц", 3)
        
        mains_v_frame = ttk.LabelFrame(parent, text="Напряжение сети", padding="5")
        mains_v_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        self.create_param_row(mains_v_frame, "mains_uab", "UAB:", "В", 0)
        self.create_param_row(mains_v_frame, "mains_ubc", "UBC:", "В", 1)
        self.create_param_row(mains_v_frame, "mains_uca", "UCA:", "В", 2)
        self.create_param_row(mains_v_frame, "mains_freq", "Частота:", "Гц", 3)
        
        current_frame = ttk.LabelFrame(parent, text="Ток генератора", padding="5")
        current_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        self.create_param_row(current_frame, "current_a", "IA:", "А", 0)
        self.create_param_row(current_frame, "current_b", "IB:", "А", 1)
        self.create_param_row(current_frame, "current_c", "IC:", "А", 2)
        self.create_param_row(current_frame, "current_earth", "IE:", "А", 3)
        
        sync_frame = ttk.LabelFrame(parent, text="Синхронизация", padding="5")
        sync_frame.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")
        self.create_param_row(sync_frame, "volt_diff", "ΔU:", "В", 0)
        self.create_param_row(sync_frame, "freq_diff", "ΔF:", "Гц", 1)
        self.create_param_row(sync_frame, "phase_diff", "Δφ:", "°", 2)
        
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        
    def create_power_tab(self, parent):
        p_frame = ttk.LabelFrame(parent, text="Активная мощность (P)", padding="5")
        p_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.create_param_row(p_frame, "power_a", "PA:", "кВт", 0)
        self.create_param_row(p_frame, "power_b", "PB:", "кВт", 1)
        self.create_param_row(p_frame, "power_c", "PC:", "кВт", 2)
        self.create_param_row(p_frame, "power_total", "P∑:", "кВт", 3)
        
        q_frame = ttk.LabelFrame(parent, text="Реактивная мощность (Q)", padding="5")
        q_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        self.create_param_row(q_frame, "reactive_a", "QA:", "квар", 0)
        self.create_param_row(q_frame, "reactive_b", "QB:", "квар", 1)
        self.create_param_row(q_frame, "reactive_c", "QC:", "квар", 2)
        self.create_param_row(q_frame, "reactive_total", "Q∑:", "квар", 3)
        
        pf_frame = ttk.LabelFrame(parent, text="Коэффициент мощности", padding="5")
        pf_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        self.create_param_row(pf_frame, "pf_a", "PF A:", "", 0)
        self.create_param_row(pf_frame, "pf_b", "PF B:", "", 1)
        self.create_param_row(pf_frame, "pf_c", "PF C:", "", 2)
        self.create_param_row(pf_frame, "pf_avg", "PF∑:", "", 3)
        
        acc_frame = ttk.LabelFrame(parent, text="Накопленные", padding="5")
        acc_frame.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")
        self.create_param_row(acc_frame, "energy_kwh", "Энергия:", "кВт⋅ч", 0)
        self.create_param_row(acc_frame, "run_hours", "Моточасы:", "ч", 1)
        self.create_param_row(acc_frame, "start_count", "Пусков:", "", 2)
        self.create_param_row(acc_frame, "load_pct", "Нагрузка:", "%", 3)
        
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        
    def create_engine_tab(self, parent):
        eng_frame = ttk.LabelFrame(parent, text="Параметры двигателя", padding="5")
        eng_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.create_param_row(eng_frame, "engine_speed", "Обороты:", "об/мин", 0)
        self.create_param_row(eng_frame, "coolant_temp", "Т охлаждения:", "°C", 1)
        self.create_param_row(eng_frame, "oil_pressure", "Давл. масла:", "кПа", 2)
        self.create_param_row(eng_frame, "fuel_level", "Уровень топлива:", "%", 3)
        
        batt_frame = ttk.LabelFrame(parent, text="Питание", padding="5")
        batt_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        self.create_param_row(batt_frame, "battery_volt", "АКБ:", "В", 0)
        self.create_param_row(batt_frame, "charger_volt", "Зарядка:", "В", 1)
        
        ecu_frame = ttk.LabelFrame(parent, text="ECU данные", padding="5")
        ecu_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        self.create_param_row(ecu_frame, "oil_temp", "Т масла:", "°C", 0)
        self.create_param_row(ecu_frame, "fuel_pressure", "Давл. топлива:", "кПа", 1)
        self.create_param_row(ecu_frame, "turbo_pressure", "Турбо:", "кПа", 2)
        self.create_param_row(ecu_frame, "fuel_consumption", "Расход:", "л/ч", 3)
        
        gov_frame = ttk.LabelFrame(parent, text="Регуляторы", padding="5")
        gov_frame.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")
        self.create_param_row(gov_frame, "gov_output", "GOV выход:", "%", 0)
        self.create_param_row(gov_frame, "avr_output", "AVR выход:", "%", 1)
        
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        
    def create_status_tab(self, parent):
        mode_frame = ttk.LabelFrame(parent, text="Режим работы", padding="5")
        mode_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.mode_auto_ind = self.create_indicator(mode_frame, "AUTO", 0)
        self.mode_manual_ind = self.create_indicator(mode_frame, "MANUAL", 1)
        self.mode_test_ind = self.create_indicator(mode_frame, "TEST", 2)
        self.mode_stop_ind = self.create_indicator(mode_frame, "STOP", 3)
        
        gen_status_frame = ttk.LabelFrame(parent, text="Статус генератора", padding="5")
        gen_status_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        self.data_vars["gen_status_text"] = tk.StringVar(value="---")
        ttk.Label(gen_status_frame, textvariable=self.data_vars["gen_status_text"], 
                  font=("Arial", 12, "bold")).pack(pady=10)
        
        breaker_frame = ttk.LabelFrame(parent, text="Выключатели", padding="5")
        breaker_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        self.gen_normal_ind = self.create_indicator(breaker_frame, "GEN НОРМ", 0)
        self.gen_closed_ind = self.create_indicator(breaker_frame, "GEN ВКЛ", 1)
        self.mains_normal_ind = self.create_indicator(breaker_frame, "MAINS НОРМ", 2)
        self.mains_load_ind = self.create_indicator(breaker_frame, "MAINS НАГ", 3)
        
        alarm_frame = ttk.LabelFrame(parent, text="Аварии", padding="5")
        alarm_frame.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")
        self.alarm_common_ind = self.create_indicator(alarm_frame, "ОБЩАЯ АВАРИЯ", 0, color="red")
        self.alarm_shutdown_ind = self.create_indicator(alarm_frame, "SHUTDOWN", 1, color="red")
        self.alarm_warning_ind = self.create_indicator(alarm_frame, "WARNING", 2, color="orange")
        self.alarm_block_ind = self.create_indicator(alarm_frame, "BLOCK", 3, color="yellow")
        self.data_vars["alarm_count"] = tk.StringVar(value="Аварий: 0")
        ttk.Label(alarm_frame, textvariable=self.data_vars["alarm_count"]).grid(row=4, column=0, columnspan=2, pady=5)
        
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        
    def create_param_row(self, parent, key, label, unit, row):
        ttk.Label(parent, text=label, width=12).grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.data_vars[key] = tk.StringVar(value="---")
        ttk.Label(parent, textvariable=self.data_vars[key], width=10, anchor="e", 
                  font=("Consolas", 10)).grid(row=row, column=1, sticky="e", padx=2, pady=2)
        ttk.Label(parent, text=unit, width=6).grid(row=row, column=2, sticky="w", padx=2, pady=2)
        
    def create_indicator(self, parent, text, row, color="green"):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=2, sticky="w", padx=5, pady=2)
        canvas = tk.Canvas(frame, width=16, height=16, highlightthickness=0)
        canvas.pack(side=tk.LEFT, padx=5)
        ind_id = canvas.create_oval(2, 2, 14, 14, fill="gray", outline="darkgray")
        ttk.Label(frame, text=text).pack(side=tk.LEFT)
        return (canvas, ind_id, color)
        
    def set_indicator(self, indicator, active):
        canvas, ind_id, color = indicator
        canvas.itemconfig(ind_id, fill=color if active else "gray")
        
    def toggle_connection(self):
        if not self.connected:
            self.connect()
        else:
            self.disconnect()
            
    def connect(self):
        ip = self.ip_var.get()
        port = int(self.port_var.get())
        self.log(f"Подключение к {ip}:{port}...")
        
        try:
            self.client = ModbusTcpClient(ip, port=port)
            if self.client.connect():
                self.connected = True
                self.read_method = None
                self.connect_btn.config(text="Отключить")
                self.status_label.config(text="● Подключено", foreground="green")
                self.log(f"✓ Подключено к {ip}:{port}")
                self.start_polling()
            else:
                raise Exception("Не удалось подключиться")
        except Exception as ex:
            self.log(f"✗ Ошибка: {ex}")
            messagebox.showerror("Ошибка", str(ex))
            
    def disconnect(self):
        self.stop_polling()
        if self.client:
            self.client.close()
        self.connected = False
        self.connect_btn.config(text="Подключить")
        self.status_label.config(text="● Отключено", foreground="red")
        self.log("Отключено")
        
    def start_polling(self):
        self.polling = True
        self.poll_thread = threading.Thread(target=self.poll_loop, daemon=True)
        self.poll_thread.start()
        
    def stop_polling(self):
        self.polling = False
        
    def poll_loop(self):
        poll_count = 0
        while self.polling and self.connected:
            poll_count += 1
            try:
                self.read_all_data()
                if poll_count % 30 == 0:
                    self.safe_log(f"Поллинг #{poll_count} OK")
            except Exception as ex:
                if poll_count % 30 == 0:
                    self.safe_log(f"Ошибка: {ex}")
            
            interval = int(self.poll_interval_var.get()) / 1000
            time.sleep(interval)
    
    def safe_log(self, message):
        self.root.after(0, lambda m=message: self.log(m))
    
    def read_regs(self, address, count):
        """Read registers - try different methods until one works"""
        slave_id = int(self.slave_var.get())
        
        if self.read_method == 'no_slave':
            return self.client.read_holding_registers(address=address, count=count)
        elif self.read_method == 'unit':
            return self.client.read_holding_registers(address=address, count=count, unit=slave_id)
        elif self.read_method == 'slave':
            return self.client.read_holding_registers(address=address, count=count, slave=slave_id)
        
        # Auto-detect
        try:
            result = self.client.read_holding_registers(address=address, count=count)
            if not result.isError():
                self.read_method = 'no_slave'
                return result
        except TypeError:
            pass
        
        try:
            result = self.client.read_holding_registers(address=address, count=count, unit=slave_id)
            if not result.isError():
                self.read_method = 'unit'
                return result
        except TypeError:
            pass
            
        try:
            result = self.client.read_holding_registers(address=address, count=count, slave=slave_id)
            if not result.isError():
                self.read_method = 'slave'
                return result
        except TypeError:
            pass
        
        return self.client.read_holding_registers(address=address, count=count)
    
    def write_coil_cmd(self, address, value=True):
        """Write coil - try different methods"""
        slave_id = int(self.slave_var.get())
        
        try:
            return self.client.write_coil(address=address, value=value)
        except TypeError:
            pass
        
        try:
            return self.client.write_coil(address=address, value=value, unit=slave_id)
        except TypeError:
            pass
            
        try:
            return self.client.write_coil(address=address, value=value, slave=slave_id)
        except TypeError:
            pass
        
        return self.client.write_coil(address, value)
    
    def is_no_data(self, val):
        """Check if value means 'no data' - 32766 or very large values"""
        return val == NO_DATA_VALUE or val >= 32000
    
    def is_no_data_percent(self, val):
        """Check if percentage value is invalid (> 100% means no sensor)"""
        return val == NO_DATA_VALUE or val > 100
    
    def is_no_data_temp(self, val):
        """Check if temperature is invalid (> 200 or < -50 is unrealistic)"""
        signed = self.to_signed(val)
        return val == NO_DATA_VALUE or val >= 32000 or signed > 200 or signed < -50
    
    def is_no_data_pressure(self, val):
        """Check if pressure is invalid (very large value)"""
        return val == NO_DATA_VALUE or val >= 10000
    
    def is_no_data_rpm(self, val):
        """Check if RPM is invalid (> 5000 is unrealistic for genset)"""
        return val == NO_DATA_VALUE or val > 5000
    
    def format_val(self, val, ratio=1.0, decimals=1):
        if self.is_no_data(val):
            return "---"
        result = val * ratio
        return f"{int(result)}" if decimals == 0 else f"{result:.{decimals}f}"
            
    def read_all_data(self):
        # Status bits (0)
        result = self.read_regs(0, 1)
        if not result.isError():
            status = result.registers[0]
            self.root.after(0, lambda s=status: self.update_status_bits(s))
        
        # Mains voltage (120-135)
        result = self.read_regs(120, 16)
        if not result.isError():
            regs = list(result.registers)
            self.root.after(0, lambda r=regs: self.update_mains_voltage(r))
        
        # Gen voltage (140-158)
        result = self.read_regs(140, 19)
        if not result.isError():
            regs = list(result.registers)
            self.root.after(0, lambda r=regs: self.update_gen_voltage(r))
        
        # Currents (166-173)
        result = self.read_regs(166, 8)
        if not result.isError():
            regs = list(result.registers)
            self.root.after(0, lambda r=regs: self.update_currents(r))
        
        # Power (174-201)
        result = self.read_regs(174, 28)
        if not result.isError():
            regs = list(result.registers)
            self.root.after(0, lambda r=regs: self.update_power(r))
        
        # Engine (212-241)
        result = self.read_regs(212, 30)
        if not result.isError():
            regs = list(result.registers)
            self.root.after(0, lambda r=regs: self.update_engine(r))
        
        # Status/accumulated (260-275)
        result = self.read_regs(260, 16)
        if not result.isError():
            regs = list(result.registers)
            self.root.after(0, lambda r=regs: self.update_accumulated(r))
            
        # Breaker status (114)
        result = self.read_regs(114, 1)
        if not result.isError():
            val = result.registers[0]
            self.root.after(0, lambda v=val: self.update_breaker_status(v))
            
        # Alarm count (511)
        result = self.read_regs(511, 1)
        if not result.isError():
            count = result.registers[0]
            self.root.after(0, lambda c=count: self.data_vars["alarm_count"].set(f"Аварий: {c}"))
    
    def update_status_bits(self, status):
        self.set_indicator(self.mode_auto_ind, bool(status & (1 << 9)))
        self.set_indicator(self.mode_manual_ind, bool(status & (1 << 10)))
        self.set_indicator(self.mode_stop_ind, bool(status & (1 << 11)))
        self.set_indicator(self.mode_test_ind, bool(status & (1 << 8)))
        self.set_indicator(self.alarm_common_ind, bool(status & (1 << 0)))
        self.set_indicator(self.alarm_shutdown_ind, bool(status & (1 << 1)))
        self.set_indicator(self.alarm_warning_ind, bool(status & (1 << 2)))
        self.set_indicator(self.alarm_block_ind, bool(status & (1 << 7)))
        
    def update_breaker_status(self, status):
        self.set_indicator(self.mains_normal_ind, bool(status & (1 << 0)))
        self.set_indicator(self.mains_load_ind, bool(status & (1 << 1)))
        self.set_indicator(self.gen_normal_ind, bool(status & (1 << 2)))
        self.set_indicator(self.gen_closed_ind, bool(status & (1 << 3)))
        
    def update_mains_voltage(self, regs):
        uab = (regs[1] * 65536 + regs[0]) * 0.1
        ubc = (regs[3] * 65536 + regs[2]) * 0.1
        uca = (regs[5] * 65536 + regs[4]) * 0.1
        freq = regs[15] * 0.01
        self.data_vars["mains_uab"].set(f"{uab:.1f}")
        self.data_vars["mains_ubc"].set(f"{ubc:.1f}")
        self.data_vars["mains_uca"].set(f"{uca:.1f}")
        self.data_vars["mains_freq"].set(f"{freq:.2f}")
        
    def update_gen_voltage(self, regs):
        uab = (regs[1] * 65536 + regs[0]) * 0.1
        ubc = (regs[3] * 65536 + regs[2]) * 0.1
        uca = (regs[5] * 65536 + regs[4]) * 0.1
        freq = regs[15] * 0.01
        self.data_vars["gen_uab"].set(f"{uab:.1f}")
        self.data_vars["gen_ubc"].set(f"{ubc:.1f}")
        self.data_vars["gen_uca"].set(f"{uca:.1f}")
        self.data_vars["gen_freq"].set(f"{freq:.2f}")
        
        volt_diff = self.to_signed(regs[16]) * 0.1
        freq_diff = self.to_signed(regs[17]) * 0.01
        phase_diff = self.to_signed(regs[18]) * 0.1
        self.data_vars["volt_diff"].set(f"{volt_diff:.1f}")
        self.data_vars["freq_diff"].set(f"{freq_diff:.2f}")
        self.data_vars["phase_diff"].set(f"{phase_diff:.1f}")
        
    def update_currents(self, regs):
        self.data_vars["current_a"].set(self.format_val(regs[0], 0.1))
        self.data_vars["current_b"].set(self.format_val(regs[1], 0.1))
        self.data_vars["current_c"].set(self.format_val(regs[2], 0.1))
        self.data_vars["current_earth"].set(self.format_val(regs[3], 0.1))
        
    def update_power(self, regs):
        pa = self.to_signed32(regs[0], regs[1]) * 0.1
        pb = self.to_signed32(regs[2], regs[3]) * 0.1
        pc = self.to_signed32(regs[4], regs[5]) * 0.1
        pt = self.to_signed32(regs[6], regs[7]) * 0.1
        self.data_vars["power_a"].set(f"{pa:.1f}")
        self.data_vars["power_b"].set(f"{pb:.1f}")
        self.data_vars["power_c"].set(f"{pc:.1f}")
        self.data_vars["power_total"].set(f"{pt:.1f}")
        
        qa = self.to_signed32(regs[8], regs[9]) * 0.1
        qb = self.to_signed32(regs[10], regs[11]) * 0.1
        qc = self.to_signed32(regs[12], regs[13]) * 0.1
        qt = self.to_signed32(regs[14], regs[15]) * 0.1
        self.data_vars["reactive_a"].set(f"{qa:.1f}")
        self.data_vars["reactive_b"].set(f"{qb:.1f}")
        self.data_vars["reactive_c"].set(f"{qc:.1f}")
        self.data_vars["reactive_total"].set(f"{qt:.1f}")
        
        pf_a = self.to_signed(regs[24]) * 0.001
        pf_b = self.to_signed(regs[25]) * 0.001
        pf_c = self.to_signed(regs[26]) * 0.001
        pf_avg = self.to_signed(regs[27]) * 0.001
        self.data_vars["pf_a"].set(f"{pf_a:.3f}")
        self.data_vars["pf_b"].set(f"{pf_b:.3f}")
        self.data_vars["pf_c"].set(f"{pf_c:.3f}")
        self.data_vars["pf_avg"].set(f"{pf_avg:.3f}")
        
    def update_engine(self, regs):
        # Engine speed (212) - RPM check
        self.data_vars["engine_speed"].set("---" if self.is_no_data_rpm(regs[0]) else f"{regs[0]}")
        
        # Battery (213), Charger (214) - 0.1V ratio
        self.data_vars["battery_volt"].set(self.format_val(regs[1], 0.1))
        self.data_vars["charger_volt"].set(self.format_val(regs[2], 0.1))
        
        # Temperature (220) - signed, temperature check
        self.data_vars["coolant_temp"].set("---" if self.is_no_data_temp(regs[8]) else f"{self.to_signed(regs[8])}")
        
        # Oil pressure (222) - pressure check
        self.data_vars["oil_pressure"].set("---" if self.is_no_data_pressure(regs[10]) else f"{regs[10]}")
        
        # Fuel level (224) - PERCENTAGE check (> 100 = no data)
        self.data_vars["fuel_level"].set("---" if self.is_no_data_percent(regs[12]) else f"{regs[12]}")
        
        # Load % (232) - signed, percentage check
        if self.is_no_data(regs[20]):
            self.data_vars["load_pct"].set("---")
        else:
            load = self.to_signed(regs[20])
            self.data_vars["load_pct"].set("---" if load > 150 or load < -50 else f"{load}")
        
        # Oil temp (234) - signed, temperature check
        self.data_vars["oil_temp"].set("---" if self.is_no_data_temp(regs[22]) else f"{self.to_signed(regs[22])}")
        
        # Fuel pressure (236) - pressure check
        self.data_vars["fuel_pressure"].set("---" if self.is_no_data_pressure(regs[24]) else f"{regs[24]}")
        
        # Turbo pressure (240) - pressure check
        self.data_vars["turbo_pressure"].set("---" if self.is_no_data_pressure(regs[28]) else f"{regs[28]}")
        
        # Fuel consumption (241) - 0.1 ratio, reasonable check
        if self.is_no_data(regs[29]) or regs[29] > 10000:
            self.data_vars["fuel_consumption"].set("---")
        else:
            self.data_vars["fuel_consumption"].set(f"{regs[29] * 0.1:.1f}")
        
    def update_accumulated(self, regs):
        gen_status_codes = {
            0: "В ожидании", 1: "Прогрев", 2: "Топливо ВКЛ", 3: "Прокрутка",
            4: "Пауза прокр.", 5: "Безоп. работа", 6: "Холост. ход", 7: "Прогрев ВО",
            8: "Ожид. нагрузки", 9: "РАБОТА", 10: "Охлаждение", 11: "Холост. стоп",
            12: "ETS", 13: "Ожид. останова", 14: "После останова", 15: "Ошибка останова"
        }
        self.data_vars["gen_status_text"].set(gen_status_codes.get(regs[0], f"? ({regs[0]})"))
        self.data_vars["run_hours"].set(f"{regs[10]}:{regs[11]:02d}")
        self.data_vars["start_count"].set(f"{regs[13]}")
        self.data_vars["energy_kwh"].set(f"{regs[15] * 65536 + regs[14]}")
        
    def to_signed(self, val):
        return val - 65536 if val > 32767 else val
        
    def to_signed32(self, lsb, msb):
        val = msb * 65536 + lsb
        return val - 0x100000000 if val > 0x7FFFFFFF else val
        
    def send_coil_command(self, address, name):
        if not self.connected:
            messagebox.showwarning("Внимание", "Нет подключения")
            return
        self.log(f"Команда '{name}'...")
        try:
            result = self.write_coil_cmd(address, True)
            if hasattr(result, 'isError') and result.isError():
                raise Exception(str(result))
            self.log(f"✓ '{name}' OK")
        except Exception as ex:
            self.log(f"✗ Ошибка: {ex}")
            messagebox.showerror("Ошибка", str(ex))
            
    def cmd_start(self):
        if messagebox.askyesno("Подтверждение", "Запустить генератор?"):
            self.send_coil_command(0, "ПУСК")
    def cmd_stop(self):
        if messagebox.askyesno("Подтверждение", "Остановить генератор?"):
            self.send_coil_command(1, "СТОП")
    def cmd_auto(self):
        self.send_coil_command(3, "AUTO")
    def cmd_manual(self):
        self.send_coil_command(4, "MANUAL")
    def cmd_gen_close(self):
        if messagebox.askyesno("Подтверждение", "Включить GEN?"):
            self.send_coil_command(6, "GEN CLOSE")
    def cmd_gen_open(self):
        if messagebox.askyesno("Подтверждение", "Отключить GEN?"):
            self.send_coil_command(7, "GEN OPEN")
    def cmd_reset(self):
        self.send_coil_command(17, "СБРОС")
        
    def log(self, message):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {message}\n")
        self.log_text.see(tk.END)
        print(f"[{ts}] {message}")
        
    def on_closing(self):
        self.disconnect()
        self.root.destroy()


def main():
    print("="*40)
    print("HGM9520N Monitor v2.0")
    print(f"pymodbus: {PYMODBUS_VERSION}")
    print("="*40)
    root = tk.Tk()
    app = HGM9520NMonitor(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()

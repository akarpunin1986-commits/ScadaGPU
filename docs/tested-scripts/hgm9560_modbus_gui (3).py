#!/usr/bin/env python3
"""
HGM9560 Genset Controller - Modbus TCP GUI
Для работы через адаптер USR-TCP232-410S (RS485 -> Ethernet)

Протокол: Modbus RTU over TCP (raw socket)
Поддерживаемые функции: 01H (Read Coils), 03H (Read Registers), 05H (Write Coil), 06H (Write Register)
Параметры RS485: 9600, 8N2, Slave Address 1 (по умолчанию)
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import socket
import struct
import threading
import time
from datetime import datetime

# ==============================================================================
# Modbus RTU Implementation (raw, no external dependencies)
# ==============================================================================

def crc16_modbus(data: bytes) -> int:
    """CRC-16/Modbus"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_read_registers(slave: int, start: int, count: int) -> bytes:
    """FC 03H - Read Holding Registers"""
    frame = struct.pack('>BBhH', slave, 0x03, start, count)
    crc = crc16_modbus(frame)
    return frame + struct.pack('<H', crc)


def build_read_coils(slave: int, start: int, count: int) -> bytes:
    """FC 01H - Read Coils"""
    frame = struct.pack('>BBhH', slave, 0x01, start, count)
    crc = crc16_modbus(frame)
    return frame + struct.pack('<H', crc)


def build_write_coil(slave: int, address: int, value: bool) -> bytes:
    """FC 05H - Write Single Coil (FF00=ON, 0000=OFF)"""
    data_val = 0xFF00 if value else 0x0000
    frame = struct.pack('>BBHH', slave, 0x05, address, data_val)
    crc = crc16_modbus(frame)
    return frame + struct.pack('<H', crc)


def build_write_register(slave: int, address: int, value: int) -> bytes:
    """FC 06H - Write Single Register"""
    frame = struct.pack('>BBHH', slave, 0x06, address, value & 0xFFFF)
    crc = crc16_modbus(frame)
    return frame + struct.pack('<H', crc)


def parse_read_registers_response(data: bytes):
    """Parse FC03 response -> list of register values (unsigned 16-bit)"""
    if len(data) < 5:
        return None
    slave, fc, byte_count = struct.unpack('>BBB', data[:3])
    if fc & 0x80:
        return None  # Exception
    n_regs = byte_count // 2
    values = []
    for i in range(n_regs):
        val = struct.unpack('>H', data[3 + i*2 : 5 + i*2])[0]
        values.append(val)
    return values


def parse_read_coils_response(data: bytes):
    """Parse FC01 response -> list of bit values"""
    if len(data) < 4:
        return None
    slave, fc, byte_count = struct.unpack('>BBB', data[:3])
    if fc & 0x80:
        return None
    coil_bytes = data[3:3+byte_count]
    bits = []
    for b in coil_bytes:
        for bit_pos in range(8):
            bits.append((b >> bit_pos) & 1)
    return bits


def signed16(val):
    """Convert unsigned 16-bit to signed"""
    return val - 0x10000 if val >= 0x8000 else val


def signed32(low, high):
    """Combine two 16-bit registers into signed 32-bit (LSB first)"""
    val = (high << 16) | low
    if val >= 0x80000000:
        val -= 0x100000000
    return val


# ==============================================================================
# HGM9560 Register Map
# ==============================================================================

GENSET_STATUS = {
    0: "Standby", 1: "Preheat", 2: "Fuel Output", 3: "Crank",
    4: "Crank Rest", 5: "Safety Run", 6: "Start Idle",
    7: "High Speed Warming Up", 8: "Wait for Load",
    9: "Normal Running", 10: "High Speed Cooling", 11: "Stop Idle",
    12: "ETS", 13: "Wait for Stop", 14: "Stop Failure"
}

SWITCH_STATUS = {
    0: "Synchronizing", 1: "Close Delay", 2: "Wait for Closing",
    3: "Closed", 4: "Unloading", 5: "Open Delay",
    6: "Wait for Opening", 7: "Opened"
}

MAINS_STATUS = {
    0: "Mains Normal", 1: "Mains Normal Delay",
    2: "Mains Abnormal", 3: "Mains Abnormal Delay"
}

MODE_BITS = {
    8: "Test Mode", 9: "Auto Mode", 10: "Manual Mode", 11: "Stop Mode"
}

ALARM_BITS_0 = {
    0: "Common Alarm", 1: "Shutdown Alarm", 2: "Warning Alarm",
    3: "Trip and Stop", 4: "Trip", 5: "Trip+Stop & Stop",
    6: "Mains Trip Alarm"
}

# Remote Coil Addresses (FC05)
REMOTE_COILS = {
    "Start":            0x0000,
    "Stop":             0x0001,
    "Auto":             0x0003,
    "Manual":           0x0004,
    "Mains Close/Open": 0x0005,
    "Busbar Close/Open":0x0006,
    "Up":               0x0007,
    "Down":             0x0008,
    "Left":             0x0009,
    "Right":            0x000A,
    "Confirm":          0x000B,
    "Mute":             0x000C,
}


# ==============================================================================
# Communication Class
# ==============================================================================

class ModbusConnection:
    def __init__(self):
        self.sock = None
        self.lock = threading.Lock()
        self.timeout = 2.0

    def connect(self, host: str, port: int) -> bool:
        try:
            self.disconnect()
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((host, port))
            return True
        except Exception as e:
            self.sock = None
            raise e

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

    def is_connected(self) -> bool:
        return self.sock is not None

    def send_receive(self, request: bytes) -> bytes:
        """Send Modbus RTU frame and receive response"""
        with self.lock:
            if not self.sock:
                raise ConnectionError("Not connected")
            try:
                # Clear any stale data
                self.sock.settimeout(0.1)
                try:
                    self.sock.recv(1024)
                except socket.timeout:
                    pass
                self.sock.settimeout(self.timeout)

                self.sock.sendall(request)
                # Wait for response (USR-TCP232 passes raw RTU frames)
                time.sleep(0.15)  # Modbus RTU inter-frame gap
                response = b''
                self.sock.settimeout(self.timeout)
                while True:
                    try:
                        chunk = self.sock.recv(256)
                        if not chunk:
                            break
                        response += chunk
                        if len(response) >= 5:  # Minimum response size
                            # Check if we have a complete frame
                            if response[1] == 0x03:
                                expected = 3 + response[2] + 2
                                if len(response) >= expected:
                                    break
                            elif response[1] == 0x01:
                                expected = 3 + response[2] + 2
                                if len(response) >= expected:
                                    break
                            elif response[1] in (0x05, 0x06):
                                if len(response) >= 8:
                                    break
                            elif response[1] & 0x80:
                                if len(response) >= 5:
                                    break
                    except socket.timeout:
                        break

                if len(response) < 5:
                    raise TimeoutError(f"Incomplete response: {response.hex()}" if response else "No response")

                # Verify CRC
                payload = response[:-2]
                received_crc = struct.unpack('<H', response[-2:])[0]
                calc_crc = crc16_modbus(payload)
                if received_crc != calc_crc:
                    raise ValueError(f"CRC error: got {received_crc:04X}, expected {calc_crc:04X}")

                return response

            except (socket.timeout, ConnectionError, OSError) as e:
                self.disconnect()
                raise ConnectionError(f"Communication error: {e}")

    def read_registers(self, slave: int, start: int, count: int) -> list:
        req = build_read_registers(slave, start, count)
        resp = self.send_receive(req)
        result = parse_read_registers_response(resp)
        if result is None:
            raise ValueError(f"Invalid response for FC03 @ {start}")
        return result

    def read_coils(self, slave: int, start: int, count: int) -> list:
        req = build_read_coils(slave, start, count)
        resp = self.send_receive(req)
        result = parse_read_coils_response(resp)
        if result is None:
            raise ValueError(f"Invalid response for FC01 @ {start}")
        return result

    def write_coil(self, slave: int, address: int, value: bool) -> bool:
        req = build_write_coil(slave, address, value)
        resp = self.send_receive(req)
        return resp[1] == 0x05

    def write_register(self, slave: int, address: int, value: int) -> bool:
        req = build_write_register(slave, address, value)
        resp = self.send_receive(req)
        return resp[1] == 0x06


# ==============================================================================
# GUI Application
# ==============================================================================

class HGM9560App:
    def __init__(self, root):
        self.root = root
        self.root.title("HGM9560 ШПР - Modbus TCP Monitor (USR-TCP232-410S)")
        self.root.geometry("1280x900")
        self.root.minsize(1100, 750)

        self.conn = ModbusConnection()
        self.polling = False
        self.poll_thread = None

        self._build_gui()
        self.log("Приложение запущено. Введите адрес адаптера и нажмите «Подключить».")

    # --------------------------------------------------------------------------
    # GUI Construction
    # --------------------------------------------------------------------------
    def _build_gui(self):
        style = ttk.Style()
        style.configure('Header.TLabel', font=('Segoe UI', 10, 'bold'))
        style.configure('Value.TLabel', font=('Consolas', 11))
        style.configure('Status.TLabel', font=('Segoe UI', 10, 'bold'), foreground='#006600')
        style.configure('Alarm.TLabel', font=('Segoe UI', 10, 'bold'), foreground='red')
        style.configure('Connected.TLabel', foreground='green', font=('Segoe UI', 10, 'bold'))
        style.configure('Disconnected.TLabel', foreground='red', font=('Segoe UI', 10, 'bold'))

        # ---- Connection Frame ----
        conn_frame = ttk.LabelFrame(self.root, text="  Подключение (USR-TCP232-410S)  ", padding=10)
        conn_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        ttk.Label(conn_frame, text="IP адрес адаптера:").grid(row=0, column=0, padx=5)
        self.ip_var = tk.StringVar(value="192.168.0.7")
        self.ip_entry = ttk.Entry(conn_frame, textvariable=self.ip_var, width=18, font=('Consolas', 11))
        self.ip_entry.grid(row=0, column=1, padx=5)

        ttk.Label(conn_frame, text="TCP порт:").grid(row=0, column=2, padx=5)
        self.port_var = tk.StringVar(value="502")
        ttk.Entry(conn_frame, textvariable=self.port_var, width=7, font=('Consolas', 11)).grid(row=0, column=3, padx=5)

        ttk.Label(conn_frame, text="Slave ID:").grid(row=0, column=4, padx=5)
        self.slave_var = tk.StringVar(value="1")
        ttk.Entry(conn_frame, textvariable=self.slave_var, width=5, font=('Consolas', 11)).grid(row=0, column=5, padx=5)

        ttk.Label(conn_frame, text="Таймаут (с):").grid(row=0, column=6, padx=5)
        self.timeout_var = tk.StringVar(value="2.0")
        ttk.Entry(conn_frame, textvariable=self.timeout_var, width=5, font=('Consolas', 11)).grid(row=0, column=7, padx=5)

        self.connect_btn = ttk.Button(conn_frame, text="Подключить", command=self.toggle_connection, width=14)
        self.connect_btn.grid(row=0, column=8, padx=10)

        self.conn_status = ttk.Label(conn_frame, text="● Отключено", style='Disconnected.TLabel')
        self.conn_status.grid(row=0, column=9, padx=10)

        # ---- Notebook (Tabs) ----
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Tab 1: Monitoring
        self._build_monitor_tab()
        # Tab 2: Manual Read/Write
        self._build_rw_tab()
        # Tab 3: Remote Control
        self._build_control_tab()
        # Tab 4: Load Management (ШПР)
        self._build_load_tab()
        # Tab 5: Log
        self._build_log_tab()

        # ---- Polling controls ----
        poll_frame = ttk.Frame(self.root)
        poll_frame.pack(fill=tk.X, padx=10, pady=(0, 5))

        self.poll_btn = ttk.Button(poll_frame, text="▶ Начать опрос", command=self.toggle_polling, width=16)
        self.poll_btn.pack(side=tk.LEFT, padx=5)

        ttk.Label(poll_frame, text="Интервал (с):").pack(side=tk.LEFT, padx=5)
        self.interval_var = tk.StringVar(value="2.0")
        ttk.Entry(poll_frame, textvariable=self.interval_var, width=5, font=('Consolas', 10)).pack(side=tk.LEFT)

        self.poll_status = ttk.Label(poll_frame, text="Опрос остановлен", style='Disconnected.TLabel')
        self.poll_status.pack(side=tk.LEFT, padx=15)

        self.last_update = ttk.Label(poll_frame, text="", font=('Segoe UI', 9))
        self.last_update.pack(side=tk.RIGHT, padx=10)

    # ---- Tab 1: Monitoring ----
    def _build_monitor_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  📊 Мониторинг  ")

        # Use a canvas for scrolling
        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        # Mouse wheel
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self.mon_labels = {}

        # --- Status & Mode ---
        f = ttk.LabelFrame(scrollable, text="  Статус контроллера  ", padding=8)
        f.pack(fill=tk.X, padx=5, pady=5)
        row = 0
        for key in ["mode", "genset_status", "mains_status", "mains_switch", "busbar_switch", "alarms"]:
            lbl_text = {
                "mode": "Режим", "genset_status": "Статус генератора",
                "mains_status": "Статус сети", "mains_switch": "Сетевой выкл.",
                "busbar_switch": "Шинный выкл.", "alarms": "Аварии"
            }[key]
            ttk.Label(f, text=f"{lbl_text}:", style='Header.TLabel').grid(row=row, column=0, sticky='w', padx=5, pady=2)
            self.mon_labels[key] = ttk.Label(f, text="---", style='Value.TLabel', width=40)
            self.mon_labels[key].grid(row=row, column=1, sticky='w', padx=10, pady=2)
            row += 1

        # --- Mains Electrical ---
        f = ttk.LabelFrame(scrollable, text="  Электрические параметры сети (Mains)  ", padding=8)
        f.pack(fill=tk.X, padx=5, pady=5)
        mains_params = [
            ("mains_uab", "UAB"), ("mains_ubc", "UBC"), ("mains_uca", "UCA"),
            ("mains_ua", "UA"), ("mains_ub", "UB"), ("mains_uc", "UC"),
            ("mains_freq", "Частота"), ("mains_ia", "IA"), ("mains_ib", "IB"), ("mains_ic", "IC"),
        ]
        for i, (key, lbl) in enumerate(mains_params):
            r, c = divmod(i, 5)
            ttk.Label(f, text=f"{lbl}:", style='Header.TLabel').grid(row=r, column=c*2, sticky='w', padx=5, pady=2)
            self.mon_labels[key] = ttk.Label(f, text="---", style='Value.TLabel', width=12)
            self.mon_labels[key].grid(row=r, column=c*2+1, sticky='w', padx=5, pady=2)

        # --- Busbar Electrical ---
        f = ttk.LabelFrame(scrollable, text="  Электрические параметры шины (Busbar)  ", padding=8)
        f.pack(fill=tk.X, padx=5, pady=5)
        busbar_params = [
            ("busbar_uab", "UAB"), ("busbar_ubc", "UBC"), ("busbar_uca", "UCA"),
            ("busbar_ua", "UA"), ("busbar_ub", "UB"), ("busbar_uc", "UC"),
            ("busbar_freq", "Частота"), ("busbar_current", "Ток шины"),
        ]
        for i, (key, lbl) in enumerate(busbar_params):
            r, c = divmod(i, 4)
            ttk.Label(f, text=f"{lbl}:", style='Header.TLabel').grid(row=r, column=c*2, sticky='w', padx=5, pady=2)
            self.mon_labels[key] = ttk.Label(f, text="---", style='Value.TLabel', width=14)
            self.mon_labels[key].grid(row=r, column=c*2+1, sticky='w', padx=5, pady=2)

        # --- Power ---
        f = ttk.LabelFrame(scrollable, text="  Мощность  ", padding=8)
        f.pack(fill=tk.X, padx=5, pady=5)
        power_params = [
            ("busbar_p", "P шины (kW)"), ("busbar_q", "Q шины (kvar)"),
            ("mains_total_p", "P сети (kW)"), ("mains_total_q", "Q сети (kvar)"),
        ]
        for i, (key, lbl) in enumerate(power_params):
            ttk.Label(f, text=f"{lbl}:", style='Header.TLabel').grid(row=0, column=i*2, sticky='w', padx=5, pady=2)
            self.mon_labels[key] = ttk.Label(f, text="---", style='Value.TLabel', width=14)
            self.mon_labels[key].grid(row=0, column=i*2+1, sticky='w', padx=5, pady=2)

        # --- Engine / Battery ---
        f = ttk.LabelFrame(scrollable, text="  Двигатель / Батарея / Энергия  ", padding=8)
        f.pack(fill=tk.X, padx=5, pady=5)
        engine_params = [
            ("battery_v", "Батарея (V)"),
            ("accum_kwh", "Всего kWh"), ("accum_kvarh", "Всего kvarh"),
            ("maint_hours", "ТО осталось (ч)"),
        ]
        for i, (key, lbl) in enumerate(engine_params):
            ttk.Label(f, text=f"{lbl}:", style='Header.TLabel').grid(row=0, column=i*2, sticky='w', padx=5, pady=2)
            self.mon_labels[key] = ttk.Label(f, text="---", style='Value.TLabel', width=14)
            self.mon_labels[key].grid(row=0, column=i*2+1, sticky='w', padx=5, pady=2)

    # ---- Tab 2: Read/Write ----
    def _build_rw_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  📝 Чтение/Запись  ")

        # READ SECTION
        rf = ttk.LabelFrame(tab, text="  Чтение регистров (FC 03H)  ", padding=10)
        rf.pack(fill=tk.X, pady=5)

        ttk.Label(rf, text="Начальный адрес:").grid(row=0, column=0, padx=5)
        self.read_addr_var = tk.StringVar(value="0")
        ttk.Entry(rf, textvariable=self.read_addr_var, width=8, font=('Consolas', 11)).grid(row=0, column=1, padx=5)

        ttk.Label(rf, text="Количество:").grid(row=0, column=2, padx=5)
        self.read_count_var = tk.StringVar(value="10")
        ttk.Entry(rf, textvariable=self.read_count_var, width=6, font=('Consolas', 11)).grid(row=0, column=3, padx=5)

        ttk.Button(rf, text="Прочитать", command=self.manual_read_registers).grid(row=0, column=4, padx=10)

        self.read_result = scrolledtext.ScrolledText(rf, height=8, width=100, font=('Consolas', 10))
        self.read_result.grid(row=1, column=0, columnspan=6, pady=5, sticky='ew')

        # READ COILS
        cf = ttk.LabelFrame(tab, text="  Чтение катушек (FC 01H)  ", padding=10)
        cf.pack(fill=tk.X, pady=5)

        ttk.Label(cf, text="Начальный адрес:").grid(row=0, column=0, padx=5)
        self.coil_addr_var = tk.StringVar(value="0")
        ttk.Entry(cf, textvariable=self.coil_addr_var, width=8, font=('Consolas', 11)).grid(row=0, column=1, padx=5)

        ttk.Label(cf, text="Количество:").grid(row=0, column=2, padx=5)
        self.coil_count_var = tk.StringVar(value="16")
        ttk.Entry(cf, textvariable=self.coil_count_var, width=6, font=('Consolas', 11)).grid(row=0, column=3, padx=5)

        ttk.Button(cf, text="Прочитать", command=self.manual_read_coils).grid(row=0, column=4, padx=10)

        self.coil_result = scrolledtext.ScrolledText(cf, height=4, width=100, font=('Consolas', 10))
        self.coil_result.grid(row=1, column=0, columnspan=6, pady=5, sticky='ew')

        # WRITE SECTION
        wf = ttk.LabelFrame(tab, text="  Запись регистра (FC 06H) — Адреса: 0199–0210, 0225–0231, 4351–4354  ", padding=10)
        wf.pack(fill=tk.X, pady=5)

        ttk.Label(wf, text="Адрес:").grid(row=0, column=0, padx=5)
        self.write_addr_var = tk.StringVar(value="0199")
        ttk.Entry(wf, textvariable=self.write_addr_var, width=8, font=('Consolas', 11)).grid(row=0, column=1, padx=5)

        ttk.Label(wf, text="Значение (dec):").grid(row=0, column=2, padx=5)
        self.write_val_var = tk.StringVar(value="0")
        ttk.Entry(wf, textvariable=self.write_val_var, width=10, font=('Consolas', 11)).grid(row=0, column=3, padx=5)

        ttk.Button(wf, text="Записать (06H)", command=self.manual_write_register, width=14).grid(row=0, column=4, padx=10)

        self.write_status_lbl = ttk.Label(wf, text="", font=('Segoe UI', 10))
        self.write_status_lbl.grid(row=0, column=5, padx=10)

        # WRITE COIL
        wcf = ttk.LabelFrame(tab, text="  Запись катушки (FC 05H)  ", padding=10)
        wcf.pack(fill=tk.X, pady=5)

        ttk.Label(wcf, text="Адрес:").grid(row=0, column=0, padx=5)
        self.wcoil_addr_var = tk.StringVar(value="0")
        ttk.Entry(wcf, textvariable=self.wcoil_addr_var, width=8, font=('Consolas', 11)).grid(row=0, column=1, padx=5)

        self.wcoil_val_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(wcf, text="ON (FF00)", variable=self.wcoil_val_var).grid(row=0, column=2, padx=5)

        ttk.Button(wcf, text="Записать (05H)", command=self.manual_write_coil, width=14).grid(row=0, column=3, padx=10)

        self.wcoil_status_lbl = ttk.Label(wcf, text="", font=('Segoe UI', 10))
        self.wcoil_status_lbl.grid(row=0, column=4, padx=10)

    # ---- Tab 3: Remote Control ----
    def _build_control_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  🎛 Управление  ")

        # Use canvas for scrolling
        canvas = tk.Canvas(tab, highlightthickness=0)
        vscroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        ctrl_scroll = ttk.Frame(canvas)
        ctrl_scroll.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=ctrl_scroll, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(ctrl_scroll, text="Дистанционное управление ШПР HGM9560 (FC 05H — одиночная команда)",
                  style='Header.TLabel').pack(pady=(10, 5))

        warn_lbl = ttk.Label(ctrl_scroll,
            text="⚠  ВНИМАНИЕ: Команды управляют контроллером параллельной работы (ШПР)!\n"
                 "    HGM9560 координирует сеть, шину и генератор. Убедитесь, что понимаете последствия.",
            foreground='red', font=('Segoe UI', 10))
        warn_lbl.pack(pady=5)

        btn_frame = ttk.Frame(ctrl_scroll)
        btn_frame.pack(pady=10, fill=tk.X, padx=10)

        # Buttons with descriptions for ШПР context
        buttons = [
            ("▶ Запуск ГУ", "Start", "#228B22",
             "Команда на запуск генераторной установки.\n"
             "ШПР отправляет сигнал пуска на контроллер генератора\n"
             "(HGM9520N/9510N). Работает в режиме Manual."),

            ("⏹ Останов ГУ", "Stop", "#CC0000",
             "Команда на остановку генераторной установки.\n"
             "ШПР выполняет разгрузку, размыкает шинный выключатель,\n"
             "затем даёт сигнал остановки генератору.\n"
             "Работает в любом режиме (Auto/Manual)."),

            ("🔄 Авто (АВР)", "Auto", "#0066CC",
             "Перевод ШПР в автоматический режим.\n"
             "Контроллер сам следит за сетью и при аварии:\n"
             "→ запускает генератор\n"
             "→ синхронизирует и подключает к шине\n"
             "→ управляет распределением нагрузки\n"
             "При восстановлении сети — обратный переход."),

            ("🔧 Ручной", "Manual", "#FF8C00",
             "Перевод ШПР в ручной режим.\n"
             "Все операции (пуск, стоп, коммутация выключателей)\n"
             "выполняются только по командам оператора.\n"
             "Необходим для ручного управления Start/Stop/Close/Open."),

            ("⚡ Сетевой выкл.", "Mains Close/Open", "#2E5090",
             "Управление сетевым выключателем (ввод от сети).\n"
             "Подключает/отключает внешнюю сеть от шины нагрузки.\n"
             "Close = замкнуть (подать сеть), Open = разомкнуть."),

            ("🔌 Шинный выкл.", "Busbar Close/Open", "#6B3A8A",
             "Управление шинным (генераторным) выключателем.\n"
             "Подключает/отключает генератор к общей шине.\n"
             "Перед замыканием ШПР выполняет синхронизацию\n"
             "(контроль U, f, φ между генератором и шиной).\n"
             "Close = подключить ГУ к шине, Open = отключить."),

            ("🔇 Сброс звука", "Mute", "#666666",
             "Сброс звуковой сигнализации (зуммера) на панели ШПР.\n"
             "Авария при этом остаётся активной до устранения причины."),
        ]

        for i, (text, cmd_key, color, desc) in enumerate(buttons):
            r, c = divmod(i, 4)
            # Button frame with description
            bf = ttk.Frame(btn_frame)
            bf.grid(row=r*2, column=c, padx=6, pady=4, sticky='n')

            btn = tk.Button(bf, text=text, width=18, height=2,
                           font=('Segoe UI', 10, 'bold'), fg='white', bg=color,
                           activebackground=color, relief=tk.RAISED,
                           command=lambda k=cmd_key: self.send_remote_command(k))
            btn.pack()

            # Tooltip on hover
            self._create_tooltip(btn, desc)

        # --- Descriptions panel ---
        desc_frame = ttk.LabelFrame(ctrl_scroll, text="  Описание команд ШПР (HGM9560)  ", padding=10)
        desc_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        desc_text = (
            "HGM9560 — контроллер параллельной работы (ШПР). Он не управляет двигателем напрямую,\n"
            "а координирует работу сети, шины и генераторной установки (ГУ).\n\n"

            "▶ Запуск ГУ — ШПР посылает сигнал пуска на контроллер генератора (HGM9520N/9510N)\n"
            "⏹ Останов ГУ — разгрузка → размыкание шинного выкл. → сигнал остановки на генератор\n"
            "🔄 Авто (АВР) — автоматическое управление: слежение за сетью, пуск/стоп ГУ, коммутация\n"
            "🔧 Ручной — все операции выполняются только по командам оператора\n"
            "⚡ Сетевой выкл. — замыкание/размыкание ввода от внешней сети\n"
            "🔌 Шинный выкл. — замыкание/размыкание генераторного контактора (с синхронизацией)\n"
            "🔇 Сброс звука — отключение зуммера аварии (авария остаётся активной)\n\n"

            "Типовая последовательность ручного пуска:\n"
            "  Ручной → Запуск ГУ → (ждать Normal Running) → Шинный выкл. (Close)\n\n"
            "Типовая последовательность остановки:\n"
            "  Шинный выкл. (Open) → Останов ГУ"
        )
        ttk.Label(desc_frame, text=desc_text, font=('Segoe UI', 9),
                  justify=tk.LEFT, wraplength=900).pack(anchor='w')

        # Remote Outputs
        out_frame = ttk.LabelFrame(ctrl_scroll,
            text="  Удалённые выходы ШПР (Remote Output 1–6) — назначение зависит от конфигурации проекта  ",
            padding=10)
        out_frame.pack(fill=tk.X, padx=10, pady=10)

        self.output_vars = {}
        for i in range(1, 7):
            var = tk.BooleanVar(value=False)
            self.output_vars[i] = var
            cb = ttk.Checkbutton(out_frame, text=f"Output {i}", variable=var,
                                command=lambda idx=i: self.send_output_command(idx))
            cb.grid(row=0, column=i-1, padx=10)

    # ---- Tab 4: Load Management ----
    def _build_load_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  ⚖ Распределение нагрузки  ")

        # Scrollable
        canvas = tk.Canvas(tab, highlightthickness=0)
        vscroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        load_scroll = ttk.Frame(canvas)
        load_scroll.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=load_scroll, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)

        # === Current values (read-only) ===
        cur_frame = ttk.LabelFrame(load_scroll, text="  Текущие значения (чтение)  ", padding=10)
        cur_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(cur_frame, text="Режим нагрузки:", style='Header.TLabel').grid(row=0, column=0, sticky='w', padx=5, pady=3)
        self.load_mode_read_lbl = ttk.Label(cur_frame, text="---", style='Value.TLabel', width=30)
        self.load_mode_read_lbl.grid(row=0, column=1, sticky='w', padx=10, pady=3)

        ttk.Label(cur_frame, text="Акт. мощность P%:", style='Header.TLabel').grid(row=1, column=0, sticky='w', padx=5, pady=3)
        self.load_p_read_lbl = ttk.Label(cur_frame, text="---", style='Value.TLabel', width=30)
        self.load_p_read_lbl.grid(row=1, column=1, sticky='w', padx=10, pady=3)

        ttk.Label(cur_frame, text="Реакт. мощность Q%:", style='Header.TLabel').grid(row=2, column=0, sticky='w', padx=5, pady=3)
        self.load_q_read_lbl = ttk.Label(cur_frame, text="---", style='Value.TLabel', width=30)
        self.load_q_read_lbl.grid(row=2, column=1, sticky='w', padx=10, pady=3)

        ttk.Button(cur_frame, text="🔄 Прочитать", command=self.read_load_settings, width=14).grid(
            row=0, column=2, rowspan=3, padx=20, pady=5)

        # === Mode Selection ===
        mode_frame = ttk.LabelFrame(load_scroll, text="  Выбор режима нагрузки (регистр 4351)  ", padding=10)
        mode_frame.pack(fill=tk.X, padx=10, pady=5)

        self.load_mode_var = tk.IntVar(value=0)

        modes = [
            (0, "Gen Control Mode — управление мощностью генератора",
             "Задаёт процент от номинальной мощности генератора.\n"
             "ШПР регулирует GOV/AVR генератора, чтобы он выдавал\n"
             "заданный % мощности. Остальное берёт сеть."),
            (1, "Mains Control Mode — управление пиковой срезкой сети",
             "Задаёт процент срезки пиковой нагрузки сети.\n"
             "Генератор покрывает пиковую нагрузку, снижая\n"
             "потребление от сети на заданный %."),
            (2, "Load Reception — приём нагрузки",
             "Режим приёма нагрузки. Генератор принимает\n"
             "на себя всю нагрузку при переключении."),
        ]

        for val, text, tip in modes:
            rb = ttk.Radiobutton(mode_frame, text=text, variable=self.load_mode_var, value=val)
            rb.pack(anchor='w', pady=3, padx=10)
            self._create_tooltip(rb, tip)

        ttk.Button(mode_frame, text="📤 Записать режим", command=self.write_load_mode,
                   width=18).pack(pady=8)

        # === Active Power Percentage ===
        p_frame = ttk.LabelFrame(load_scroll,
            text="  Активная мощность P% (регистр 4352)  ", padding=10)
        p_frame.pack(fill=tk.X, padx=10, pady=5)

        p_inner = ttk.Frame(p_frame)
        p_inner.pack(fill=tk.X)

        ttk.Label(p_inner, text="0%", font=('Consolas', 9)).pack(side=tk.LEFT, padx=5)

        self.load_p_var = tk.DoubleVar(value=0.0)
        self.load_p_scale = ttk.Scale(p_inner, from_=0, to=100, orient=tk.HORIZONTAL,
                                       variable=self.load_p_var, command=self._update_p_label)
        self.load_p_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        ttk.Label(p_inner, text="100%", font=('Consolas', 9)).pack(side=tk.LEFT, padx=5)

        p_val_frame = ttk.Frame(p_frame)
        p_val_frame.pack(fill=tk.X, pady=5)

        ttk.Label(p_val_frame, text="Точное значение (%):").pack(side=tk.LEFT, padx=5)
        self.load_p_entry_var = tk.StringVar(value="0.0")
        p_entry = ttk.Entry(p_val_frame, textvariable=self.load_p_entry_var, width=8, font=('Consolas', 11))
        p_entry.pack(side=tk.LEFT, padx=5)

        self.load_p_display = ttk.Label(p_val_frame, text="= значение регистра: 0",
                                         font=('Consolas', 10), foreground='#666')
        self.load_p_display.pack(side=tk.LEFT, padx=10)

        ttk.Button(p_val_frame, text="📤 Записать P%", command=self.write_load_p,
                   width=16).pack(side=tk.LEFT, padx=15)

        # === Reactive Power Percentage ===
        q_frame = ttk.LabelFrame(load_scroll,
            text="  Реактивная мощность Q% (регистр 4354)  ", padding=10)
        q_frame.pack(fill=tk.X, padx=10, pady=5)

        q_inner = ttk.Frame(q_frame)
        q_inner.pack(fill=tk.X)

        ttk.Label(q_inner, text="0%", font=('Consolas', 9)).pack(side=tk.LEFT, padx=5)

        self.load_q_var = tk.DoubleVar(value=0.0)
        self.load_q_scale = ttk.Scale(q_inner, from_=0, to=100, orient=tk.HORIZONTAL,
                                       variable=self.load_q_var, command=self._update_q_label)
        self.load_q_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        ttk.Label(q_inner, text="100%", font=('Consolas', 9)).pack(side=tk.LEFT, padx=5)

        q_val_frame = ttk.Frame(q_frame)
        q_val_frame.pack(fill=tk.X, pady=5)

        ttk.Label(q_val_frame, text="Точное значение (%):").pack(side=tk.LEFT, padx=5)
        self.load_q_entry_var = tk.StringVar(value="0.0")
        q_entry = ttk.Entry(q_val_frame, textvariable=self.load_q_entry_var, width=8, font=('Consolas', 11))
        q_entry.pack(side=tk.LEFT, padx=5)

        self.load_q_display = ttk.Label(q_val_frame, text="= значение регистра: 0",
                                         font=('Consolas', 10), foreground='#666')
        self.load_q_display.pack(side=tk.LEFT, padx=10)

        ttk.Button(q_val_frame, text="📤 Записать Q%", command=self.write_load_q,
                   width=16).pack(side=tk.LEFT, padx=15)

        # === PRESETS ===
        preset_frame = ttk.LabelFrame(load_scroll,
            text="  🎯 Пресеты (быстрые настройки)  ", padding=10)
        preset_frame.pack(fill=tk.X, padx=10, pady=8)

        # Backup section
        bak_row = ttk.Frame(preset_frame)
        bak_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(bak_row, text="Резервная копия:", style='Header.TLabel').pack(side=tk.LEFT, padx=5)

        ttk.Button(bak_row, text="💾 Сохранить текущие настройки",
                   command=self.backup_load_settings, width=28).pack(side=tk.LEFT, padx=8)

        ttk.Button(bak_row, text="♻ Восстановить из бекапа",
                   command=self.restore_load_settings, width=24).pack(side=tk.LEFT, padx=8)

        self.backup_status_lbl = ttk.Label(bak_row, text="(бекап не создан)", font=('Segoe UI', 9),
                                            foreground='#999')
        self.backup_status_lbl.pack(side=tk.LEFT, padx=10)

        # Separator
        ttk.Separator(preset_frame, orient='horizontal').pack(fill=tk.X, pady=8)

        # Preset buttons
        ttk.Label(preset_frame, text="Выберите пресет — перед применением автоматически создаётся бекап текущих настроек:",
                  font=('Segoe UI', 9)).pack(anchor='w', padx=5, pady=(0, 8))

        presets_grid = ttk.Frame(preset_frame)
        presets_grid.pack(fill=tk.X)

        # Define presets: (name, color, mode, p%, q%, description)
        self.presets = [
            {
                "name": "🔋 Приоритет генератора",
                "color": "#228B22",
                "mode": 0, "p": 100.0, "q": 100.0,
                "desc": "Генератор выдаёт максимум (100% P и Q).\n"
                        "Сеть подхватывает только то, что генератор\n"
                        "не может выдать. При пропадании сети —\n"
                        "генератор продолжает работать.\n"
                        "Для: основное питание от генератора."
            },
            {
                "name": "⚡ Приоритет сети",
                "color": "#0066CC",
                "mode": 1, "p": 0.0, "q": 0.0,
                "desc": "Генератор не берёт нагрузку от сети (0%).\n"
                        "Вся мощность идёт от сети, генератор в\n"
                        "горячем резерве. Готов подхватить при\n"
                        "пропадании сети.\n"
                        "Для: сеть основная, генератор — резерв."
            },
            {
                "name": "📊 Срезка пиков 30%",
                "color": "#FF8C00",
                "mode": 1, "p": 30.0, "q": 20.0,
                "desc": "Генератор срезает 30% пиковой активной\n"
                        "и 20% реактивной нагрузки сети.\n"
                        "Снижает платёж за пиковую мощность.\n"
                        "Для: peak shaving, экономия на тарифе."
            },
            {
                "name": "📊 Срезка пиков 50%",
                "color": "#CC6600",
                "mode": 1, "p": 50.0, "q": 30.0,
                "desc": "Генератор срезает 50% пиковой активной\n"
                        "и 30% реактивной нагрузки сети.\n"
                        "Агрессивная срезка для больших пиков.\n"
                        "Для: высокий тариф за пиковую мощность."
            },
            {
                "name": "⚖ 50/50 генератор-сеть",
                "color": "#6B3A8A",
                "mode": 0, "p": 50.0, "q": 50.0,
                "desc": "Генератор выдаёт 50% от номинала.\n"
                        "Нагрузка делится примерно поровну\n"
                        "между генератором и сетью.\n"
                        "Для: равномерная нагрузка, обкатка ГУ."
            },
            {
                "name": "🔧 Минимум генератора",
                "color": "#555555",
                "mode": 0, "p": 10.0, "q": 10.0,
                "desc": "Генератор на минимальной нагрузке (10%).\n"
                        "Поддерживает рабочий режим без\n"
                        "существенной нагрузки. Сеть покрывает\n"
                        "почти всё.\n"
                        "Для: прогрев, тестирование, холостой режим."
            },
        ]

        for i, preset in enumerate(self.presets):
            r, c = divmod(i, 3)
            pf = ttk.Frame(presets_grid)
            pf.grid(row=r, column=c, padx=6, pady=4, sticky='nsew')
            presets_grid.columnconfigure(c, weight=1)

            btn = tk.Button(pf, text=preset["name"], width=24, height=2,
                           font=('Segoe UI', 10, 'bold'), fg='white', bg=preset["color"],
                           activebackground=preset["color"], relief=tk.RAISED,
                           command=lambda p=preset: self.apply_preset(p))
            btn.pack(fill=tk.X)
            self._create_tooltip(btn, preset["desc"])

            # Compact info under button
            mode_names = {0: "Gen Control", 1: "Mains Control", 2: "Load Reception"}
            info = f"Режим: {mode_names[preset['mode']]}  |  P={preset['p']:.0f}%  Q={preset['q']:.0f}%"
            ttk.Label(pf, text=info, font=('Consolas', 8), foreground='#666').pack()

        # Backup storage
        self._load_backup = None

        # === Explanation ===
        help_frame = ttk.LabelFrame(load_scroll,
            text="  📖 Как пользоваться распределением нагрузки  ", padding=12)
        help_frame.pack(fill=tk.X, padx=10, pady=10)

        help_text = (
            "HGM9560 (ШПР) управляет распределением нагрузки между генератором и сетью.\n"
            "Это нужно при параллельной работе генератора с сетью.\n\n"

            "━━━ РЕЖИМ 0: Gen Control Mode (Управление генератором) ━━━\n"
            "Вы задаёте, какой процент от номинальной мощности должен выдавать генератор.\n"
            "Пример: генератор 100 кВт, задали P% = 50% → генератор выдаёт 50 кВт,\n"
            "остальную нагрузку покрывает сеть.\n"
            "Применение: стабильная базовая нагрузка от генератора, пики берёт сеть.\n\n"

            "━━━ РЕЖИМ 1: Mains Control Mode (Срезка пиков сети) ━━━\n"
            "Вы задаёте, на сколько процентов генератор должен снизить пиковое потребление от сети.\n"
            "Пример: пиковая нагрузка 200 кВт, задали P% = 30% → генератор покрывает 60 кВт\n"
            "от пиковой нагрузки, сеть потребляет только 140 кВт.\n"
            "Применение: снижение платы за мощность (peak shaving), защита от штрафов.\n\n"

            "━━━ РЕЖИМ 2: Load Reception (Приём нагрузки) ━━━\n"
            "Генератор принимает на себя нагрузку при переключении.\n"
            "Используется при переходных процессах.\n\n"

            "━━━ Активная мощность P% ━━━\n"
            "Регулирует активную составляющую (кВт) — реальную потребляемую мощность.\n"
            "Диапазон: 0.0% – 100.0%  (в регистр записывается 0–1000).\n\n"

            "━━━ Реактивная мощность Q% ━━━\n"
            "Регулирует реактивную составляющую (кВАр) — для компенсации cosφ.\n"
            "Диапазон: 0.0% – 100.0%  (в регистр записывается 0–1000).\n\n"

            "━━━ Порядок действий ━━━\n"
            "1. Нажмите «Прочитать» чтобы увидеть текущие настройки\n"
            "2. Выберите режим нагрузки и нажмите «Записать режим»\n"
            "3. Установите нужный P% и нажмите «Записать P%»\n"
            "4. При необходимости установите Q% и нажмите «Записать Q%»\n"
            "5. Контроллер применит настройки автоматически\n\n"

            "⚠  Изменение параметров влияет на реальное распределение электрической\n"
            "    нагрузки между генератором и сетью. Убедитесь, что генератор способен\n"
            "    выдать заданную мощность и параллельная работа настроена корректно."
        )
        help_label = ttk.Label(help_frame, text=help_text, font=('Segoe UI', 9),
                               justify=tk.LEFT, wraplength=950)
        help_label.pack(anchor='w')

    def _update_p_label(self, val):
        """Update P% display when slider moves"""
        pct = float(val)
        reg_val = int(pct * 10)
        self.load_p_entry_var.set(f"{pct:.1f}")
        self.load_p_display.config(text=f"= значение регистра: {reg_val}")

    def _update_q_label(self, val):
        """Update Q% display when slider moves"""
        pct = float(val)
        reg_val = int(pct * 10)
        self.load_q_entry_var.set(f"{pct:.1f}")
        self.load_q_display.config(text=f"= значение регистра: {reg_val}")

    # ---- Backup / Restore / Presets ----
    def backup_load_settings(self):
        """Read current load settings and save as backup"""
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        def _do():
            try:
                slave = int(self.slave_var.get())
                regs = self.conn.read_registers(slave, 4351, 4)
                backup = {
                    "mode": regs[0],
                    "p_reg": regs[1],
                    "q_reg": regs[3],
                    "p_pct": regs[1] * 0.1,
                    "q_pct": regs[3] * 0.1,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                self._load_backup = backup

                mode_names = {0: "Gen Control", 1: "Mains Control", 2: "Load Reception"}
                mode_str = mode_names.get(backup["mode"], f"Unknown({backup['mode']})")
                status = f"✅ Бекап: {mode_str}, P={backup['p_pct']:.1f}%, Q={backup['q_pct']:.1f}% ({backup['timestamp']})"

                self.root.after(0, lambda: (
                    self.backup_status_lbl.config(text=status, foreground='#228B22'),
                ))
                self.log(f"Backup saved: mode={backup['mode']}, P={backup['p_pct']:.1f}%, Q={backup['q_pct']:.1f}%")

                # Also save to file
                self._save_backup_to_file(backup)

            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось прочитать настройки: {e}"))
                self.log(f"Backup error: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def _save_backup_to_file(self, backup):
        """Save backup to JSON file next to the script"""
        import json, os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hgm9560_load_backup.json")
        try:
            # Load existing history or start fresh
            history = []
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        history = data
                    else:
                        history = [data]

            history.append(backup)
            # Keep last 20 backups
            history = history[-20:]

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            self.log(f"Backup saved to file: {path}")
        except Exception as e:
            self.log(f"Warning: could not save backup to file: {e}")

    def _load_backup_from_file(self):
        """Load last backup from JSON file"""
        import json, os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hgm9560_load_backup.json")
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        return data[-1]
                    elif isinstance(data, dict):
                        return data
        except Exception as e:
            self.log(f"Warning: could not load backup from file: {e}")
        return None

    def restore_load_settings(self):
        """Restore load settings from backup"""
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        backup = self._load_backup
        if backup is None:
            # Try loading from file
            backup = self._load_backup_from_file()
            if backup is None:
                messagebox.showwarning("Внимание",
                    "Бекап не найден!\n"
                    "Сначала нажмите «Сохранить текущие настройки»\n"
                    "или ранее сохранённый файл hgm9560_load_backup.json отсутствует.")
                return
            self._load_backup = backup

        mode_names = {0: "Gen Control", 1: "Mains Control", 2: "Load Reception"}
        mode_str = mode_names.get(backup["mode"], f"Unknown({backup['mode']})")

        msg = (f"Восстановить настройки из бекапа?\n\n"
               f"Режим: {mode_str} ({backup['mode']})\n"
               f"Активная мощность P: {backup['p_pct']:.1f}%\n"
               f"Реактивная мощность Q: {backup['q_pct']:.1f}%\n"
               f"Время бекапа: {backup.get('timestamp', 'N/A')}")

        if not messagebox.askyesno("Восстановление из бекапа", msg):
            return

        def _do():
            try:
                slave = int(self.slave_var.get())
                errors = []

                # Write mode
                ok = self.conn.write_register(slave, 4351, backup["mode"])
                if not ok: errors.append("Mode")
                time.sleep(0.15)

                # Write P%
                ok = self.conn.write_register(slave, 4352, backup["p_reg"])
                if not ok: errors.append("P%")
                time.sleep(0.15)

                # Write Q%
                ok = self.conn.write_register(slave, 4354, backup["q_reg"])
                if not ok: errors.append("Q%")

                if errors:
                    self.root.after(0, lambda: messagebox.showwarning("Частичная ошибка",
                        f"Не удалось записать: {', '.join(errors)}"))
                    self.log(f"Restore partial fail: {errors}")
                else:
                    # Update UI
                    self.root.after(0, lambda: (
                        self.load_mode_var.set(backup["mode"]),
                        self.load_p_var.set(backup["p_pct"]),
                        self.load_p_entry_var.set(f"{backup['p_pct']:.1f}"),
                        self.load_p_display.config(text=f"= значение регистра: {backup['p_reg']}"),
                        self.load_q_var.set(backup["q_pct"]),
                        self.load_q_entry_var.set(f"{backup['q_pct']:.1f}"),
                        self.load_q_display.config(text=f"= значение регистра: {backup['q_reg']}"),
                        messagebox.showinfo("Успех",
                            f"Настройки восстановлены из бекапа!\n"
                            f"Режим: {mode_str}, P={backup['p_pct']:.1f}%, Q={backup['q_pct']:.1f}%"),
                    ))
                    self.log(f"Restore OK: mode={backup['mode']}, P={backup['p_pct']:.1f}%, Q={backup['q_pct']:.1f}%")

            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))
                self.log(f"Restore error: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def apply_preset(self, preset):
        """Apply a preset with automatic backup first"""
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        mode_names = {0: "Gen Control", 1: "Mains Control", 2: "Load Reception"}

        msg = (f"Применить пресет «{preset['name']}»?\n\n"
               f"Режим: {mode_names[preset['mode']]}\n"
               f"Активная мощность P: {preset['p']:.1f}%\n"
               f"Реактивная мощность Q: {preset['q']:.1f}%\n\n"
               f"⚠ Текущие настройки будут автоматически сохранены в бекап.")

        if not messagebox.askyesno("Применение пресета", msg):
            return

        def _do():
            try:
                slave = int(self.slave_var.get())

                # STEP 1: Auto-backup current settings
                self.log("Preset: backing up current settings...")
                try:
                    regs = self.conn.read_registers(slave, 4351, 4)
                    backup = {
                        "mode": regs[0],
                        "p_reg": regs[1],
                        "q_reg": regs[3],
                        "p_pct": regs[1] * 0.1,
                        "q_pct": regs[3] * 0.1,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "reason": f"Auto-backup before preset: {preset['name']}"
                    }
                    self._load_backup = backup
                    self._save_backup_to_file(backup)

                    old_mode = mode_names.get(backup["mode"], "?")
                    self.root.after(0, lambda: self.backup_status_lbl.config(
                        text=f"✅ Авто-бекап: {old_mode}, P={backup['p_pct']:.1f}%, Q={backup['q_pct']:.1f}% ({backup['timestamp']})",
                        foreground='#228B22'))
                    self.log(f"Auto-backup saved: mode={backup['mode']}, P={backup['p_pct']:.1f}%, Q={backup['q_pct']:.1f}%")
                    time.sleep(0.15)
                except Exception as e:
                    self.log(f"Warning: auto-backup failed: {e}")
                    # Ask user if they want to continue without backup
                    proceed = [False]
                    def ask():
                        proceed[0] = messagebox.askyesno("Внимание",
                            f"Не удалось создать бекап: {e}\n\nПродолжить применение пресета без бекапа?")
                    self.root.after(0, ask)
                    time.sleep(1)  # wait for dialog
                    if not proceed[0]:
                        return

                # STEP 2: Write preset values
                errors = []

                ok = self.conn.write_register(slave, 4351, preset["mode"])
                if not ok: errors.append("Mode")
                self.log(f"Preset write mode={preset['mode']}: {'OK' if ok else 'FAIL'}")
                time.sleep(0.15)

                p_reg = int(preset["p"] * 10)
                ok = self.conn.write_register(slave, 4352, p_reg)
                if not ok: errors.append("P%")
                self.log(f"Preset write P={preset['p']:.1f}% (reg={p_reg}): {'OK' if ok else 'FAIL'}")
                time.sleep(0.15)

                q_reg = int(preset["q"] * 10)
                ok = self.conn.write_register(slave, 4354, q_reg)
                if not ok: errors.append("Q%")
                self.log(f"Preset write Q={preset['q']:.1f}% (reg={q_reg}): {'OK' if ok else 'FAIL'}")

                if errors:
                    self.root.after(0, lambda: messagebox.showwarning("Частичная ошибка",
                        f"Пресет применён частично.\nНе удалось записать: {', '.join(errors)}"))
                else:
                    # Update UI to match preset
                    self.root.after(0, lambda: (
                        self.load_mode_var.set(preset["mode"]),
                        self.load_p_var.set(preset["p"]),
                        self.load_p_entry_var.set(f"{preset['p']:.1f}"),
                        self.load_p_display.config(text=f"= значение регистра: {p_reg}"),
                        self.load_q_var.set(preset["q"]),
                        self.load_q_entry_var.set(f"{preset['q']:.1f}"),
                        self.load_q_display.config(text=f"= значение регистра: {q_reg}"),
                        self.load_mode_read_lbl.config(text=f"{preset['mode']} — {mode_names[preset['mode']]}"),
                        self.load_p_read_lbl.config(text=f"{preset['p']:.1f}% (регистр: {p_reg})"),
                        self.load_q_read_lbl.config(text=f"{preset['q']:.1f}% (регистр: {q_reg})"),
                        messagebox.showinfo("Успех",
                            f"Пресет «{preset['name']}» применён!\n\n"
                            f"Режим: {mode_names[preset['mode']]}\n"
                            f"P = {preset['p']:.1f}%,  Q = {preset['q']:.1f}%\n\n"
                            f"Предыдущие настройки сохранены в бекап."),
                    ))
                    self.log(f"Preset '{preset['name']}' applied successfully")

            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))
                self.log(f"Preset apply error: {e}")

        threading.Thread(target=_do, daemon=True).start()
    def read_load_settings(self):
        """Read current load mode, P% and Q% from registers 4351-4354"""
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        def _do():
            try:
                slave = int(self.slave_var.get())
                regs = self.conn.read_registers(slave, 4351, 4)
                mode = regs[0]
                p_pct = regs[1] * 0.1  # 0-1000 -> 0.0-100.0%
                # reg[2] is 4353 (skipped/reserved)
                q_pct = regs[3] * 0.1  # 4354

                mode_names = {
                    0: "0 — Gen Control (мощность генератора)",
                    1: "1 — Mains Control (срезка пиков сети)",
                    2: "2 — Load Reception (приём нагрузки)"
                }
                mode_str = mode_names.get(mode, f"Unknown ({mode})")

                self.root.after(0, lambda: (
                    self.load_mode_read_lbl.config(text=mode_str),
                    self.load_p_read_lbl.config(text=f"{p_pct:.1f}% (регистр: {regs[1]})"),
                    self.load_q_read_lbl.config(text=f"{q_pct:.1f}% (регистр: {regs[3]})"),
                    self.load_mode_var.set(mode),
                    self.load_p_var.set(p_pct),
                    self.load_p_entry_var.set(f"{p_pct:.1f}"),
                    self.load_p_display.config(text=f"= значение регистра: {regs[1]}"),
                    self.load_q_var.set(q_pct),
                    self.load_q_entry_var.set(f"{q_pct:.1f}"),
                    self.load_q_display.config(text=f"= значение регистра: {regs[3]}"),
                ))
                self.log(f"Load settings: mode={mode}, P={p_pct:.1f}%, Q={q_pct:.1f}%")
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Ошибка", f"Ошибка чтения: {e}"))
                self.log(f"Ошибка чтения load settings: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def write_load_mode(self):
        """Write load mode to register 4351"""
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        mode = self.load_mode_var.get()
        mode_names = {0: "Gen Control", 1: "Mains Control", 2: "Load Reception"}
        if not messagebox.askyesno("Подтверждение",
                f"Установить режим нагрузки: {mode_names.get(mode, '?')} ({mode})?"):
            return

        def _do():
            try:
                slave = int(self.slave_var.get())
                ok = self.conn.write_register(slave, 4351, mode)
                self.log(f"Load Mode -> {mode} ({mode_names.get(mode)}): {'OK' if ok else 'FAIL'}")
                if ok:
                    self.root.after(0, lambda: messagebox.showinfo("Успех",
                        f"Режим нагрузки установлен: {mode_names.get(mode)}"))
            except Exception as e:
                self.log(f"Ошибка записи Load Mode: {e}")
                self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))

        threading.Thread(target=_do, daemon=True).start()

    def write_load_p(self):
        """Write active power percentage to register 4352"""
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        try:
            pct = float(self.load_p_entry_var.get())
        except ValueError:
            messagebox.showwarning("Внимание", "Введите числовое значение P%!")
            return

        if pct < 0 or pct > 100:
            messagebox.showwarning("Внимание", "P% должен быть в диапазоне 0.0 – 100.0!")
            return

        reg_val = int(pct * 10)  # 0.0-100.0% -> 0-1000

        if not messagebox.askyesno("Подтверждение",
                f"Установить активную мощность P = {pct:.1f}%?\n"
                f"(значение регистра 4352 = {reg_val})"):
            return

        def _do():
            try:
                slave = int(self.slave_var.get())
                ok = self.conn.write_register(slave, 4352, reg_val)
                self.log(f"Load P% -> {pct:.1f}% (reg={reg_val}): {'OK' if ok else 'FAIL'}")
                if ok:
                    self.root.after(0, lambda: messagebox.showinfo("Успех",
                        f"Активная мощность P = {pct:.1f}% записана"))
            except Exception as e:
                self.log(f"Ошибка записи Load P%: {e}")
                self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))

        threading.Thread(target=_do, daemon=True).start()

    def write_load_q(self):
        """Write reactive power percentage to register 4354"""
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        try:
            pct = float(self.load_q_entry_var.get())
        except ValueError:
            messagebox.showwarning("Внимание", "Введите числовое значение Q%!")
            return

        if pct < 0 or pct > 100:
            messagebox.showwarning("Внимание", "Q% должен быть в диапазоне 0.0 – 100.0!")
            return

        reg_val = int(pct * 10)

        if not messagebox.askyesno("Подтверждение",
                f"Установить реактивную мощность Q = {pct:.1f}%?\n"
                f"(значение регистра 4354 = {reg_val})"):
            return

        def _do():
            try:
                slave = int(self.slave_var.get())
                ok = self.conn.write_register(slave, 4354, reg_val)
                self.log(f"Load Q% -> {pct:.1f}% (reg={reg_val}): {'OK' if ok else 'FAIL'}")
                if ok:
                    self.root.after(0, lambda: messagebox.showinfo("Успех",
                        f"Реактивная мощность Q = {pct:.1f}% записана"))
            except Exception as e:
                self.log(f"Ошибка записи Load Q%: {e}")
                self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))

        threading.Thread(target=_do, daemon=True).start()

    # ---- Tooltip helper ----
    def _create_tooltip(self, widget, text):
        """Create a hover tooltip for a widget"""
        tip_window = [None]

        def show_tip(event):
            if tip_window[0]:
                return
            x = event.x_root + 15
            y = event.y_root + 10
            tw = tk.Toplevel(widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tw.configure(bg='#FFFFDD')
            label = tk.Label(tw, text=text, justify=tk.LEFT,
                           background='#FFFFDD', foreground='#333333',
                           relief=tk.SOLID, borderwidth=1,
                           font=('Segoe UI', 9), padx=8, pady=5)
            label.pack()
            tip_window[0] = tw

        def hide_tip(event):
            if tip_window[0]:
                tip_window[0].destroy()
                tip_window[0] = None

        widget.bind('<Enter>', show_tip)
        widget.bind('<Leave>', hide_tip)

    # ---- Tab 4: Log ----
    def _build_log_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  📋 Лог  ")

        btn_f = ttk.Frame(tab)
        btn_f.pack(fill=tk.X)
        ttk.Button(btn_f, text="Очистить лог", command=self.clear_log).pack(side=tk.RIGHT, padx=5)

        self.log_text = scrolledtext.ScrolledText(tab, height=30, font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=5)

    # --------------------------------------------------------------------------
    # Logging
    # --------------------------------------------------------------------------
    def log(self, msg, tag=None):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {msg}\n"
        try:
            self.log_text.insert(tk.END, line)
            self.log_text.see(tk.END)
        except:
            pass

    def clear_log(self):
        self.log_text.delete('1.0', tk.END)

    # --------------------------------------------------------------------------
    # Connection
    # --------------------------------------------------------------------------
    def toggle_connection(self):
        if self.conn.is_connected():
            self.polling = False
            time.sleep(0.3)
            self.conn.disconnect()
            self.connect_btn.config(text="Подключить")
            self.conn_status.config(text="● Отключено", style='Disconnected.TLabel')
            self.poll_status.config(text="Опрос остановлен", style='Disconnected.TLabel')
            self.log("Отключено от адаптера")
        else:
            host = self.ip_var.get().strip()
            port = int(self.port_var.get().strip())
            timeout = float(self.timeout_var.get().strip())
            self.conn.timeout = timeout
            try:
                self.conn.connect(host, port)
                self.connect_btn.config(text="Отключить")
                self.conn_status.config(text=f"● Подключено ({host}:{port})", style='Connected.TLabel')
                self.log(f"Подключено к {host}:{port}")
            except Exception as e:
                messagebox.showerror("Ошибка подключения", str(e))
                self.log(f"Ошибка: {e}")

    # --------------------------------------------------------------------------
    # Polling
    # --------------------------------------------------------------------------
    def toggle_polling(self):
        if self.polling:
            self.polling = False
            self.poll_btn.config(text="▶ Начать опрос")
            self.poll_status.config(text="Опрос остановлен", style='Disconnected.TLabel')
        else:
            if not self.conn.is_connected():
                messagebox.showwarning("Внимание", "Сначала подключитесь к адаптеру!")
                return
            self.polling = True
            self.poll_btn.config(text="⏸ Остановить опрос")
            self.poll_status.config(text="Опрос запущен", style='Connected.TLabel')
            self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self.poll_thread.start()

    def _poll_loop(self):
        while self.polling and self.conn.is_connected():
            try:
                self._read_all_data()
                self.root.after(0, lambda: self.last_update.config(
                    text=f"Обновлено: {datetime.now().strftime('%H:%M:%S')}"))
            except Exception as e:
                self.root.after(0, lambda e=e: self.log(f"Ошибка опроса: {e}"))
                self.root.after(0, lambda: self.poll_status.config(
                    text="Ошибка связи!", style='Alarm.TLabel'))
                # Try to reconnect
                time.sleep(1)
                try:
                    host = self.ip_var.get().strip()
                    port = int(self.port_var.get().strip())
                    self.conn.connect(host, port)
                    self.root.after(0, lambda: self.log("Переподключено"))
                    self.root.after(0, lambda: self.poll_status.config(
                        text="Опрос запущен", style='Connected.TLabel'))
                except:
                    pass

            try:
                interval = float(self.interval_var.get())
            except:
                interval = 2.0
            time.sleep(interval)

    def _read_all_data(self):
        slave = int(self.slave_var.get())

        # --- Block 1: Status registers 0000-0002 (mode, alarms) ---
        regs = self.conn.read_registers(slave, 0, 3)
        mode_word = regs[0]
        mode_str = ""
        for bit, name in MODE_BITS.items():
            if mode_word & (1 << bit):
                mode_str = name
        alarm_str = ""
        for bit, name in ALARM_BITS_0.items():
            if mode_word & (1 << bit):
                alarm_str += name + ", "
        alarm_str = alarm_str.rstrip(", ") or "Нет"

        self.root.after(0, lambda: self.mon_labels["mode"].config(text=mode_str or "---"))
        self.root.after(0, lambda: self.mon_labels["alarms"].config(
            text=alarm_str,
            style='Alarm.TLabel' if alarm_str != "Нет" else 'Value.TLabel'))

        time.sleep(0.05)

        # --- Block 2: Mains Voltage 0055-0064 ---
        regs = self.conn.read_registers(slave, 55, 10)
        mains_uab = regs[0]
        mains_ubc = regs[1]
        mains_uca = regs[2]
        mains_ua = regs[3]
        mains_ub = regs[4]
        mains_uc = regs[5]
        # 6,7,8 - phases
        mains_freq = regs[9] * 0.01

        self.root.after(0, lambda: self.mon_labels["mains_uab"].config(text=f"{mains_uab} V"))
        self.root.after(0, lambda: self.mon_labels["mains_ubc"].config(text=f"{mains_ubc} V"))
        self.root.after(0, lambda: self.mon_labels["mains_uca"].config(text=f"{mains_uca} V"))
        self.root.after(0, lambda: self.mon_labels["mains_ua"].config(text=f"{mains_ua} V"))
        self.root.after(0, lambda: self.mon_labels["mains_ub"].config(text=f"{mains_ub} V"))
        self.root.after(0, lambda: self.mon_labels["mains_uc"].config(text=f"{mains_uc} V"))
        self.root.after(0, lambda: self.mon_labels["mains_freq"].config(text=f"{mains_freq:.2f} Hz"))

        time.sleep(0.05)

        # --- Block 3: Busbar Voltage 0075-0084 ---
        regs = self.conn.read_registers(slave, 75, 10)
        busbar_uab = regs[0]
        busbar_ubc = regs[1]
        busbar_uca = regs[2]
        busbar_ua = regs[3]
        busbar_ub = regs[4]
        busbar_uc = regs[5]
        busbar_freq = regs[9] * 0.01

        self.root.after(0, lambda: self.mon_labels["busbar_uab"].config(text=f"{busbar_uab} V"))
        self.root.after(0, lambda: self.mon_labels["busbar_ubc"].config(text=f"{busbar_ubc} V"))
        self.root.after(0, lambda: self.mon_labels["busbar_uca"].config(text=f"{busbar_uca} V"))
        self.root.after(0, lambda: self.mon_labels["busbar_ua"].config(text=f"{busbar_ua} V"))
        self.root.after(0, lambda: self.mon_labels["busbar_ub"].config(text=f"{busbar_ub} V"))
        self.root.after(0, lambda: self.mon_labels["busbar_uc"].config(text=f"{busbar_uc} V"))
        self.root.after(0, lambda: self.mon_labels["busbar_freq"].config(text=f"{busbar_freq:.2f} Hz"))

        time.sleep(0.05)

        # --- Block 4: Mains Current 0095-0097 ---
        regs = self.conn.read_registers(slave, 95, 3)
        mains_ia = regs[0] * 0.1
        mains_ib = regs[1] * 0.1
        mains_ic = regs[2] * 0.1

        self.root.after(0, lambda: self.mon_labels["mains_ia"].config(text=f"{mains_ia:.1f} A"))
        self.root.after(0, lambda: self.mon_labels["mains_ib"].config(text=f"{mains_ib:.1f} A"))
        self.root.after(0, lambda: self.mon_labels["mains_ic"].config(text=f"{mains_ic:.1f} A"))

        time.sleep(0.05)

        # --- Block 5: Mains Total Power 0109-0118 ---
        regs = self.conn.read_registers(slave, 109, 10)
        mains_total_p = signed32(regs[0], regs[1]) * 0.1
        # 2-3: Mains A Reactive, 4-5: B, 6-7: C
        mains_total_q = signed32(regs[8], regs[9]) * 0.1

        self.root.after(0, lambda: self.mon_labels["mains_total_p"].config(text=f"{mains_total_p:.1f} kW"))
        self.root.after(0, lambda: self.mon_labels["mains_total_q"].config(text=f"{mains_total_q:.1f} kvar"))

        time.sleep(0.05)

        # --- Block 6: Busbar current + Battery + Power + Status ---
        regs = self.conn.read_registers(slave, 134, 12)
        busbar_current = regs[0] * 0.1  # 0134
        # 0135-0141 reserved
        battery_v = regs[8] * 0.1  # 0142

        self.root.after(0, lambda: self.mon_labels["busbar_current"].config(text=f"{busbar_current:.1f} A"))
        self.root.after(0, lambda: self.mon_labels["battery_v"].config(text=f"{battery_v:.1f} V"))

        time.sleep(0.05)

        # --- Block 7: Busbar power + switch statuses 0182-0198 ---
        regs = self.conn.read_registers(slave, 182, 17)
        busbar_p = signed32(regs[0], regs[1]) * 0.1     # 0182-0183
        busbar_q = signed32(regs[2], regs[3]) * 0.1     # 0184-0185
        busbar_sw = regs[11]      # 0193
        mains_st = regs[13]       # 0195
        mains_sw = regs[15]       # 0197

        self.root.after(0, lambda: self.mon_labels["busbar_p"].config(text=f"{busbar_p:.1f} kW"))
        self.root.after(0, lambda: self.mon_labels["busbar_q"].config(text=f"{busbar_q:.1f} kvar"))

        genset_st = "---"  # HGM9560 genset status is in register 0040 area
        busbar_sw_str = SWITCH_STATUS.get(busbar_sw, f"Unknown({busbar_sw})")
        mains_st_str = MAINS_STATUS.get(mains_st, f"Unknown({mains_st})")
        mains_sw_str = SWITCH_STATUS.get(mains_sw, f"Unknown({mains_sw})")

        self.root.after(0, lambda: self.mon_labels["busbar_switch"].config(text=busbar_sw_str))
        self.root.after(0, lambda: self.mon_labels["mains_status"].config(text=mains_st_str))
        self.root.after(0, lambda: self.mon_labels["mains_switch"].config(text=mains_sw_str))

        time.sleep(0.05)

        # --- Block 8: Genset status from register 0040-0042 ---
        regs = self.conn.read_registers(slave, 40, 3)
        gs = regs[0]
        genset_status_str = GENSET_STATUS.get(gs, f"Unknown({gs})")
        self.root.after(0, lambda: self.mon_labels["genset_status"].config(text=genset_status_str))

        time.sleep(0.05)

        # --- Block 9: Accumulated Energy 0203-0211 ---
        regs = self.conn.read_registers(slave, 203, 9)
        accum_kwh = signed32(regs[0], regs[1]) * 0.1   # 0203-0204
        accum_kvarh = signed32(regs[2], regs[3]) * 0.1  # 0205-0206
        # 0207-0208: kVAh
        # 0209-0210: reserved
        maint_h = regs[8]  # 0211

        self.root.after(0, lambda: self.mon_labels["accum_kwh"].config(text=f"{accum_kwh:.1f}"))
        self.root.after(0, lambda: self.mon_labels["accum_kvarh"].config(text=f"{accum_kvarh:.1f}"))
        self.root.after(0, lambda: self.mon_labels["maint_hours"].config(text=f"{maint_h}"))

    # --------------------------------------------------------------------------
    # Manual Read/Write
    # --------------------------------------------------------------------------
    def manual_read_registers(self):
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        def _do():
            try:
                addr = int(self.read_addr_var.get())
                count = int(self.read_count_var.get())
                slave = int(self.slave_var.get())
                if count > 120:
                    count = 120
                regs = self.conn.read_registers(slave, addr, count)

                lines = [f"FC 03H | Slave={slave} | Start={addr} | Count={count}\n"]
                lines.append(f"{'Addr':<8}{'Dec':<10}{'Hex':<10}{'Signed':<10}{'Binary':<20}\n")
                lines.append("-" * 58 + "\n")
                for i, v in enumerate(regs):
                    s = signed16(v)
                    lines.append(f"{addr+i:<8}{v:<10}0x{v:04X}{'':>4}{s:<10}{v:016b}\n")

                self.root.after(0, lambda: (
                    self.read_result.delete('1.0', tk.END),
                    self.read_result.insert('1.0', ''.join(lines))
                ))
                self.log(f"Прочитано {count} регистров с адреса {addr}")
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Ошибка чтения", str(e)))
                self.log(f"Ошибка чтения: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def manual_read_coils(self):
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        def _do():
            try:
                addr = int(self.coil_addr_var.get())
                count = int(self.coil_count_var.get())
                slave = int(self.slave_var.get())
                bits = self.conn.read_coils(slave, addr, count)

                lines = [f"FC 01H | Slave={slave} | Start={addr} | Count={count}\n"]
                for i in range(min(count, len(bits))):
                    lines.append(f"  Coil {addr+i:04d} = {bits[i]}\n")

                self.root.after(0, lambda: (
                    self.coil_result.delete('1.0', tk.END),
                    self.coil_result.insert('1.0', ''.join(lines))
                ))
                self.log(f"Прочитано {count} катушек с адреса {addr}")
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Ошибка чтения", str(e)))
                self.log(f"Ошибка чтения катушек: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def manual_write_register(self):
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        addr = int(self.write_addr_var.get())
        # Validate writable range
        if not ((199 <= addr <= 210) or (225 <= addr <= 231) or (4351 <= addr <= 4354)):
            messagebox.showwarning("Внимание",
                f"Адрес {addr} не в допустимом диапазоне записи!\n"
                "Допустимые: 0199–0210, 0225–0231, 4351–4354")
            return

        if not messagebox.askyesno("Подтверждение",
                f"Записать значение {self.write_val_var.get()} в регистр {addr}?"):
            return

        def _do():
            try:
                val = int(self.write_val_var.get())
                slave = int(self.slave_var.get())
                ok = self.conn.write_register(slave, addr, val)
                status = "✅ Записано успешно" if ok else "❌ Ошибка записи"
                self.root.after(0, lambda: self.write_status_lbl.config(text=status))
                self.log(f"FC06 запись: addr={addr}, val={val}, result={'OK' if ok else 'FAIL'}")
            except Exception as e:
                self.root.after(0, lambda: self.write_status_lbl.config(text=f"❌ {e}"))
                self.log(f"Ошибка записи: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def manual_write_coil(self):
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        def _do():
            try:
                addr = int(self.wcoil_addr_var.get())
                val = self.wcoil_val_var.get()
                slave = int(self.slave_var.get())
                ok = self.conn.write_coil(slave, addr, val)
                status = "✅ Записано" if ok else "❌ Ошибка"
                self.root.after(0, lambda: self.wcoil_status_lbl.config(text=status))
                self.log(f"FC05 запись: coil={addr}, val={'ON' if val else 'OFF'}, result={'OK' if ok else 'FAIL'}")
            except Exception as e:
                self.root.after(0, lambda: self.wcoil_status_lbl.config(text=f"❌ {e}"))
                self.log(f"Ошибка записи катушки: {e}")

        threading.Thread(target=_do, daemon=True).start()

    # --------------------------------------------------------------------------
    # Remote Control
    # --------------------------------------------------------------------------
    def send_remote_command(self, key):
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        if key in ("Start", "Stop"):
            if not messagebox.askyesno("Подтверждение",
                    f"Вы уверены, что хотите отправить команду «{key}»?"):
                return

        addr = REMOTE_COILS.get(key)
        if addr is None:
            return

        def _do():
            try:
                slave = int(self.slave_var.get())
                ok = self.conn.write_coil(slave, addr, True)
                self.log(f"Remote command: {key} (coil {addr}) -> {'OK' if ok else 'FAIL'}")
            except Exception as e:
                self.log(f"Ошибка команды {key}: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def send_output_command(self, idx):
        if not self.conn.is_connected():
            messagebox.showwarning("Внимание", "Не подключено!")
            return

        val = self.output_vars[idx].get()
        addr = 0x0013 + (idx - 1)  # Remote Output 1 = coil 0019 (0x0013)

        def _do():
            try:
                slave = int(self.slave_var.get())
                ok = self.conn.write_coil(slave, addr, val)
                self.log(f"Output {idx} -> {'ON' if val else 'OFF'} (coil {addr}) -> {'OK' if ok else 'FAIL'}")
            except Exception as e:
                self.log(f"Ошибка Output {idx}: {e}")

        threading.Thread(target=_do, daemon=True).start()


# ==============================================================================
# Main
# ==============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = HGM9560App(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (
        setattr(app, 'polling', False),
        app.conn.disconnect(),
        root.destroy()
    ))
    root.mainloop()

#!/usr/bin/env python3
"""
CLI test: FC06 write to HGM9560 registers 4351, 4352, 4354.
Uses the SAME socket logic as the reference script hgm9560_modbus_gui (3).py.

Usage:
    python test_fc06_cli.py [--ip 10.11.0.2] [--port 26] [--slave 3]
"""

import socket
import struct
import time
import sys
import argparse


# ===========================================================================
# Modbus RTU helpers — copied verbatim from reference script
# ===========================================================================

def crc16_modbus(data: bytes) -> int:
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
    frame = struct.pack('>BBhH', slave, 0x03, start, count)
    crc = crc16_modbus(frame)
    return frame + struct.pack('<H', crc)


def build_write_register(slave: int, address: int, value: int) -> bytes:
    frame = struct.pack('>BBHH', slave, 0x06, address, value & 0xFFFF)
    crc = crc16_modbus(frame)
    return frame + struct.pack('<H', crc)


def parse_read_registers_response(data: bytes):
    if len(data) < 5:
        return None
    slave, fc, byte_count = struct.unpack('>BBB', data[:3])
    if fc & 0x80:
        return None
    n_regs = byte_count // 2
    values = []
    for i in range(n_regs):
        val = struct.unpack('>H', data[3 + i*2 : 5 + i*2])[0]
        values.append(val)
    return values


# ===========================================================================
# Communication — exact copy from reference script ModbusConnection
# ===========================================================================

class ModbusConnection:
    def __init__(self):
        self.sock = None
        self.timeout = 2.0

    def connect(self, host: str, port: int) -> bool:
        self.disconnect()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((host, port))
        return True

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

    def send_receive(self, request: bytes) -> bytes:
        if not self.sock:
            raise ConnectionError("Not connected")
        # Clear stale data
        self.sock.settimeout(0.1)
        try:
            self.sock.recv(1024)
        except socket.timeout:
            pass
        self.sock.settimeout(self.timeout)

        self.sock.sendall(request)
        time.sleep(0.15)  # inter-frame gap

        response = b''
        self.sock.settimeout(self.timeout)
        while True:
            try:
                chunk = self.sock.recv(256)
                if not chunk:
                    break
                response += chunk
                if len(response) >= 5:
                    if response[1] == 0x03:
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

    def read_registers(self, slave: int, start: int, count: int) -> list:
        req = build_read_registers(slave, start, count)
        resp = self.send_receive(req)
        result = parse_read_registers_response(resp)
        if result is None:
            raise ValueError(f"Invalid response for FC03 @ {start}")
        return result

    def write_register(self, slave: int, address: int, value: int) -> bool:
        req = build_write_register(slave, address, value)
        resp = self.send_receive(req)
        return resp[1] == 0x06


# ===========================================================================
# Test
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="Test FC06 writes to HGM9560")
    parser.add_argument("--ip", default="10.11.0.2")
    parser.add_argument("--port", type=int, default=26)
    parser.add_argument("--slave", type=int, default=3)
    args = parser.parse_args()

    conn = ModbusConnection()
    print(f"=" * 60)
    print(f"HGM9560 FC06 Write Test (reference script logic)")
    print(f"Connecting to {args.ip}:{args.port} slave={args.slave}")
    print(f"=" * 60)

    try:
        conn.connect(args.ip, args.port)
        print("[OK] Connected\n")
    except Exception as e:
        print(f"[FAIL] Connection error: {e}")
        sys.exit(1)

    # ---- Step 1: Read current config ----
    print("--- Step 1: Read current config (FC03 @ 4351, count=4) ---")
    try:
        regs = conn.read_registers(args.slave, 4351, 4)
        mode_orig = regs[0]
        p_orig = regs[1]
        q_orig = regs[3]  # reg[2] = 4353 (reserved)
        print(f"  LoadMode (4351) = {mode_orig}")
        print(f"  P%       (4352) = {p_orig}  ({p_orig * 0.1:.1f}%)")
        print(f"  (4353 reserved)  = {regs[2]}")
        print(f"  Q%       (4354) = {q_orig}  ({q_orig * 0.1:.1f}%)")
        print()
    except Exception as e:
        print(f"  [FAIL] Read error: {e}")
        conn.disconnect()
        sys.exit(1)

    # ---- Step 2: Write test value to P% (4352) ----
    # Change P% by +1 raw unit (0.1%), so it's a minimal change
    test_p = (p_orig + 1) if p_orig < 1000 else (p_orig - 1)
    print(f"--- Step 2: Write test P% = {test_p} ({test_p * 0.1:.1f}%) to reg 4352 ---")
    try:
        time.sleep(0.15)
        ok = conn.write_register(args.slave, 4352, test_p)
        print(f"  FC06 echo check: {'OK' if ok else 'FAIL'}")
    except Exception as e:
        print(f"  [FAIL] Write error: {e}")

    # ---- Step 3: Verify read-back ----
    print(f"\n--- Step 3: Read back config (verify) ---")
    try:
        time.sleep(0.3)  # give controller time to process
        regs2 = conn.read_registers(args.slave, 4351, 4)
        p_new = regs2[1]
        print(f"  LoadMode (4351) = {regs2[0]}")
        print(f"  P%       (4352) = {p_new}  ({p_new * 0.1:.1f}%)")
        print(f"  Q%       (4354) = {regs2[3]}  ({regs2[3] * 0.1:.1f}%)")
        print()
        if p_new == test_p:
            print(f"  *** VERIFY OK: P% changed from {p_orig} to {p_new} ***")
            print(f"  >>> FC06 WORKS for reg 4352 on this controller! <<<")
        else:
            print(f"  *** VERIFY FAIL: P% still {p_new} (expected {test_p}, was {p_orig}) ***")
            print(f"  >>> FC06 echo OK but value NOT saved — firmware issue <<<")
    except Exception as e:
        print(f"  [FAIL] Read error: {e}")

    # ---- Step 4: Write test to reg 225 (controller time — seconds) ----
    print(f"\n--- Step 4: Test FC06 to reg 225 (controller time) ---")
    try:
        time.sleep(0.15)
        regs_time = conn.read_registers(args.slave, 225, 1)
        time_orig = regs_time[0]
        print(f"  Current reg 225 = {time_orig}")
        time_test = (time_orig + 1) % 60
        ok = conn.write_register(args.slave, 225, time_test)
        print(f"  Write {time_test} to reg 225: echo {'OK' if ok else 'FAIL'}")
        time.sleep(0.3)
        regs_time2 = conn.read_registers(args.slave, 225, 1)
        time_new = regs_time2[0]
        print(f"  Read back reg 225 = {time_new}")
        if time_new == time_test:
            print(f"  *** Reg 225 WRITE WORKS (value changed {time_orig} -> {time_new}) ***")
        else:
            print(f"  *** Reg 225 also NOT saved (value {time_new}, expected {time_test}) ***")
            print(f"  (Note: time reg may auto-increment, so small differences are OK)")
    except Exception as e:
        print(f"  [FAIL] Reg 225 test error: {e}")

    # ---- Step 5: Restore original P% ----
    print(f"\n--- Step 5: Restore original P% = {p_orig} ---")
    try:
        time.sleep(0.15)
        ok = conn.write_register(args.slave, 4352, p_orig)
        print(f"  Restore FC06: {'OK' if ok else 'FAIL'}")
        time.sleep(0.3)
        regs3 = conn.read_registers(args.slave, 4352, 1)
        print(f"  Read back: {regs3[0]} (original was {p_orig})")
    except Exception as e:
        print(f"  [FAIL] Restore error: {e}")

    # ---- Done ----
    conn.disconnect()
    print(f"\n{'=' * 60}")
    print("Test complete. Connection closed.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

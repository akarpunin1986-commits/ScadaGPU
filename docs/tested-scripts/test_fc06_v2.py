#!/usr/bin/env python3
"""
Extended FC06/FC16 write test for HGM9560 registers 4351-4354.

Tests:
  A) FC16 (Write Multiple Registers) single reg 4352
  B) FC16 bulk write all 4351-4354 (4 regs)
  C) Password 0318 to reg 199, then FC06 to 4352
  D) Password 0318 to reg 199, then FC16 bulk to 4351-4354

Usage:
    python test_fc06_v2.py [--ip 10.11.0.2] [--port 26] [--slave 3]
"""

import socket
import struct
import time
import sys
import argparse


# ===========================================================================
# Modbus RTU helpers
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
    """FC06 — Write Single Register"""
    frame = struct.pack('>BBHH', slave, 0x06, address, value & 0xFFFF)
    crc = crc16_modbus(frame)
    return frame + struct.pack('<H', crc)


def build_write_multiple_registers(slave: int, address: int, values: list[int]) -> bytes:
    """FC16 (0x10) — Write Multiple Registers"""
    count = len(values)
    byte_count = count * 2
    # Header: slave + FC(0x10) + start_addr(2) + count(2) + byte_count(1)
    frame = struct.pack('>BBHHB', slave, 0x10, address, count, byte_count)
    # Data: each register as big-endian 16-bit
    for v in values:
        frame += struct.pack('>H', v & 0xFFFF)
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
# Communication — same as reference script
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
        time.sleep(0.15)

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
                    elif response[1] == 0x10:
                        # FC16 response: slave + FC + addr(2) + count(2) + CRC(2) = 8 bytes
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
        """FC06"""
        req = build_write_register(slave, address, value)
        resp = self.send_receive(req)
        return resp[1] == 0x06

    def write_multiple_registers(self, slave: int, address: int, values: list[int]) -> bool:
        """FC16"""
        req = build_write_multiple_registers(slave, address, values)
        resp = self.send_receive(req)
        print(f"    FC16 response: {resp.hex()} ({len(resp)} bytes)")
        if resp[1] & 0x80:
            exc_code = resp[2] if len(resp) > 2 else 0
            print(f"    FC16 EXCEPTION: code={exc_code}")
            return False
        return resp[1] == 0x10


def read_config(conn, slave):
    """Read regs 4351-4354 and return (mode, p, reserved, q)"""
    regs = conn.read_registers(slave, 4351, 4)
    return regs[0], regs[1], regs[2], regs[3]


def print_config(mode, p, reserved, q, prefix="  "):
    print(f"{prefix}LoadMode(4351)={mode}  P%(4352)={p}({p*0.1:.1f}%)  (4353)={reserved}  Q%(4354)={q}({q*0.1:.1f}%)")


# ===========================================================================
# Tests
# ===========================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="10.11.0.2")
    parser.add_argument("--port", type=int, default=26)
    parser.add_argument("--slave", type=int, default=3)
    args = parser.parse_args()

    conn = ModbusConnection()
    print("=" * 70)
    print("HGM9560 Extended FC06/FC16 Write Test")
    print(f"Target: {args.ip}:{args.port} slave={args.slave}")
    print("=" * 70)

    try:
        conn.connect(args.ip, args.port)
        print("[OK] Connected\n")
    except Exception as e:
        print(f"[FAIL] {e}")
        sys.exit(1)

    # Read current config
    print("--- READ CURRENT CONFIG ---")
    mode_orig, p_orig, reserved_orig, q_orig = read_config(conn, args.slave)
    print_config(mode_orig, p_orig, reserved_orig, q_orig)
    print()

    test_p = (p_orig + 1) if p_orig < 1000 else (p_orig - 1)

    # ================================================================
    # TEST A: FC16 single register 4352
    # ================================================================
    print("=" * 70)
    print(f"TEST A: FC16 (Write Multiple Registers) — reg 4352 = {test_p}")
    print("=" * 70)
    try:
        time.sleep(0.2)
        ok = conn.write_multiple_registers(args.slave, 4352, [test_p])
        print(f"  FC16 result: {'OK' if ok else 'FAIL / EXCEPTION'}")
        time.sleep(0.3)
        m, p, r, q = read_config(conn, args.slave)
        print_config(m, p, r, q)
        if p == test_p:
            print(f"  >>> TEST A: SUCCESS — P% changed {p_orig} -> {p} <<<")
        else:
            print(f"  >>> TEST A: FAIL — P% still {p} (expected {test_p}) <<<")
    except Exception as e:
        print(f"  [ERROR] {e}")
    print()

    # ================================================================
    # TEST B: FC16 bulk write 4351-4354 (4 registers)
    # ================================================================
    print("=" * 70)
    print(f"TEST B: FC16 bulk write regs 4351-4354 = [{mode_orig}, {test_p}, {reserved_orig}, {q_orig}]")
    print("=" * 70)
    try:
        time.sleep(0.2)
        ok = conn.write_multiple_registers(args.slave, 4351, [mode_orig, test_p, reserved_orig, q_orig])
        print(f"  FC16 result: {'OK' if ok else 'FAIL / EXCEPTION'}")
        time.sleep(0.3)
        m, p, r, q = read_config(conn, args.slave)
        print_config(m, p, r, q)
        if p == test_p:
            print(f"  >>> TEST B: SUCCESS — P% changed {p_orig} -> {p} <<<")
        else:
            print(f"  >>> TEST B: FAIL — P% still {p} (expected {test_p}) <<<")
    except Exception as e:
        print(f"  [ERROR] {e}")
    print()

    # ================================================================
    # TEST C: Password 0318 to reg 199, then FC06 to 4352
    # ================================================================
    print("=" * 70)
    print(f"TEST C: FC06 reg 199 = 318 (password), then FC06 reg 4352 = {test_p}")
    print("=" * 70)
    try:
        time.sleep(0.2)
        # Save reg 199 first
        regs199 = conn.read_registers(args.slave, 199, 1)
        orig_199 = regs199[0]
        print(f"  Current reg 199 = {orig_199}")

        # Write password
        ok_pw = conn.write_register(args.slave, 199, 318)
        print(f"  Password FC06 reg 199=318: {'OK' if ok_pw else 'FAIL'}")
        time.sleep(0.15)

        # Write P%
        ok_p = conn.write_register(args.slave, 4352, test_p)
        print(f"  FC06 reg 4352={test_p}: {'OK' if ok_p else 'FAIL'}")
        time.sleep(0.3)

        m, p, r, q = read_config(conn, args.slave)
        print_config(m, p, r, q)
        if p == test_p:
            print(f"  >>> TEST C: SUCCESS — Password + FC06 works! <<<")
        else:
            print(f"  >>> TEST C: FAIL — P% still {p} (expected {test_p}) <<<")

        # Restore reg 199
        conn.write_register(args.slave, 199, orig_199)
        print(f"  Restored reg 199 = {orig_199}")
    except Exception as e:
        print(f"  [ERROR] {e}")
    print()

    # ================================================================
    # TEST D: Password 0318 to reg 199, then FC16 bulk
    # ================================================================
    print("=" * 70)
    print(f"TEST D: FC06 reg 199 = 318 (password), then FC16 bulk 4351-4354")
    print("=" * 70)
    try:
        time.sleep(0.2)
        regs199 = conn.read_registers(args.slave, 199, 1)
        orig_199 = regs199[0]

        # Write password
        ok_pw = conn.write_register(args.slave, 199, 318)
        print(f"  Password FC06 reg 199=318: {'OK' if ok_pw else 'FAIL'}")
        time.sleep(0.15)

        # Bulk write
        ok = conn.write_multiple_registers(args.slave, 4351, [mode_orig, test_p, reserved_orig, q_orig])
        print(f"  FC16 bulk result: {'OK' if ok else 'FAIL / EXCEPTION'}")
        time.sleep(0.3)

        m, p, r, q = read_config(conn, args.slave)
        print_config(m, p, r, q)
        if p == test_p:
            print(f"  >>> TEST D: SUCCESS — Password + FC16 works! <<<")
        else:
            print(f"  >>> TEST D: FAIL — P% still {p} (expected {test_p}) <<<")

        # Restore reg 199
        conn.write_register(args.slave, 199, orig_199)
        print(f"  Restored reg 199 = {orig_199}")
    except Exception as e:
        print(f"  [ERROR] {e}")
    print()

    # ================================================================
    # TEST E: FC06 to reg 4352 with longer delay (1 second before read-back)
    # ================================================================
    print("=" * 70)
    print(f"TEST E: FC06 reg 4352 = {test_p}, then wait 1.5s before read-back")
    print("=" * 70)
    try:
        time.sleep(0.2)
        ok = conn.write_register(args.slave, 4352, test_p)
        print(f"  FC06 result: {'OK' if ok else 'FAIL'}")
        print("  Waiting 1.5 seconds...")
        time.sleep(1.5)
        m, p, r, q = read_config(conn, args.slave)
        print_config(m, p, r, q)
        if p == test_p:
            print(f"  >>> TEST E: SUCCESS — FC06 with long delay works! <<<")
        else:
            print(f"  >>> TEST E: FAIL — P% still {p} (expected {test_p}) <<<")
    except Exception as e:
        print(f"  [ERROR] {e}")
    print()

    # ================================================================
    # TEST F: Write reg 4352 via FC06 three times rapidly
    # ================================================================
    print("=" * 70)
    print(f"TEST F: FC06 reg 4352 = {test_p} x3 (triple write)")
    print("=" * 70)
    try:
        time.sleep(0.2)
        for i in range(3):
            ok = conn.write_register(args.slave, 4352, test_p)
            print(f"  Write #{i+1}: {'OK' if ok else 'FAIL'}")
            time.sleep(0.15)
        time.sleep(0.5)
        m, p, r, q = read_config(conn, args.slave)
        print_config(m, p, r, q)
        if p == test_p:
            print(f"  >>> TEST F: SUCCESS — Triple FC06 works! <<<")
        else:
            print(f"  >>> TEST F: FAIL — P% still {p} (expected {test_p}) <<<")
    except Exception as e:
        print(f"  [ERROR] {e}")
    print()

    # ================================================================
    # Done
    # ================================================================
    conn.disconnect()
    print("=" * 70)
    print("All tests complete. Connection closed.")
    print("=" * 70)


if __name__ == "__main__":
    main()

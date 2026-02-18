"""
Диагностика сетевого подключения к контроллерам.
Запуск: python backend/scripts/network_diag.py
"""
import asyncio
import socket
import subprocess
import sys

TARGETS = [
    ("Gen1", "192.168.97.10", 502),
    ("Gen2", "192.168.97.11", 502),
    ("SPR",  "10.11.0.2", 26),
]


async def main():
    for name, ip, port in TARGETS:
        print(f"\n{'='*60}")
        print(f"  {name} — {ip}:{port}")
        print(f"{'='*60}")

        # 1. Ping
        result = subprocess.run(
            ["ping", "-n" if sys.platform == "win32" else "-c", "3", ip],
            capture_output=True, text=True, timeout=10
        )
        print(f"\n[PING] {'OK' if result.returncode == 0 else 'FAIL'}")
        print(result.stdout[-200:] if result.stdout else result.stderr[-200:])

        # 2. ARP
        result = subprocess.run(["arp", "-a", ip], capture_output=True, text=True)
        print(f"\n[ARP]\n{result.stdout.strip()}")

        # 3. TCP connect
        try:
            sock = socket.create_connection((ip, port), timeout=3)
            print(f"\n[TCP:{port}] Connected OK")
            sock.close()
        except Exception as e:
            print(f"\n[TCP:{port}] FAIL: {e}")

        # 4. Modbus read (status register 0)
        try:
            sys.path.insert(0, "backend/app")
            from services.modbus_poller import build_read_registers, parse_read_registers_response
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=3
            )
            frame = build_read_registers(1, 0, 1)
            writer.write(frame)
            await writer.drain()
            await asyncio.sleep(0.2)
            data = await asyncio.wait_for(reader.read(256), timeout=3)
            regs = parse_read_registers_response(data)
            if regs:
                print(f"\n[MODBUS] Register 0 = 0x{regs[0]:04X} ({regs[0]})")
            else:
                print(f"\n[MODBUS] No valid response. Raw: {data.hex()}")
            writer.close()
        except Exception as e:
            print(f"\n[MODBUS] FAIL: {e}")

        # 5. Traceroute (first 5 hops)
        cmd = ["tracert", "-d", "-h", "5", ip] if sys.platform == "win32" else ["traceroute", "-n", "-m", "5", ip]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            print(f"\n[TRACEROUTE]\n{result.stdout[:500]}")
        except Exception:
            print("\n[TRACEROUTE] timeout")

    # 6. Route table for 192.168.97.x
    print(f"\n{'='*60}")
    print(f"  ROUTE TABLE (192.168.97.x)")
    print(f"{'='*60}")
    if sys.platform == "win32":
        result = subprocess.run(["route", "print"], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if '192.168.97' in line or '0.0.0.0' in line:
                print(line)
    else:
        result = subprocess.run(["ip", "route", "show"], capture_output=True, text=True)
        print(result.stdout)


asyncio.run(main())

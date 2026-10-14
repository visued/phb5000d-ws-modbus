#!/usr/bin/env python3
"""Leitor Modbus TCP (somente leitura) do inversor PHB5000D-WS (linha D-WS).

Só usa a função 03 (Read Holding Registers). Nunca escreve no inversor.
Mapa de registradores e ressalvas: README.md desta pasta.

Uso:
    python3 phb_reader.py 192.168.18.138            # JSON decodificado
    python3 phb_reader.py 192.168.18.138 --raw      # + registradores brutos
    python3 phb_reader.py 192.168.18.138 --watch 30 # repete a cada 30 s

Como biblioteca:
    from phb_reader import read_inverter
    data = read_inverter("192.168.18.138")
"""
import argparse
import json
import socket
import struct
import sys
import time

# Tabelas válidas (início, quantidade). O módulo só responde se o bloco
# inteiro estiver dentro de uma tabela; fora disso ele não responde nada
# (nem exceção) e trava ~1 s esperando o inversor na RS485.
BLOCKS = [(30001, 16), (30034, 51), (30100, 100), (30200, 30), (40173, 16)]


class ModbusError(Exception):
    pass


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ModbusError("conexão fechada pelo inversor")
        buf += chunk
    return buf


def read_holding(sock, start, count, tid=1, unit=1):
    """FC03 — lê `count` registradores a partir de `start`. Retorna lista de uint16."""
    sock.sendall(struct.pack(">HHHBBHH", tid, 0, 6, unit, 3, start, count))
    head = _recv_exact(sock, 7)
    rtid, _, length, _ = struct.unpack(">HHHB", head)
    body = _recv_exact(sock, length - 1)
    if rtid != tid:
        raise ModbusError(f"transaction id inesperado ({rtid} != {tid})")
    if body[0] & 0x80:
        raise ModbusError(f"exceção Modbus {body[1]} em {start}")
    nbytes = body[1]
    return list(struct.unpack(f">{nbytes // 2}H", body[2:2 + nbytes]))


def read_raw(host, port=502, timeout=3.0, pause=0.2):
    """Lê todas as tabelas conhecidas numa única conexão. Retorna {endereço: uint16}."""
    regs = {}
    with socket.create_connection((host, port), timeout=timeout) as sock:
        for i, (start, count) in enumerate(BLOCKS, 1):
            for off, val in enumerate(read_holding(sock, start, count, tid=i)):
                regs[start + off] = val
            time.sleep(pause)
    return regs


def _u32(r, a):
    return (r[a] << 16) | r[a + 1]


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def _s32(r, a):
    v = _u32(r, a)
    return v - 0x100000000 if v & 0x80000000 else v


def _ascii(r, a, n):
    raw = b"".join(struct.pack(">H", r[a + i]) for i in range(n))
    return raw.split(b"\x00")[0].decode("ascii", "replace").strip()


def _opt(v, scale=1.0, nd=1):
    """0xFFFF = campo não usado neste modelo (ex.: fases B/C no monofásico)."""
    return None if v == 0xFFFF else round(v * scale, nd)


def decode(r):
    """Converte registradores brutos em grandezas. Confiança de cada campo: README.md."""
    yy, mo = r[30100] >> 8, r[30100] & 0xFF
    dd, hh = r[30101] >> 8, r[30101] & 0xFF
    mi, ss = r[30102] >> 8, r[30102] & 0xFF
    pv = []
    for n, a in enumerate((30103, 30105), 1):  # 30107/30108 = MPPT3, sempre 0 no 5000D-WS
        v, i = _opt(r[a], 0.1), _opt(r[a + 1], 0.1)
        if v is None:
            continue
        pv.append({"mppt": n, "v": v, "a": i, "w": round(v * i) if i is not None else None})
    return {
        "model": _ascii(r, 40173, 16),
        "serial": _ascii(r, 30004, 8),
        "inverter_time": f"20{yy:02d}-{mo:02d}-{dd:02d}T{hh:02d}:{mi:02d}:{ss:02d}",
        "pv": pv,
        "pv_w": sum(p["w"] or 0 for p in pv),
        "ac_v": _opt(r[30118], 0.1),
        "ac_a": _opt(r[30121], 0.1),
        "ac_hz": _opt(r[30124], 0.01, 2),
        "ac_w": _s32(r, 30127),
        "ac_va": _s32(r, 30133),
        "ac_var": _s16(r[30136]),
        "pf": _opt(r[30139], 0.001, 3),
        "temp1_c": _opt(r[30141], 0.1),
        "temp2_c": _opt(r[30142], 0.1),
        "energy_today_kwh": _opt(r[30144], 0.1),
        "energy_total_kwh": round(_u32(r, 30145) * 0.1, 1),
        "hours_total": _u32(r, 30147),
        "bus_v": _opt(r[30163], 0.1),
        "string_a": [x for x in (_opt(r[30175], 0.1), _opt(r[30176], 0.1)) if x is not None],
        "status_raw": r[30034],
        "fw_part": _ascii(r, 30221, 6),
    }


def read_inverter(host, port=502, timeout=3.0, raw=False):
    regs = read_raw(host, port, timeout)
    out = decode(regs)
    out["read_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if raw:
        out["raw"] = {str(a): f"0x{v:04x}" for a, v in sorted(regs.items())}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("host")
    ap.add_argument("--port", type=int, default=502)
    ap.add_argument("--raw", action="store_true", help="inclui registradores brutos")
    ap.add_argument("--watch", type=float, default=0, help="repete a cada N segundos (mín. 10)")
    args = ap.parse_args()
    while True:
        try:
            print(json.dumps(read_inverter(args.host, args.port, raw=args.raw), ensure_ascii=False), flush=True)
        except (OSError, ModbusError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
        if not args.watch:
            break
        time.sleep(max(args.watch, 10))


if __name__ == "__main__":
    main()

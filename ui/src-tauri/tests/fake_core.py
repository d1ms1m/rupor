"""Поддельное ядро для теста супервизора (sidecar.rs).

Запуск: python fake_core.py <папка_состояния> --sidecar --ws-port P --token T --ui-pid PID
Пишет свои аргументы в run-<N>.txt и слушает порт. Первый запуск «падает» через 1 с
с кодом 3, следующие работают до остановки.

Режим ws (в папке состояния есть файл ws-mode): не падает, а ждёт выхода по WS-команде, как
настоящее ядро, — проверяет токен в рукопожатии, отвечает 101 и событием hello, ждёт
текстовый кадр, отвечает на него, ждёт кадр закрытия (код 1000), пишет полезную нагрузку
текстового кадра в quit-<N>.json и завершается с кодом 0.
"""
from __future__ import annotations

import base64
import hashlib
import pathlib
import socket
import sys
import time


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("соединение закрыто")
        buf += chunk
    return buf


def _recv_frame(conn: socket.socket, first: int) -> bytes | None:
    """Короткий маскированный кадр клиента с первым байтом first → полезная нагрузка."""
    b0, b1 = _recv_exact(conn, 2)
    if b0 != first or not b1 & 0x80 or (b1 & 0x7F) >= 126:
        return None
    mask = _recv_exact(conn, 4)
    data = _recv_exact(conn, b1 & 0x7F)
    return bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def _ws_quit(conn: socket.socket, token: str, out: pathlib.Path) -> bool:
    """Рукопожатие WebSocket с токеном, текстовый кадр клиента (→ out) и кадр закрытия.
    True — всё получено."""
    conn.settimeout(2.0)
    head = b""
    try:
        while b"\r\n\r\n" not in head:
            chunk = conn.recv(1)
            if not chunk:
                return False  # проба порта супервизора: подключился и закрыл
            head += chunk
        lines = head.decode("latin-1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        key = headers.get("sec-websocket-key", "")
        if (not lines[0].startswith(f"GET /?token={token} HTTP/1.1")
                or headers.get("upgrade", "").lower() != "websocket"
                or len(base64.b64decode(key)) != 16):
            conn.sendall(b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n")
            return False
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        conn.sendall((f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        # как настоящее ядро — сразу событие hello (длинное: 16-битная длина кадра)
        hello = b'{"event":"hello","data":{"pad":"' + b"x" * 300 + b'"}}'
        conn.sendall(bytes([0x81, 126]) + len(hello).to_bytes(2, "big") + hello)
        text = _recv_frame(conn, 0x81)
        if text is None:
            return False  # ждём короткий маскированный текстовый кадр
        reply = b'{"id":1,"ok":true,"result":null}'
        conn.sendall(bytes([0x81, len(reply)]) + reply)
        if _recv_frame(conn, 0x88) != (1000).to_bytes(2, "big"):
            return False  # после ответа — кадр закрытия с кодом 1000
        conn.sendall(bytes([0x88, 2]) + (1000).to_bytes(2, "big"))
        out.write_bytes(text)
        return True
    except (OSError, ValueError):
        return False
    finally:
        conn.close()


def main() -> int:
    state = pathlib.Path(sys.argv[1])
    args = sys.argv[2:]
    port = int(args[args.index("--ws-port") + 1])
    token = args[args.index("--token") + 1]
    ws = (state / "ws-mode").exists()
    run = len(list(state.glob("run-*.txt")))
    (state / f"run-{run}.txt").write_text("\n".join(args), encoding="utf-8")
    srv = socket.create_server(("127.0.0.1", port))
    srv.settimeout(0.2)
    deadline = time.monotonic() + (1.0 if run == 0 and not ws else 120.0)
    while time.monotonic() < deadline:
        try:
            conn, _ = srv.accept()
        except TimeoutError:
            continue
        if not ws:
            conn.close()
        elif _ws_quit(conn, token, state / f"quit-{run}.json"):
            return 0
    return 3 if run == 0 else 0


if __name__ == "__main__":
    sys.exit(main())

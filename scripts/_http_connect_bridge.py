"""SSH ProxyCommand：经本地 HTTP 代理(127.0.0.1:10808) CONNECT 到目标并桥接 stdio。
用法: python http_connect_bridge.py <host> <port>
本机直连被 v2ray TUN 劫持，但 10808 代理可通，故走代理建立到服务器的 TCP 隧道。
"""
import socket
import sys
import threading

PROXY = ("127.0.0.1", 10808)


def main() -> None:
    host, port = sys.argv[1], int(sys.argv[2])
    s = socket.create_connection(PROXY, timeout=20)
    s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            sys.exit(1)
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0]
    if b" 200" not in status_line:
        sys.stderr.write(f"proxy CONNECT failed: {status_line!r}\n")
        sys.exit(1)
    # CONNECT 响应头之后若已带数据（如 SSH banner）需先吐出
    if rest:
        sys.stdout.buffer.write(rest)
        sys.stdout.buffer.flush()

    def pump_stdin_to_sock() -> None:
        try:
            while True:
                data = sys.stdin.buffer.read(8192)
                if not data:
                    break
                s.sendall(data)
        except Exception:
            pass
        finally:
            try:
                s.shutdown(socket.SHUT_WR)
            except Exception:
                pass

    threading.Thread(target=pump_stdin_to_sock, daemon=True).start()
    try:
        while True:
            data = s.recv(8192)
            if not data:
                break
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    except Exception:
        pass


if __name__ == "__main__":
    main()

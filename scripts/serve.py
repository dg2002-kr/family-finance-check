# -*- coding: utf-8 -*-
"""
집 와이파이 안에서 휴대폰으로 대시보드를 본다.

  python -X utf8 scripts/serve.py
  python -X utf8 scripts/serve.py --port 8080 --open

★ 같은 와이파이에 붙은 기기에서만 보입니다. 인터넷 밖으로는 나가지 않습니다.
★ 공용 와이파이(카페·회사)에서는 켜지 마세요. 같은 망의 다른 사람도 볼 수 있습니다.
★ 끄려면 이 창에서 Ctrl+C.
"""
import argparse
import http.server
import socket
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import quote

뿌리 = Path(__file__).resolve().parent.parent
대시보드 = "우리집_점검.html"


def 내주소():
    """공유기가 준 이 PC의 주소를 찾는다. 밖으로 나가는 통신은 하지 않는다."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))     # 실제로 보내지 않는다. 경로만 물어본다
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        s.close()


def 만들기(폴더: Path):
    class 손님맞이(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(폴더), **kw)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(302)
                self.send_header("Location", "/" + quote(대시보드))
                self.end_headers()
                return
            super().do_GET()

        def end_headers(self):
            # 브라우저가 옛 화면을 계속 보여주지 않게 한다
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, 꼴, *인자):
            if "GET" in (인자[0] if 인자 else ""):
                pass    # 조용히

    return 손님맞이


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="휴대폰에서 볼 수 있게 잠깐 띄웁니다.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dir", default="out")
    ap.add_argument("--open", action="store_true", help="이 PC 브라우저도 같이 연다")
    args = ap.parse_args()

    폴더 = (뿌리 / args.dir).resolve()
    if not (폴더 / 대시보드).exists():
        print(f"[!] 대시보드가 없습니다: {폴더 / 대시보드}")
        print("    먼저 run.bat 을 누르거나 scripts/report.py 를 돌려주세요.")
        return 3

    주소 = 내주소()
    socketserver.TCPServer.allow_reuse_address = True
    try:
        서버 = socketserver.ThreadingTCPServer(("0.0.0.0", args.port), 만들기(폴더))
    except OSError as e:
        print(f"[!] {args.port} 번을 쓸 수 없습니다. ({e})")
        print("    --port 8080 처럼 다른 번호로 해보세요.")
        return 1

    링크 = f"http://{주소}:{args.port}/"
    print()
    print("  집 와이파이 안에서만 보이는 주소를 열었습니다.")
    print("  " + "─" * 46)
    print()
    print(f"    휴대폰 브라우저에 이 주소를 치세요")
    print()
    print(f"      {링크}")
    print()
    print("  " + "─" * 46)
    print("  · 휴대폰이 이 PC와 같은 와이파이에 붙어 있어야 합니다.")
    print("  · 크롬·사파리에서 '홈 화면에 추가' 를 하면 앱처럼 열립니다.")
    print("  · 공용 와이파이에서는 켜지 마세요. 같은 망의 다른 사람도 볼 수 있습니다.")
    print("  · 끄려면 이 창에서 Ctrl+C.")
    print()

    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}/")).start()

    try:
        서버.serve_forever()
    except KeyboardInterrupt:
        print("\n  껐습니다. 이제 밖에서 볼 수 없습니다.")
    finally:
        서버.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

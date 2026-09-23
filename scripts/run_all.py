# -*- coding: utf-8 -*-
"""
한 번에 끝내기 — 파일을 읽고, 대시보드를 만들고, 브라우저로 띄운다.

  run.bat 을 두 번 누르면 이 파일이 돕니다.
  명령창에서는:  python -X utf8 scripts/run_all.py

내 데이터(data/private)가 있으면 그것을, 없으면 예시(data/sample)를 씁니다.
"""
import argparse
import subprocess
import sys
import webbrowser
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent


def 줄(글=""):
    print(f"  {글}")


def 돌리기(이름, 인자):
    명령 = [sys.executable, "-X", "utf8", str(뿌리 / "scripts" / 이름)] + 인자
    끝 = subprocess.run(명령, cwd=뿌리)
    return 끝.returncode


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--data", default="")
    ap.add_argument("--ai", action="store_true", help="AI 분석도 새로 받아온다")
    args, _ = ap.parse_known_args()

    print()
    줄("우리집 머니 리포트")
    줄("─" * 46)
    print()

    # 엑셀 읽기 도구
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        줄("엑셀을 읽는 도구가 없어 지금 설치합니다…")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "openpyxl"])
        print()

    # 어느 폴더를 볼지
    폴더 = args.data
    if not 폴더:
        내것 = 뿌리 / "data" / "private"
        있음 = 내것.is_dir() and any(p.is_dir() for p in 내것.iterdir())
        폴더 = "data/private" if 있음 else "data/sample"
        if not 있음:
            줄("내 데이터가 아직 없어 예시로 보여드립니다.")
            줄("data/private 안에 가족 이름으로 폴더를 만들고 파일을 넣으세요.")
            print()

    줄(f"[1/2] {폴더} 의 파일을 읽어 한 표로 합치는 중…")
    print()
    if 돌리기("parse.py", ["--input", 폴더]) >= 3:
        print()
        줄("위 안내를 읽고 고친 뒤 다시 실행해 주세요.")
        return 1

    if args.ai:
        print()
        줄("[+] AI 분석을 받아오는 중…")
        print()
        돌리기("advise.py", ["--data", 폴더])

    print()
    줄("[2/2] 대시보드를 만드는 중…")
    print()
    if 돌리기("report.py", ["--data", 폴더]) >= 3:
        print()
        줄("위 안내를 읽고 고친 뒤 다시 실행해 주세요.")
        return 1

    결과 = 뿌리 / "out" / "우리집_머니리포트.html"
    print()
    줄("─" * 46)
    줄("다 됐습니다. 브라우저를 엽니다.")
    줄(f"{결과}")
    print()
    try:
        webbrowser.open(결과.as_uri())
    except Exception:
        줄("자동으로 열리지 않으면 위 파일을 두 번 누르세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

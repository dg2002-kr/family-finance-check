# -*- coding: utf-8 -*-
"""
지금 만든 대시보드를 깃허브 페이지(발표용 공개 주소)에 올린다.

  python -X utf8 tools/발표페이지_갱신.py

★ 예시 자료로 만든 화면만 올라갑니다.
  진짜 가족 자료로 만든 화면이면 멈추고 알려줍니다. 공개 주소이기 때문입니다.
"""
import shutil
import subprocess
import sys
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
만든것 = 뿌리 / "out" / "우리집_머니리포트.html"
올릴곳 = 뿌리 / "docs" / "index.html"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not 만든것.exists():
        print(f"[!] 대시보드가 없습니다: {만든것}")
        print("    먼저  python -X utf8 scripts/report.py  를 돌리세요.")
        return 1

    글 = 만든것.read_text(encoding="utf-8")
    if "지어낸 교육용 예시" not in 글:
        print("[!] 이 화면은 예시 자료로 만든 것이 아닙니다. 올리지 않았습니다.")
        print("    깃허브 페이지는 누구나 볼 수 있는 주소라서, 진짜 자료는 올리면 안 됩니다.")
        print("    예시로 만들려면:  python -X utf8 scripts/report.py --data data/sample")
        return 1

    올릴곳.parent.mkdir(exist_ok=True)
    shutil.copy(만든것, 올릴곳)
    print(f"  복사했습니다: {올릴곳.relative_to(뿌리)}  ({len(글.encode()):,}바이트)")
    print()
    print("  이제 아래 두 줄을 실행하면 공개 주소에 반영됩니다.")
    print('    git add docs/index.html && git commit -m "발표 페이지 갱신"')
    print("    git push")
    print()
    try:
        이름 = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q",
                             ".nameWithOwner"], capture_output=True, text=True,
                            cwd=뿌리, timeout=15).stdout.strip()
        if "/" in 이름:
            주인, 저장소 = 이름.split("/", 1)
            print(f"  주소: https://{주인}.github.io/{저장소}/")
    except Exception:
        pass
    print("  올린 뒤 1~2분 지나야 바뀝니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

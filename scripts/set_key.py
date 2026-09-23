# -*- coding: utf-8 -*-
"""
API 키를 이 PC에만 저장한다.

  python -X utf8 scripts/set_key.py            (제미나이)
  python -X utf8 scripts/set_key.py --dart      (DART)

★ 키를 화면에 찍지 않고, 대화창에도 남기지 않습니다.
  data/private/ 안에만 저장되고 깃허브에 올라가지 않습니다.
  이미 어딘가에 붙여넣은 키는 새로 발급받아 여기에 넣으세요.
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

곳 = {
    "gemini": {
        "파일": "gemini.key",
        "이름": "구글 제미나이",
        "받는곳": "https://aistudio.google.com/apikey",
        "생김새": "AQ. 또는 AIza 로 시작하는 긴 글자",
        "환경변수": "GEMINI_API_KEY",
    },
    "dart": {
        "파일": "dart.key",
        "이름": "금융감독원 DART",
        "받는곳": "https://opendart.fss.or.kr  (회원가입 → 인증키 신청, 무료·즉시)",
        "생김새": "영문·숫자 40자",
        "환경변수": "DART_API_KEY",
    },
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="API 키를 이 PC에만 저장합니다.")
    ap.add_argument("--dart", action="store_true", help="DART 키를 넣는다")
    ap.add_argument("--data", default="data/private")
    ap.add_argument("--show", action="store_true", help="어떤 키가 들어 있는지만 본다")
    args = ap.parse_args()

    종류 = "dart" if args.dart else "gemini"
    정보 = 곳[종류]
    자료 = Path(args.data)
    경로 = 자료 / 정보["파일"]

    if args.show:
        print()
        for k, v in 곳.items():
            p = 자료 / v["파일"]
            환경 = os.environ.get(v["환경변수"])
            상태 = []
            if p.exists() and p.read_text(encoding="utf-8").strip():
                글 = p.read_text(encoding="utf-8").strip()
                상태.append(f"파일에 있음 ({글[:4]}…{글[-4:]}, {len(글)}자)")
            if 환경:
                상태.append(f"환경변수에 있음 ({환경[:4]}…{환경[-4:]})")
            print(f"  {v['이름']:<16} {' · '.join(상태) or '없음'}")
        print()
        return 0

    print()
    print(f"  {정보['이름']} 키를 넣습니다.")
    print(f"  받는 곳: {정보['받는곳']}")
    print(f"  생김새: {정보['생김새']}")
    print()
    print("  아래에 붙여넣고 엔터를 누르세요. 화면에 글자가 보이지 않는 것이 정상입니다.")
    print("  (취소하려면 그냥 엔터)")
    print()

    try:
        키 = getpass.getpass("  키: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  취소했습니다.")
        return 1

    if not 키:
        print("\n  아무것도 넣지 않아 그대로 둡니다.")
        return 1
    if len(키) < 20:
        print(f"\n  [!] {len(키)}자밖에 안 됩니다. 키가 잘린 것 같으니 다시 확인해 주세요.")
        return 1

    경로.parent.mkdir(parents=True, exist_ok=True)
    경로.write_text(키, encoding="utf-8")
    try:
        os.chmod(경로, 0o600)
    except OSError:
        pass

    print()
    print(f"  저장했습니다: {경로}")
    print(f"  앞 4자리 {키[:4]}… 뒤 4자리 …{키[-4:]} ({len(키)}자)")
    print()
    print("  이 파일은 깃허브에 올라가지 않습니다 (.gitignore 가 *.key 를 막습니다).")
    print("  이제 명령을 그냥 실행하면 알아서 이 키를 씁니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

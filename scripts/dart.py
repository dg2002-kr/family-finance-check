# -*- coding: utf-8 -*-
"""
금융감독원 전자공시(DART)에서 보유 종목의 재무를 받아온다.

  python -X utf8 scripts/dart.py --mock          가상 값으로 흐름 보기 (기본)
  python -X utf8 scripts/dart.py --fetch         실제로 받아오기 (인증키 필요)
  python -X utf8 scripts/dart.py --corp 삼성전자  회사 코드만 찾아보기

★ 인증키는 개인도 무료로 즉시 발급됩니다.
  https://opendart.fss.or.kr → 회원가입 → 인증키 신청 (심사 없음)
  받으신 뒤  python -X utf8 scripts/set_key.py --dart  로 넣으세요.

★ 여기서 계산하는 값은 공시된 재무제표와 잔고에 적힌 현재가로 낸 것입니다.
  좋은 주식인지 나쁜 주식인지 판단하지 않고, 사거나 팔라고 권하지도 않습니다.
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from advise import 표읽기  # noqa: E402

API = "https://opendart.fss.or.kr/api"
보고서 = {"사업보고서": "11011", "반기": "11012", "1분기": "11013", "3분기": "11014"}

# 주요계정 응답의 account_nm 은 회사마다 조금씩 다르다. 넉넉히 잡는다.
계정별칭 = {
    "매출액": ["매출액", "수익(매출액)", "영업수익", "매출"],
    "영업이익": ["영업이익", "영업이익(손실)"],
    "당기순이익": ["당기순이익", "당기순이익(손실)", "당기순손익"],
    "자산총계": ["자산총계"],
    "부채총계": ["부채총계"],
    "자본총계": ["자본총계"],
}


def 키찾기(자료: Path):
    키 = (os.environ.get("DART_API_KEY") or "").strip()
    if 키:
        return 키, "환경변수 DART_API_KEY"
    for 후보 in (자료 / "dart.key", Path("data/private/dart.key")):
        if 후보.exists():
            값 = re.sub(r"[^\x21-\x7E]", "", 후보.read_text(encoding="utf-8"))
            if 값:
                return 값, str(후보)
    return None, None


def 부르기(길, 변수, 초=40):
    url = f"{API}/{길}?{urllib.parse.urlencode(변수)}"
    try:
        with urllib.request.urlopen(url, timeout=초) as r:
            원본 = r.read()
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if 길.endswith(".xml"):
        return 원본, None
    try:
        답 = json.loads(원본.decode("utf-8"))
    except Exception:
        return None, "답을 읽지 못했습니다"
    상태 = 답.get("status")
    if 상태 and 상태 != "000":
        말 = {"010": "인증키가 잘못됐습니다", "011": "사용할 수 없는 키입니다",
             "013": "찾는 자료가 없습니다", "020": "하루 요청 수를 넘겼습니다",
             "100": "보낸 값이 잘못됐습니다"}.get(상태, 답.get("message", ""))
        return None, f"{상태} — {말}"
    return 답, None


# ============================================================================
def 회사표받기(키, 자료: Path):
    """상장사 고유번호표. 한 번 받아 두면 계속 쓴다 (약 2만 곳, 몇 MB)."""
    캐시 = 자료 / "dart_회사표.json"
    if 캐시.exists():
        return json.loads(캐시.read_text(encoding="utf-8")), None

    print("  회사 목록을 처음 받아옵니다. 잠시 걸립니다…")
    원본, 오류 = 부르기("corpCode.xml", {"crtfc_key": 키}, 초=120)
    if 오류:
        return None, 오류
    try:
        with zipfile.ZipFile(io.BytesIO(원본)) as z:
            글 = z.read(z.namelist()[0]).decode("utf-8")
    except Exception as e:
        return None, f"압축을 풀지 못했습니다 ({type(e).__name__})"

    표 = {}
    for 덩이 in re.findall(r"<list>(.*?)</list>", 글, re.S):
        이름 = re.search(r"<corp_name>(.*?)</corp_name>", 덩이, re.S)
        코드 = re.search(r"<corp_code>(.*?)</corp_code>", 덩이, re.S)
        종목 = re.search(r"<stock_code>(.*?)</stock_code>", 덩이, re.S)
        if 이름 and 코드 and 종목 and 종목.group(1).strip():
            표[이름.group(1).strip()] = 코드.group(1).strip()
    캐시.parent.mkdir(parents=True, exist_ok=True)
    캐시.write_text(json.dumps(표, ensure_ascii=False), encoding="utf-8")
    print(f"  상장사 {len(표):,}곳을 받아 저장했습니다.")
    return 표, None


def 회사찾기(표, 이름):
    """'삼성전자' 같은 종목명으로 고유번호를 찾는다. ETF 처럼 회사가 아닌 것은 없다."""
    이름 = 이름.strip()
    if 이름 in 표:
        return 이름, 표[이름]
    붙인 = 이름.replace(" ", "")
    for 회사, 코드 in 표.items():
        if 회사.replace(" ", "") == 붙인:
            return 회사, 코드
    return None, None


def 숫자(글):
    try:
        return int(str(글).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def 재무읽기(키, 코드, 해, 구분="사업보고서"):
    답, 오류 = 부르기("fnlttSinglAcnt.json", {
        "crtfc_key": 키, "corp_code": 코드,
        "bsns_year": str(해), "reprt_code": 보고서[구분]})
    if 오류:
        return None, 오류

    모음 = {}
    for r in 답.get("list", []):
        if r.get("fs_div") not in (None, "CFS"):      # 연결재무제표 우선
            continue
        이름 = (r.get("account_nm") or "").strip()
        for 표준, 별칭들 in 계정별칭.items():
            if 이름 in 별칭들:
                모음.setdefault(표준, {})
                모음[표준]["당기"] = 숫자(r.get("thstrm_amount"))
                모음[표준]["전기"] = 숫자(r.get("frmtrm_amount"))
    return 모음, None


def 주식수읽기(키, 코드, 해, 구분="사업보고서"):
    답, 오류 = 부르기("stockTotqySttus.json", {
        "crtfc_key": 키, "corp_code": 코드,
        "bsns_year": str(해), "reprt_code": 보고서[구분]})
    if 오류:
        return None, 오류
    for r in 답.get("list", []):
        if "보통주" in (r.get("se") or "") or (r.get("se") or "").strip() == "합계":
            n = 숫자(r.get("distb_stock_co")) or 숫자(r.get("istc_totqy"))
            if n:
                return n, None
    return None, "발행주식수를 찾지 못했습니다"


# ============================================================================
가상재무 = {
    "삼성전자": {"해": 2025, "매출액": 302_000_000_000_000, "영업이익": 38_500_000_000_000,
              "당기순이익": 34_200_000_000_000, "자본총계": 402_000_000_000_000,
              "자산총계": 520_000_000_000_000, "부채총계": 118_000_000_000_000,
              "주식수": 5_969_782_550},
    "SK하이닉스": {"해": 2025, "매출액": 78_400_000_000_000, "영업이익": 24_100_000_000_000,
                "당기순이익": 19_800_000_000_000, "자본총계": 82_500_000_000_000,
                "자산총계": 116_000_000_000_000, "부채총계": 33_500_000_000_000,
                "주식수": 728_002_365},
    "NAVER": {"해": 2025, "매출액": 11_200_000_000_000, "영업이익": 1_880_000_000_000,
              "당기순이익": 1_450_000_000_000, "자본총계": 23_400_000_000_000,
              "자산총계": 34_800_000_000_000, "부채총계": 11_400_000_000_000,
              "주식수": 155_000_000},
    "현대차": {"해": 2025, "매출액": 175_000_000_000_000, "영업이익": 14_200_000_000_000,
             "당기순이익": 12_600_000_000_000, "자본총계": 98_000_000_000_000,
             "자산총계": 290_000_000_000_000, "부채총계": 192_000_000_000_000,
             "주식수": 209_416_191},
    "카카오": {"해": 2025, "매출액": 8_100_000_000_000, "영업이익": 520_000_000_000,
             "당기순이익": 180_000_000_000, "자본총계": 12_600_000_000_000,
             "자산총계": 22_400_000_000_000, "부채총계": 9_800_000_000_000,
             "주식수": 445_000_000},
    "기아": {"해": 2025, "매출액": 109_000_000_000_000, "영업이익": 11_800_000_000_000,
           "당기순이익": 9_400_000_000_000, "자본총계": 61_000_000_000_000,
           "자산총계": 108_000_000_000_000, "부채총계": 47_000_000_000_000,
           "주식수": 397_000_000},
    "두산에너빌리티": {"해": 2025, "매출액": 17_600_000_000_000, "영업이익": 1_240_000_000_000,
                 "당기순이익": 610_000_000_000, "자본총계": 12_800_000_000_000,
                 "자산총계": 27_900_000_000_000, "부채총계": 15_100_000_000_000,
                 "주식수": 640_000_000},
    "삼성바이오로직스": {"해": 2025, "매출액": 4_900_000_000_000, "영업이익": 1_760_000_000_000,
                  "당기순이익": 1_320_000_000_000, "자본총계": 12_400_000_000_000,
                  "자산총계": 15_600_000_000_000, "부채총계": 3_200_000_000_000,
                  "주식수": 71_200_000},
    "LG에너지솔루션": {"해": 2025, "매출액": 26_400_000_000_000, "영업이익": 620_000_000_000,
                 "당기순이익": 240_000_000_000, "자본총계": 24_800_000_000_000,
                 "자산총계": 51_200_000_000_000, "부채총계": 26_400_000_000_000,
                 "주식수": 234_000_000},
    "셀트리온": {"해": 2025, "매출액": 3_900_000_000_000, "영업이익": 780_000_000_000,
             "당기순이익": 520_000_000_000, "자본총계": 12_100_000_000_000,
             "자산총계": 14_900_000_000_000, "부채총계": 2_800_000_000_000,
             "주식수": 217_000_000},
}


def 지표계산(재무: dict, 주식수, 현재가):
    """공시된 값과 잔고에 적힌 현재가로 낸 값. 좋고 나쁨은 판단하지 않는다."""
    나옴 = dict(재무)
    순익 = 재무.get("당기순이익")
    자본 = 재무.get("자본총계")
    매출 = 재무.get("매출액")
    영익 = 재무.get("영업이익")

    if 매출 and 영익:
        나옴["영업이익률"] = round(영익 / 매출 * 100, 1)
    if 자본 and 순익:
        나옴["ROE"] = round(순익 / 자본 * 100, 1)
    if 주식수:
        if 순익:
            나옴["EPS"] = round(순익 / 주식수)
        if 자본:
            나옴["BPS"] = round(자본 / 주식수)
    if 현재가 and 나옴.get("EPS"):
        나옴["PER"] = round(현재가 / 나옴["EPS"], 1)
    if 현재가 and 나옴.get("BPS"):
        나옴["PBR"] = round(현재가 / 나옴["BPS"], 2)
    return 나옴


def 현재가표(자료: Path):
    값 = {}
    for r in 표읽기(자료 / "보유종목.csv"):
        이름 = (r.get("종목명") or "").strip()
        try:
            가 = float(str(r.get("현재가", "")).replace(",", "") or 0)
        except ValueError:
            가 = 0
        if 이름 and 가:
            값[이름] = 가
    return 값


# ============================================================================
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="DART 에서 보유 종목 재무를 받아옵니다.")
    ap.add_argument("--data", default="data/sample")
    ap.add_argument("--year", type=int, default=0, help="사업연도 (기본: 작년)")
    ap.add_argument("--mock", action="store_true", help="가상 값으로 흐름만 본다")
    ap.add_argument("--fetch", action="store_true", help="실제로 받아온다")
    ap.add_argument("--corp", help="이 이름의 회사 코드만 찾아본다")
    args = ap.parse_args()

    자료 = Path(args.data)
    해 = args.year or 2025
    가격 = 현재가표(자료)

    종목들 = list(가격) or []
    if not 종목들 and not args.corp:
        print(f"[!] 보유종목.csv 가 없습니다: {자료 / '보유종목.csv'}")
        return 3

    # ---------------- 가상 ----------------
    if not (args.fetch or args.corp):
        print("가상 모드입니다. 인터넷에 연결하지 않고 값의 모양만 보여줍니다.")
        print("실제로 받으려면 인증키를 넣고 --fetch 를 쓰세요.\n")
        모음 = {}
        for 이름 in 종목들:
            바탕 = 가상재무.get(이름)
            if not 바탕:
                continue
            재무 = {k: v for k, v in 바탕.items() if k not in ("해", "주식수")}
            모음[이름] = 지표계산(재무, 바탕["주식수"], 가격.get(이름))
            모음[이름]["해"] = 바탕["해"]
            모음[이름]["출처"] = "가상"
        저장(모음, 자료, 해)
        return 0

    # ---------------- 실제 ----------------
    키, 어디 = 키찾기(자료)
    if not 키:
        print("[!] DART 인증키가 없습니다.")
        print("    1) https://opendart.fss.or.kr 에서 회원가입 → 인증키 신청 (무료·즉시)")
        print("    2) python -X utf8 scripts/set_key.py --dart")
        return 2
    print(f"키: {어디}")

    표, 오류 = 회사표받기(키, 자료)
    if 오류:
        print(f"[!] 회사 목록을 받지 못했습니다. {오류}")
        return 1

    if args.corp:
        회사, 코드 = 회사찾기(표, args.corp)
        print(f"  {args.corp} → {회사 or '못 찾음'} {코드 or ''}")
        return 0 if 코드 else 1

    모음 = {}
    for 이름 in 종목들:
        회사, 코드 = 회사찾기(표, 이름)
        if not 코드:
            print(f"  {이름:<20} 상장사가 아니거나 이름이 다릅니다 (ETF 는 재무가 없습니다)")
            continue
        재무, 오류 = 재무읽기(키, 코드, 해)
        if 오류 or not 재무:
            print(f"  {이름:<20} 재무를 받지 못했습니다 — {오류 or '자료 없음'}")
            continue
        주식수, _ = 주식수읽기(키, 코드, 해)
        값 = {k: v["당기"] for k, v in 재무.items() if v.get("당기")}
        모음[이름] = 지표계산(값, 주식수, 가격.get(이름))
        모음[이름]["해"] = 해
        모음[이름]["출처"] = "DART"
        print(f"  {이름:<20} {해}년 사업보고서 · 계정 {len(값)}개")

    if not 모음:
        print("\n받아온 것이 없습니다.")
        return 1
    저장(모음, 자료, 해)
    return 0


def 저장(모음, 자료: Path, 해):
    출력 = 자료 / "종목재무.json"
    출력.parent.mkdir(parents=True, exist_ok=True)
    출력.write_text(json.dumps({"기준해": 해, "종목": 모음}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"\n종목 {len(모음)}개")
    for 이름, v in 모음.items():
        조각 = []
        if v.get("매출액"):
            조각.append(f"매출 {v['매출액']/1e12:.1f}조")
        if v.get("영업이익률") is not None:
            조각.append(f"영업이익률 {v['영업이익률']}%")
        if v.get("EPS"):
            조각.append(f"EPS {v['EPS']:,}원")
        if v.get("PER"):
            조각.append(f"PER {v['PER']}")
        if v.get("PBR"):
            조각.append(f"PBR {v['PBR']}")
        print(f"  {이름:<20} " + " · ".join(조각))
    print(f"\n저장: {출력}")
    print("이제 python -X utf8 scripts/report.py 를 돌리면 종목 상세에 들어갑니다.")


if __name__ == "__main__":
    sys.exit(main())

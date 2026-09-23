# -*- coding: utf-8 -*-
"""
금융결제원 오픈뱅킹에서 거래내역을 받아 사람별 폴더에 CSV로 떨군다.

  python -X utf8 scripts/openbanking.py --mock --person 아빠      (가상 응답으로 흐름 확인)
  python -X utf8 scripts/openbanking.py --login                   (테스트베드 로그인)
  python -X utf8 scripts/openbanking.py --accounts
  python -X utf8 scripts/openbanking.py --fetch --person 아빠 --from 2026-01-01 --to 2026-09-30

★ 개인은 오픈뱅킹 이용기관으로 등록할 수 없습니다.
  최소 개인사업자가 있어야 하고 금융권 심사에 1~2개월이 걸립니다.
  개발자사이트 테스트베드는 개인도 가입해 쓸 수 있으니, 자격이 생기기 전까지는
  --mock 으로 흐름을 보고 --test 로 테스트베드를 두드려 보세요.

★ 은행 아이디·비밀번호를 이 프로그램이 받지 않습니다.
  로그인은 오픈뱅킹이 띄우는 자기네 화면에서 이루어지고,
  여기로는 권한을 위임받은 토큰만 돌아옵니다.

만들어지는 파일은 기존 은행 내역과 같은 모양이라 parse.py 가 그대로 읽습니다.
"""
import argparse
import csv
import datetime as dt
import json
import random
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

주소 = {
    "test": "https://testapi.openbanking.or.kr",     # 테스트베드 (개인도 가입 가능)
    "prod": "https://openapi.openbanking.or.kr",     # 운영 (이용기관 승인 필요)
}

설정파일 = "openbanking.json"      # client_id 등 (data/private/ 안에 둔다)
토큰파일 = "openbanking_token.json"

표준헤더 = ["거래일시", "적요", "출금액", "입금액", "잔액"]


# ============================================================================
def 설정읽기(자료: Path):
    p = 자료 / 설정파일
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def 설정뼈대(자료: Path):
    p = 자료 / 설정파일
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "client_id": "여기에 개발자사이트에서 받은 Client ID",
        "client_secret": "여기에 Client Secret",
        "redirect_uri": "http://localhost:8765/callback",
        "이용기관코드": "10자리 이용기관코드",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def 토큰읽기(자료: Path):
    p = 자료 / 토큰파일
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def 거래고유번호(이용기관코드: str, 순번: int) -> str:
    """이용기관코드(10) + 'U' + 일련번호(9). 호출마다 달라야 한다."""
    return f"{이용기관코드[:10]:0<10}U{순번:09d}"


def 부르기(url, 헤더=None, 몸통=None, 초=30):
    데이터 = urllib.parse.urlencode(몸통).encode() if 몸통 else None
    req = urllib.request.Request(url, data=데이터, headers=헤더 or {},
                                 method="POST" if 몸통 else "GET")
    try:
        with urllib.request.urlopen(req, timeout=초) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} — {e.read().decode('utf-8', 'replace')[:400]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ============================================================================
# 로그인 — 오픈뱅킹이 띄운 화면에서 사용자가 동의하면 code 가 돌아온다
# ============================================================================
받은code = {}


class 콜백받기(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        받은code.update({k: v[0] for k, v in q.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        됨 = "code" in 받은code
        self.wfile.write((
            "<!doctype html><meta charset='utf-8'>"
            "<div style=\"font-family:system-ui,'Malgun Gothic';padding:40px;text-align:center\">"
            f"<h2>{'연결됐습니다' if 됨 else '연결하지 못했습니다'}</h2>"
            "<p>이 창을 닫고 명령창으로 돌아가세요.</p></div>"
        ).encode("utf-8"))

    def log_message(self, *a):
        pass


def 로그인(설정, 기준, 자료: Path):
    redirect = 설정["redirect_uri"]
    조각 = urllib.parse.urlparse(redirect)
    포트 = 조각.port or 8765
    state = secrets.token_hex(16)

    질의 = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": 설정["client_id"],
        "redirect_uri": redirect,
        "scope": "login inquiry",          # 조회만. 이체 권한은 받지 않는다
        "state": state,
        "auth_type": "0",
    })
    url = f"{기준}/oauth/2.0/authorize?{질의}"

    서버 = HTTPServer(("127.0.0.1", 포트), 콜백받기)
    threading.Thread(target=서버.handle_request, daemon=True).start()

    print("브라우저에서 오픈뱅킹 로그인 화면이 열립니다.")
    print("은행 아이디·비밀번호는 이 프로그램이 아니라 오픈뱅킹 화면에 입력하세요.")
    print(f"\n안 열리면 아래 주소를 직접 여세요.\n{url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    print("동의를 기다리는 중… (창을 닫으면 취소됩니다)")
    for _ in range(600):
        if 받은code:
            break
        threading.Event().wait(0.5)
    서버.server_close()

    if "code" not in 받은code:
        print(f"[!] code 를 받지 못했습니다. 돌아온 값: {받은code or '없음'}")
        return 2
    if 받은code.get("state") != state:
        print("[!] state 가 맞지 않습니다. 중간에 가로채였을 수 있으니 다시 시도하세요.")
        return 2

    답, 오류 = 부르기(f"{기준}/oauth/2.0/token", 몸통={
        "code": 받은code["code"],
        "client_id": 설정["client_id"],
        "client_secret": 설정["client_secret"],
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    })
    if 오류:
        print(f"[!] 토큰을 받지 못했습니다. {오류}")
        return 1

    답["받은때"] = dt.datetime.now().isoformat(timespec="seconds")
    (자료 / 토큰파일).write_text(json.dumps(답, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n연결됐습니다. user_seq_no={답.get('user_seq_no')}")
    print(f"토큰을 {자료 / 토큰파일} 에 저장했습니다. (깃허브에 올라가지 않습니다)")
    return 0


# ============================================================================
# 가상 응답 — 이용기관 자격이 없어도 흐름 전체를 볼 수 있게 한다
# ============================================================================
def 가상계좌목록():
    return {"rsp_code": "A0000", "res_list": [
        {"fintech_use_num": "199000000000000000000001", "bank_name": "국민은행",
         "account_num_masked": "123456**7890", "account_alias": "급여통장",
         "account_holder_name": "홍길동"},
        {"fintech_use_num": "199000000000000000000002", "bank_name": "신한은행",
         "account_num_masked": "110***456789", "account_alias": "생활비통장",
         "account_holder_name": "홍길동"},
    ]}


def 가상거래내역(from_date: str, to_date: str, 씨=20260923):
    """실제 응답과 같은 필드 이름으로 만든다. 붙일 때 코드를 안 고쳐도 되게."""
    rng = random.Random(씨)
    시작 = dt.date.fromisoformat(from_date)
    끝 = dt.date.fromisoformat(to_date)
    가게 = [("이마트 트레이더스", 40000, 180000), ("스타벅스", 4500, 12000),
           ("배달의민족", 15000, 45000), ("GS칼텍스", 50000, 90000),
           ("올리브영", 15000, 60000), ("쿠팡", 10000, 80000),
           ("CU 편의점", 3000, 15000), ("교보문고", 12000, 40000)]
    고정 = [("SKT 통신요금", 132000, 5), ("행복아파트 관리비", 452000, 25),
           ("삼성생명 보험료", 380000, 15), ("넷플릭스", 17000, 8)]

    목록, 잔액 = [], 5_000_000
    날 = 시작
    while 날 <= 끝:
        if 날.day == 25:
            잔액 += 8_500_000
            목록.append({"tran_date": 날.strftime("%Y%m%d"), "tran_time": "090000",
                       "inout_type": "입금", "tran_type": "이체", "printed_content": "급여",
                       "tran_amt": "8500000", "after_balance_amt": str(잔액), "branch_name": ""})
        for 이름, 금액, 일 in 고정:
            if 날.day == 일:
                잔액 -= 금액
                목록.append({"tran_date": 날.strftime("%Y%m%d"), "tran_time": "080000",
                           "inout_type": "출금", "tran_type": "이체", "printed_content": 이름,
                           "tran_amt": str(금액), "after_balance_amt": str(잔액), "branch_name": ""})
        for _ in range(rng.randint(0, 3)):
            이름, 최소, 최대 = rng.choice(가게)
            금액 = rng.randrange(최소, 최대, 100)
            잔액 -= 금액
            목록.append({"tran_date": 날.strftime("%Y%m%d"),
                       "tran_time": f"{rng.randint(9, 21):02d}{rng.randint(0, 59):02d}00",
                       "inout_type": "출금", "tran_type": "카드", "printed_content": 이름,
                       "tran_amt": str(금액), "after_balance_amt": str(잔액), "branch_name": ""})
        날 += dt.timedelta(days=1)

    return {"rsp_code": "A0000", "rsp_message": "", "bank_name": "국민은행",
            "balance_amt": str(잔액), "page_record_cnt": str(len(목록)),
            "next_page_yn": "N", "res_list": 목록}


# ============================================================================
def 계좌목록(기준, 토큰, 설정):
    질의 = urllib.parse.urlencode({
        "user_seq_no": 토큰["user_seq_no"],
        "include_cancel_yn": "N",
        "sort_order": "D",
    })
    return 부르기(f"{기준}/v2.0/account/list?{질의}",
                헤더={"Authorization": f"Bearer {토큰['access_token']}"})


def 거래내역(기준, 토큰, 설정, 핀테크번호, from_date, to_date, 순번=1):
    질의 = urllib.parse.urlencode({
        "bank_tran_id": 거래고유번호(설정["이용기관코드"], 순번),
        "fintech_use_num": 핀테크번호,
        "inquiry_type": "A",            # A: 전체 (입금+출금)
        "inquiry_base": "D",            # D: 날짜 기준
        "from_date": from_date.replace("-", ""),
        "to_date": to_date.replace("-", ""),
        "sort_order": "D",
        "tran_dtime": dt.datetime.now().strftime("%Y%m%d%H%M%S"),
    })
    return 부르기(f"{기준}/v2.0/account/transaction_list/fin_num?{질의}",
                헤더={"Authorization": f"Bearer {토큰['access_token']}"})


def CSV로쓰기(답: dict, 경로: Path):
    """오픈뱅킹 응답을 기존 은행 내역과 같은 모양으로 저장한다."""
    줄 = []
    for t in 답.get("res_list", []):
        d = t.get("tran_date", "")
        날짜 = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d
        금액 = t.get("tran_amt", "0")
        입금 = t.get("inout_type", "") == "입금"
        줄.append([날짜, t.get("printed_content", "").strip(),
                  "" if 입금 else 금액, 금액 if 입금 else "",
                  t.get("after_balance_amt", "")])
    경로.parent.mkdir(parents=True, exist_ok=True)
    with open(경로, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(표준헤더)
        w.writerows(줄)
    return len(줄)


# ============================================================================
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="오픈뱅킹에서 거래내역을 받아옵니다.")
    ap.add_argument("--data", default="data/private", help="설정·토큰을 둘 폴더")
    ap.add_argument("--out", default="data/private", help="CSV 를 떨굴 폴더")
    ap.add_argument("--person", default="나", help="사람 폴더 이름")
    ap.add_argument("--mock", action="store_true", help="가상 응답으로 흐름만 본다 (기본)")
    ap.add_argument("--test", action="store_true", help="테스트베드에 실제로 붙는다")
    ap.add_argument("--prod", action="store_true", help="운영계에 붙는다 (이용기관 승인 필요)")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--accounts", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--fin", help="핀테크이용번호 (없으면 첫 계좌)")
    ap.add_argument("--from", dest="from_date", default="")
    ap.add_argument("--to", dest="to_date", default="")
    ap.add_argument("--init", action="store_true", help="설정 파일 뼈대를 만든다")
    args = ap.parse_args()

    자료 = Path(args.data)
    모드 = "prod" if args.prod else ("test" if args.test else "mock")
    기준 = 주소.get(모드, 주소["test"])

    if args.init:
        p = 설정뼈대(자료)
        print(f"설정 뼈대를 만들었습니다: {p}")
        print("개발자사이트(developers.kftc.or.kr)에서 받은 값으로 채워주세요.")
        print("이 파일은 깃허브에 올라가지 않습니다.")
        return 0

    오늘 = dt.date.today()
    from_date = args.from_date or (오늘 - dt.timedelta(days=90)).isoformat()
    to_date = args.to_date or 오늘.isoformat()

    # ---------------- 가상 모드 ----------------
    if 모드 == "mock":
        print("가상 모드입니다. 인터넷에 연결하지 않고 응답 모양만 흉내 냅니다.")
        print("실제로 붙이려면 --test (테스트베드) 또는 --prod (운영) 를 쓰세요.\n")
        if args.accounts or not (args.fetch or args.login):
            for a in 가상계좌목록()["res_list"]:
                print(f"  {a['bank_name']} {a['account_num_masked']} "
                      f"({a['account_alias']}) → {a['fintech_use_num']}")
            print()
        if args.fetch or not (args.accounts or args.login):
            답 = 가상거래내역(from_date, to_date)
            경로 = Path(args.out) / args.person / "오픈뱅킹_국민은행.csv"
            n = CSV로쓰기(답, 경로)
            print(f"{from_date} ~ {to_date} / 거래 {n}건")
            print(f"저장: {경로}")
            print(f"\n이제 python -X utf8 scripts/parse.py --input {args.out} 로 읽을 수 있습니다.")
        return 0

    # ---------------- 실제 모드 ----------------
    설정 = 설정읽기(자료)
    if not 설정 or "여기에" in 설정.get("client_id", ""):
        print(f"[!] 설정이 없습니다. 먼저 --init 으로 뼈대를 만들고 채워주세요.")
        print(f"    {자료 / 설정파일}")
        return 2

    print(f"모드: {모드} ({기준})")

    if args.login:
        return 로그인(설정, 기준, 자료)

    토큰 = 토큰읽기(자료)
    if not 토큰:
        print("[!] 아직 로그인하지 않았습니다. --login 을 먼저 실행하세요.")
        return 2

    if args.accounts:
        답, 오류 = 계좌목록(기준, 토큰, 설정)
        if 오류:
            print(f"[!] {오류}")
            return 1
        if 답.get("rsp_code") not in ("A0000", None):
            print(f"[!] {답.get('rsp_code')} {답.get('rsp_message')}")
            return 1
        for a in 답.get("res_list", []):
            print(f"  {a.get('bank_name')} {a.get('account_num_masked')} "
                  f"({a.get('account_alias', '')}) → {a.get('fintech_use_num')}")
        return 0

    if args.fetch:
        핀 = args.fin
        if not 핀:
            답, 오류 = 계좌목록(기준, 토큰, 설정)
            if 오류 or not 답.get("res_list"):
                print(f"[!] 계좌를 찾지 못했습니다. {오류 or ''}")
                return 1
            핀 = 답["res_list"][0]["fintech_use_num"]
            print(f"계좌를 지정하지 않아 첫 계좌를 씁니다: {핀}")

        답, 오류 = 거래내역(기준, 토큰, 설정, 핀, from_date, to_date)
        if 오류:
            print(f"[!] {오류}")
            return 1
        if 답.get("rsp_code") not in ("A0000", None):
            print(f"[!] {답.get('rsp_code')} {답.get('rsp_message')}")
            print("    금융결제원 응답코드를 개발자사이트에서 확인해 보세요.")
            return 1

        은행 = 답.get("bank_name", "은행").replace("/", "_")
        경로 = Path(args.out) / args.person / f"오픈뱅킹_{은행}.csv"
        n = CSV로쓰기(답, 경로)
        print(f"{from_date} ~ {to_date} / 거래 {n}건 / 잔액 {답.get('balance_amt', '?')}")
        print(f"저장: {경로}")
        if 답.get("next_page_yn") == "Y":
            print("더 있습니다. 기간을 나눠 다시 받아주세요.")
        return 0

    print("할 일을 지정하세요: --login / --accounts / --fetch  (또는 --mock)")
    return 2


if __name__ == "__main__":
    sys.exit(main())

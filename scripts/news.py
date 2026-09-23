# -*- coding: utf-8 -*-
"""
보유 종목의 오늘 소식을 제목·언론사·링크로 모아 둔다.

  python -X utf8 scripts/news.py                    (키워드는 규칙으로)
  python -X utf8 scripts/news.py --ai               (키워드를 AI가 다듬음, 1회 약 1원)
  python -X utf8 scripts/news.py --data data/private

★ 기사 본문을 가져오거나 요약하지 않습니다.
  제목·언론사·날짜·링크만 모으고, 자세한 내용은 원문으로 보냅니다.
  본문을 옮겨 적는 것은 저작권 문제가 됩니다.

구글 뉴스 RSS 를 씁니다. 인증키가 필요 없습니다.
"""
import argparse
import datetime as dt
import html as htmlmod
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from advise import 기본모델, 돈계산, 키찾기, 표읽기  # noqa: E402

RSS = "https://news.google.com/rss/search"
가져올건수 = 6
멈춤말 = {"관련", "종목", "주가", "오늘", "속보", "단독", "종합", "그래픽", "영상"}

# 검색어와 상관없는 기사가 섞여 들어온다. 제목에 이름이 든 것만 남기려고 쓰는 표다.
# 집에서 다른 종목을 넣었는데 기사가 텅 비면 여기에 별칭을 한 줄 더 적으면 된다.
# 블로그·카페 글은 언론 기사가 아니라서 걸러낸다.
막을출처 = ("blog", "블로그", "cafe", "카페", "tistory", "brunch", "post")

종목별칭 = {
    "NAVER": ["네이버"],
    "LG에너지솔루션": ["LG엔솔", "엘지에너지솔루션"],
    "SK하이닉스": ["하이닉스"],
    "현대차": ["현대자동차"],
}


def 기사읽기(검색어: str, 건수=가져올건수):
    질의 = urllib.parse.urlencode({"q": 검색어, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    req = urllib.request.Request(f"{RSS}?{질의}", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            글 = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"

    나온것 = []
    for 조각 in re.findall(r"<item>(.*?)</item>", 글, re.S)[: 건수 * 2]:
        def 뽑기(태그):
            m = re.search(rf"<{태그}[^>]*>(.*?)</{태그}>", 조각, re.S)
            return htmlmod.unescape(re.sub(r"<[^>]+>", "", m.group(1)).strip()) if m else ""

        제목 = 뽑기("title")
        출처 = 뽑기("source")
        if 출처 and 제목.endswith(f"- {출처}"):
            제목 = 제목[: -len(출처) - 2].strip()
        날 = 뽑기("pubDate")
        try:
            날 = dt.datetime.strptime(날[:16], "%a, %d %b %Y").strftime("%Y-%m-%d")
        except ValueError:
            날 = 날[:16]
        나온것.append({"제목": 제목, "출처": 출처, "날짜": 날, "링크": 뽑기("link")})
        if len(나온것) >= 건수:
            break
    return 나온것, None


def 골라내기(이름: str, 기사들: list) -> list:
    """제목에 종목 이름이 들어간 기사만 남긴다.

    구글 뉴스는 'NAVER' 로 찾아도 엉뚱한 기사를 섞어 준다.
    다 걸러져 한 건도 안 남으면(이름이 제목에 잘 안 쓰이는 ETF 등) 원래 목록을 그대로 둔다.
    """
    납작 = lambda s: re.sub(r"[\s\-·,'\"]", "", s).lower()
    후보 = [납작(x) for x in [이름] + 종목별칭.get(이름, [])]
    기사들 = [a for a in 기사들
            if not any(w in (a.get("출처") or "").lower() for w in 막을출처)]
    남길것 = []
    for a in 기사들:
        # 네이버 블로그 제목은 끝에 ' : 네이버' 가 붙는다. 이름이 나온 걸로 치지 않는다.
        제목 = re.sub(r"[\s:\-]*(네이버|naver)\s*$", "", a["제목"], flags=re.I)
        if any(c in 납작(제목) for c in 후보):
            남길것.append(a)
    return 남길것 or 기사들


def 규칙키워드(제목: str) -> str:
    """AI 없이도 쓸 수 있게, 제목에서 핵심으로 보이는 토막을 뽑는다."""
    글 = re.sub(r"[\"'“”‘’\[\]<>…]", " ", 제목)
    글 = re.split(r"…|\.\.\.| - ", 글)[0]          # 쉼표로는 자르지 않는다. 너무 짧아진다
    낱말 = [w for w in 글.split() if len(w) >= 2 and w not in 멈춤말]
    키 = " ".join(낱말[:7]) if 낱말 else 제목[:24]
    return 키[:34]


def AI키워드(키, 모델, 제목들):
    """제목을 12~22글자 한 줄로 줄인다. 실패하면 규칙으로 돌아간다."""
    from advise import 부르기
    스키마 = {"type": "object", "properties": {"키워드": {"type": "array", "items": {
        "type": "object", "properties": {"번호": {"type": "integer"},
                                         "키워드": {"type": "string"}},
        "required": ["번호", "키워드"]}}}, "required": ["키워드"]}
    지시 = ("뉴스 제목을 한 줄로 줄입니다. 그 줄만 읽고도 무슨 일인지 짐작이 가야 합니다.\n"
           "- 18~30글자. 15글자 아래로 줄이지 않습니다. 짧으면 무슨 소린지 모릅니다.\n"
           "- 누가 · 무엇을 · 어떻게가 드러나게 씁니다.\n"
           "- 제목에 있는 낱말을 그대로 가져다 씁니다. 비슷한 말로 바꾸지 않습니다.\n"
           "  ('세계 최초' 를 '업계 최초' 로, 'SOXL' 을 '속슬' 로 바꾸면 안 됩니다.)\n"
           "- 좋고 나쁨을 판단하거나 앞으로 오를지 내릴지 덧붙이지 않습니다.\n"
           "- 상향·하향·급등·급락·호재·악재 같은 방향을 나타내는 말은 제목에 그 말이 있을 때만 씁니다.\n"
           "  제목이 '목표주가 63만원' 이라고만 했으면 오른 것인지 내린 것인지 알 수 없으므로 그대로 적습니다.\n"
           "- 예: '추석 앞두고 삼성전자 냉장고 잇단 먹통…긴급 복구 중'\n"
           "      -> '삼성전자 냉장고 먹통, 추석에도 긴급 복구' (21글자)\n"
           "- 예: 'SK하이닉스 신입사원 4명 해고…인생에서 가장 비싼 술'\n"
           "      -> 'SK하이닉스 신입사원 4명 해고, 인생서 가장 비싼 술' (26글자)")
    질문 = "\n".join(f"{i}. {t}" for i, t in enumerate(제목들))
    몸통 = {
        "systemInstruction": {"parts": [{"text": 지시}]},
        "contents": [{"role": "user", "parts": [{"text": 질문}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 3000,
                             "thinkingConfig": {"thinkingBudget": 0},
                             "responseMimeType": "application/json",
                             "responseSchema": 스키마},
    }
    답, 오류 = 부르기(키, 모델, 몸통, 초=90)
    if 오류:
        return None, 오류, {}
    try:
        결과 = json.loads(답["candidates"][0]["content"]["parts"][0]["text"])
        표 = {x["번호"]: x["키워드"].strip()[:40] for x in 결과.get("키워드", [])}
        return 표, None, 답.get("usageMetadata", {})
    except Exception as e:
        return None, f"{type(e).__name__}", 답.get("usageMetadata", {})


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="보유 종목의 소식을 제목·링크로 모읍니다.")
    ap.add_argument("--data", default="data/sample")
    ap.add_argument("--out", default="")
    ap.add_argument("--model", default=기본모델)
    ap.add_argument("--ai", action="store_true", help="키워드를 AI가 다듬는다")
    ap.add_argument("--limit", type=int, default=가져올건수)
    args = ap.parse_args()

    자료 = Path(args.data)
    종목들 = []
    for r in 표읽기(자료 / "보유종목.csv"):
        이름 = (r.get("종목명") or "").strip()
        if 이름 and 이름 not in 종목들:
            종목들.append(이름)

    if not 종목들:
        print(f"[!] 보유종목.csv 가 없거나 비어 있습니다: {자료 / '보유종목.csv'}")
        return 3

    print(f"종목 {len(종목들)}개의 소식을 찾습니다. (구글 뉴스 RSS · 인증키 없음)")
    모음, 제목모음 = {}, []
    for 이름 in 종목들:
        기사, 오류 = 기사읽기(이름, args.limit)
        if 오류:
            print(f"  {이름:<20} 실패 — {오류}")
            continue
        받은건수 = len(기사)
        기사 = 골라내기(이름, 기사)
        for a in 기사:
            a["키워드"] = 규칙키워드(a["제목"])
            제목모음.append((이름, a))
        모음[이름] = 기사
        뺀것 = 받은건수 - len(기사)
        print(f"  {이름:<20} {len(기사)}건" + (f" (이름이 안 나온 {뺀것}건 제외)" if 뺀것 else ""))

    if args.ai and 제목모음:
        키, 어디 = 키찾기(자료)
        if not 키:
            print("\n[!] AI 키가 없어 규칙으로 만든 키워드를 그대로 씁니다.")
        else:
            print(f"\n키워드를 다듬는 중… ({어디})")
            표, 오류, 쓴것 = AI키워드(키, args.model, [a["제목"] for _, a in 제목모음])
            if 오류:
                print(f"  다듬지 못했습니다({오류}). 규칙으로 만든 것을 씁니다.")
            else:
                for i, (_, a) in enumerate(제목모음):
                    if i in 표 and 표[i]:
                        a["키워드"] = 표[i]
                입 = 쓴것.get("promptTokenCount", 0)
                출 = 쓴것.get("candidatesTokenCount", 0)
                달러, 원 = 돈계산(args.model, 입, 출)
                print(f"  토큰 입력 {입} / 출력 {출} · 약 {원:.2f}원")

    # 같은 사건을 여러 언론사가 쓰면 키워드가 겹친다. 먼저 나온 것만 남긴다.
    for 이름, 기사 in 모음.items():
        # 종목 이름은 어느 키워드에나 들어 있으므로 겹침 계산에서 뺀다.
        # 빼지 않으면 서로 다른 사건까지 같은 것으로 묶여 기사가 두세 건만 남는다.
        빼기 = {w.lower() for x in [이름] + 종목별칭.get(이름, []) for w in x.split()}
        본것, 남길것 = [], []
        for a in 기사:
            낱말 = {w for w in a["키워드"].replace(",", " ").split()
                  if len(w) >= 2 and w.lower() not in 빼기}
            if any(len(낱말 & 앞) >= 2 for 앞 in 본것):
                continue                      # 같은 사건을 다른 언론사가 쓴 것
            본것.append(낱말)
            남길것.append(a)
        모음[이름] = 남길것

    출력 = Path(args.out) if args.out else 자료 / "뉴스.json"
    출력.parent.mkdir(parents=True, exist_ok=True)
    출력.write_text(json.dumps(
        {"받은때": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "종목": 모음},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n저장: {출력}")
    보기 = [(이름, a) for 이름, 기사 in 모음.items() for a in 기사][:6]
    if 보기:
        print("\n키워드 미리보기")
        for 이름, a in 보기:
            print(f"  [{a['키워드']}] {이름} — {a['제목'][:44]} ({a['출처']})")
    print("\n이제 python -X utf8 scripts/report.py 를 돌리면 종목 상세에 들어갑니다.")
    print("기사 본문은 가져오지 않습니다. 자세한 내용은 원문 링크로 보세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

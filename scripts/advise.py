# -*- coding: utf-8 -*-
"""
집계한 숫자를 구글 제미나이에 보내 소비 패턴 분석을 받아온다.

  python -X utf8 scripts/advise.py
  python -X utf8 scripts/advise.py --data data/private --force
  python -X utf8 scripts/advise.py --models          (내 키로 쓸 수 있는 모델 보기)

★ 이 기능을 켜면 집계한 숫자가 구글 서버로 나갑니다.
  거래 하나하나나 가맹점 이름, 계좌·증권번호는 보내지 않습니다.
  보내는 내용은 --dry 로 미리 볼 수 있습니다.

키는 코드나 저장소에 넣지 않습니다. 둘 중 하나로 넣으세요.
  1) 환경변수  GEMINI_API_KEY
  2) 파일      data/private/gemini.key   (깃허브에 올라가지 않음)
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

# 이 정도 분석에 비싼 모델은 필요 없다. 값싼 모델로도 결과가 거의 같다.
기본모델 = "gemini-3.1-flash-lite"

# 100만 토큰당 미국 달러 (입력, 출력). 2026-12-31 까지 기준이며 2027-01-01 에 오른다.
단가표 = {
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-flash":      (0.75, 3.75),
    "gemini-3.5-flash":      (1.50, 9.00),
}
환율 = 1350          # 대략적인 원/달러. 얼마나 드는지 감을 잡는 용도다.


def 돈계산(모델, 입력, 출력):
    입단, 출단 = 단가표.get(모델, (0.75, 3.75))
    달러 = 입력 / 1_000_000 * 입단 + 출력 / 1_000_000 * 출단
    return 달러, 달러 * 환율
API = "https://generativelanguage.googleapis.com/v1beta/models"

출력상한 = 1000          # 답변이 길어질수록 돈이 든다. 짧게 받는다.
요약항목수 = 8          # 목록마다 상위 몇 개만 보낼지


# ============================================================================
def 키찾기(자료폴더: Path):
    키 = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if 키:
        return 키, "환경변수 GEMINI_API_KEY"
    for 후보 in (자료폴더 / "gemini.key", Path("data/private/gemini.key")):
        if 후보.exists():
            값 = 후보.read_text(encoding="utf-8").strip()
            if 값:
                return 값, str(후보)
    return None, None


def 부르기(키: str, 모델: str, 몸통: dict, 초=60):
    req = urllib.request.Request(
        f"{API}/{모델}:generateContent",
        data=json.dumps(몸통, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": 키},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=초, context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        본문 = e.read().decode("utf-8", errors="replace")
        try:
            메시지 = json.loads(본문)["error"].get("message", "")
        except Exception:
            메시지 = 본문[:300]
        return None, f"HTTP {e.code} — {메시지}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ============================================================================
def 표읽기(path: Path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def 요약만들기(거래표: Path, 자료폴더: Path):
    """거래 하나하나가 아니라 합계만 추린다. 이게 토큰을 아끼는 핵심이다."""
    행 = 표읽기(거래표)
    if not 행:
        return None

    월, 수혜자, 카테고리, 월카 = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    수입 = 0
    for r in 행:
        금 = int(r["금액"])
        m = r["날짜"][:7]
        if r["구분"] == "지출":
            월[m] += -금
            수혜자[(r.get("수혜자") or r["사람"]).split("_")[0]] += -금
            카테고리[r["카테고리"]] += -금
            월카[(m, r["카테고리"])] += -금
        elif r["구분"] == "수입":
            수입 += 금

    달들 = sorted(월)
    개월 = max(1, len(달들))
    총지출 = sum(월.values())

    변화 = []
    if len(달들) >= 2:
        이번, 지난 = 달들[-1], 달들[-2]
        for c in {c for (m, c) in 월카}:
            d = 월카.get((이번, c), 0) - 월카.get((지난, c), 0)
            if d:
                변화.append([c, d])
        변화.sort(key=lambda x: -abs(x[1]))

    # 고정비: 매달 빠짐없이 한 번씩, 금액이 거의 같은 것
    그룹 = defaultdict(list)
    for r in 행:
        if r["구분"] == "지출":
            그룹[r["가맹점"]].append((r["날짜"][:7], -int(r["금액"])))
    고정 = []
    for 이름, ts in 그룹.items():
        달수 = {m for m, _ in ts}
        if len(달수) == 개월 and len(ts) == 개월 and 개월 >= 3:
            금액들 = [v for _, v in ts]
            평균 = sum(금액들) / len(금액들)
            if 평균 > 0 and (max(금액들) - min(금액들)) / 평균 <= 0.12:
                고정.append([이름, round(평균)])
    고정.sort(key=lambda x: -x[1])

    자산 = defaultdict(int)
    for r in 표읽기(자료폴더 / "자산.csv"):
        try:
            자산[(r.get("분류") or "기타").strip()] += int(str(r.get("평가금액", "")).replace(",", "") or 0)
        except ValueError:
            pass

    보험료 = 0
    for r in 표읽기(자료폴더 / "보험.csv"):
        try:
            보험료 += int(str(r.get("월보험료", "")).replace(",", "") or 0)
        except ValueError:
            pass

    def 위(d, n=요약항목수):
        return [[k, v] for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:n]]

    return {
        "기간": f"{달들[0]}~{달들[-1]}",
        "월평균지출": round(총지출 / 개월),
        "월평균수입": round(수입 / 개월),
        "월별지출": [[m, 월[m]] for m in 달들],
        "누구몫": 위(수혜자),
        "카테고리": 위(카테고리),
        "고정비": 고정[:요약항목수],
        "지난달대비": 변화[:5],
        "자산": dict(자산),
        "월보험료": 보험료,
    }


# ============================================================================
지시 = """당신은 가계부 데이터를 읽고 설명하는 분석가입니다. 한국어 존댓말로 씁니다.

지켜야 할 것
- 주어진 숫자만 씁니다. 숫자를 지어내지 않습니다. 계산은 주어진 값 안에서만 합니다.
- 투자(무엇을 사라/팔라/비중을 얼마로)와 보험 가입·해지를 권하지 않습니다.
- 특정 금융상품 이름을 추천하지 않습니다.
- "절약하세요" 같은 뻔한 말 대신, 이 집 숫자에서만 나오는 이야기를 씁니다.
- 한 항목은 두 문장을 넘기지 않습니다. 짧게 씁니다.
- 가치판단(낭비다, 과하다)을 단정하지 않습니다. 사실과 비교를 보여주고 판단은 사용자에게 맡깁니다.

금액은 만원 단위로 반올림해 읽기 쉽게 씁니다. 예: 1,248만원"""

스키마 = {
    "type": "object",
    "properties": {
        "한줄": {"type": "string"},
        "발견": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "제목": {"type": "string"},
                    "설명": {"type": "string"},
                },
                "required": ["제목", "설명"],
            },
        },
        "살펴볼점": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "제목": {"type": "string"},
                    "설명": {"type": "string"},
                    "규모": {"type": "string"},
                },
                "required": ["제목", "설명"],
            },
        },
    },
    "required": ["한줄", "발견", "살펴볼점"],
}


def 몸통만들기(요약: dict):
    질문 = (
        "아래는 한 가구의 12개월 가계 집계입니다. 금액 단위는 원입니다.\n"
        f"{json.dumps(요약, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "1) 한줄: 이 집 소비를 한 문장으로.\n"
        "2) 발견: 숫자에서 눈에 띄는 패턴 3가지. 계절 변화나 쏠린 항목처럼 "
        "표만 봐서는 지나치기 쉬운 것을 짚어주세요.\n"
        "3) 살펴볼점: 사용자가 직접 확인해볼 만한 것 3가지. "
        "규모에는 해당 금액을 적으세요(예: 월 27만원). 권유가 아니라 확인거리로 씁니다."
    )
    return {
        "systemInstruction": {"parts": [{"text": 지시}]},
        "contents": [{"role": "user", "parts": [{"text": 질문}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 출력상한,
            # Gemini 3.x 는 답하기 전에 '생각'에 토큰을 먼저 쓴다.
            # 이 정도 분석에는 필요 없고, 끄면 답이 잘리지도 않는다.
            "thinkingConfig": {"thinkingBudget": 0},
            "responseMimeType": "application/json",
            "responseSchema": 스키마,
        },
    }


# ============================================================================
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="집계 요약으로 소비 패턴 분석을 받아옵니다.")
    ap.add_argument("--input", default="out/거래통합.csv")
    ap.add_argument("--data", default="data/sample")
    ap.add_argument("--output", default="out/ai_조언.json")
    ap.add_argument("--model", default=기본모델)
    ap.add_argument("--force", action="store_true", help="내용이 그대로여도 다시 물어본다")
    ap.add_argument("--dry", action="store_true", help="보낼 내용만 보고 호출하지 않는다")
    ap.add_argument("--models", action="store_true", help="쓸 수 있는 모델을 보여준다")
    args = ap.parse_args()

    자료 = Path(args.data)
    키, 어디 = 키찾기(자료)

    if args.models:
        if not 키:
            print("[!] 키가 없습니다. GEMINI_API_KEY 환경변수나 data/private/gemini.key 에 넣어주세요.")
            return 2
        req = urllib.request.Request(f"{API}?pageSize=200", headers={"x-goog-api-key": 키})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        for m in d.get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                print(" ", m["name"].split("/")[-1])
        return 0

    요약 = 요약만들기(Path(args.input), 자료)
    if 요약 is None:
        print(f"[!] 거래표가 없습니다: {args.input}")
        print("    먼저 python -X utf8 scripts/parse.py 를 실행하세요.")
        return 3

    보낼글 = json.dumps(요약, ensure_ascii=False, separators=(",", ":"))
    지문 = hashlib.sha256((보낼글 + args.model).encode("utf-8")).hexdigest()[:16]
    글자수 = len(보낼글) + len(지시)

    print(f"보낼 내용: 집계 요약 {len(보낼글):,}자 (거래 하나하나는 보내지 않습니다)")
    print(f"대략 {글자수//2:,}토큰 정도 들어가고, 답변은 {출력상한}토큰에서 끊습니다.")

    if args.dry:
        print("\n--- 실제로 보내는 내용 ---")
        print(json.dumps(요약, ensure_ascii=False, indent=2))
        return 0

    출력 = Path(args.output)
    if 출력.exists() and not args.force:
        try:
            기존 = json.loads(출력.read_text(encoding="utf-8"))
            if 기존.get("지문") == 지문:
                print("\n요약이 지난번과 같아서 다시 묻지 않았습니다. (토큰 0)")
                print("    다시 받으려면 --force 를 붙이세요.")
                print(f"\n그대로 둡니다: {출력}")
                return 0
        except Exception:
            pass

    if not 키:
        print("\n[!] 키를 찾지 못했습니다. 둘 중 하나로 넣어주세요.")
        print("    1) 환경변수:  setx GEMINI_API_KEY \"내키\"   (창을 새로 연 뒤 실행)")
        print("    2) 파일:      data/private/gemini.key 에 키만 한 줄로 저장")
        print("    키는 깃허브에 올라가지 않습니다.")
        return 2

    print(f"키: {어디} / 모델: {args.model}")
    print("구글에 물어보는 중…")
    몸통 = 몸통만들기(요약)
    답, 오류 = 부르기(키, args.model, 몸통)
    if 오류 and "invalid argument" in 오류.lower():
        몸통["generationConfig"].pop("thinkingConfig", None)
        답, 오류 = 부르기(키, args.model, 몸통)
    if 오류:
        print(f"\n[!] 실패했습니다. {오류}")
        if "API key" in (오류 or "") or "401" in (오류 or "") or "403" in (오류 or ""):
            print("    키가 맞는지, AI Studio 에서 살아 있는지 확인해 주세요.")
        if "404" in (오류 or ""):
            print(f"    '{args.model}' 모델이 없을 수 있습니다. --models 로 목록을 확인하세요.")
        return 1

    try:
        글 = 답["candidates"][0]["content"]["parts"][0]["text"]
        결과 = json.loads(글)
    except Exception as e:
        print(f"\n[!] 답을 읽지 못했습니다. ({type(e).__name__})")
        print(json.dumps(답, ensure_ascii=False)[:500])
        return 1

    쓴토큰 = 답.get("usageMetadata", {})
    결과["지문"] = 지문
    결과["모델"] = args.model
    출력.parent.mkdir(parents=True, exist_ok=True)
    출력.write_text(json.dumps(결과, ensure_ascii=False, indent=2), encoding="utf-8")

    입력수 = 쓴토큰.get("promptTokenCount", 0)
    출력수 = 쓴토큰.get("candidatesTokenCount", 0)
    달러, 원 = 돈계산(args.model, 입력수, 출력수)

    기록파일 = 출력.parent / "ai_사용량.json"
    try:
        기록 = json.loads(기록파일.read_text(encoding="utf-8"))
    except Exception:
        기록 = []
    기록.append({"때": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "모델": args.model,
               "입력": 입력수, "출력": 출력수, "원": round(원, 2)})
    기록 = 기록[-500:]
    기록파일.write_text(json.dumps(기록, ensure_ascii=False, indent=1), encoding="utf-8")

    이번달 = dt.datetime.now().strftime("%Y-%m")
    달합 = sum(x["원"] for x in 기록 if x["때"].startswith(이번달))
    달횟수 = sum(1 for x in 기록 if x["때"].startswith(이번달))

    print(f"\n들어간 토큰: 입력 {입력수} / 출력 {출력수} / 합계 {쓴토큰.get('totalTokenCount', '?')}")
    print(f"이번 호출 비용: 약 {원:.2f}원 (${달러:.5f})")
    print(f"{이번달} 누적: {달횟수}회 · 약 {달합:.0f}원  (월 한도 1,000원 기준 "
          f"{max(0, int((1000 - 달합) / max(원, 0.01)))}회 더 가능)")
    print(f"\n{결과.get('한줄', '')}")
    for x in 결과.get("발견", []):
        print(f"  · {x.get('제목', '')}")
    for x in 결과.get("살펴볼점", []):
        print(f"  ? {x.get('제목', '')} {('— ' + x['규모']) if x.get('규모') else ''}")
    print(f"\n저장: {출력}")
    print("이제 python -X utf8 scripts/report.py 를 다시 돌리면 대시보드에 들어갑니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

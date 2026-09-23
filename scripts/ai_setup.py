# -*- coding: utf-8 -*-
"""
손으로 적어야 하던 설정을 AI에게 한 번 물어보고 규칙 파일로 굳힌다.

  python -X utf8 scripts/ai_setup.py --categories        미분류 가맹점 분류
  python -X utf8 scripts/ai_setup.py --who               누구 몫인지 추정
  python -X utf8 scripts/ai_setup.py --policy 증권1.jpg 증권2.pdf   증권 → 보험.csv

★ AI 는 한 번만 판단하고, 그 판단은 CSV 로 저장된다.
  다음 달부터는 저장된 규칙이 일하므로 토큰이 들지 않는다.
★ 결과는 모두 `_초안.csv` 로 저장된다. 사람이 확인하고 이름을 바꿔야 쓰인다.
  AI 가 잘못 넣은 것을 모르고 쓰는 일이 없게 하려는 것이다.
"""
import argparse
import base64
import csv
import json
import mimetypes
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from advise import API, 기본모델, 돈계산, 부르기, 키찾기, 표읽기  # noqa: E402

출력상한 = 2000


def 물어보기(키, 모델, 조각들, 스키마, 지시, 온도=0.2):
    몸통 = {
        "systemInstruction": {"parts": [{"text": 지시}]},
        "contents": [{"role": "user", "parts": 조각들}],
        "generationConfig": {
            "temperature": 온도,
            "maxOutputTokens": 출력상한,
            "thinkingConfig": {"thinkingBudget": 0},
            "responseMimeType": "application/json",
            "responseSchema": 스키마,
        },
    }
    답, 오류 = 부르기(키, 모델, 몸통, 초=120)
    if 오류 and "invalid argument" in 오류.lower():
        몸통["generationConfig"].pop("thinkingConfig", None)
        답, 오류 = 부르기(키, 모델, 몸통, 초=120)
    if 오류:
        return None, 오류, {}
    try:
        글 = 답["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(글), None, 답.get("usageMetadata", {})
    except Exception as e:
        return None, f"답을 읽지 못했습니다 ({type(e).__name__})", 답.get("usageMetadata", {})


def 비용알림(모델, 쓴것):
    입, 출 = 쓴것.get("promptTokenCount", 0), 쓴것.get("candidatesTokenCount", 0)
    달러, 원 = 돈계산(모델, 입, 출)
    print(f"토큰 입력 {입} / 출력 {출} · 약 {원:.2f}원 (${달러:.5f})")


def 초안쓰기(경로: Path, 머리, 줄들):
    경로.parent.mkdir(parents=True, exist_ok=True)
    with open(경로, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(머리)
        w.writerows(줄들)
    print(f"\n저장: {경로}")
    print("확인하신 뒤 이름에서 '_초안'을 떼면 도구가 읽습니다.")


# ============================================================================
# 1. 미분류 가맹점 분류
# ============================================================================
카테고리들 = ["식비", "장보기", "교육", "교통", "의료", "주거", "통신비", "보험",
           "쇼핑", "문화", "여가", "생활", "운동", "구독", "수입", "이체", "기타"]


def 카테고리작업(키, 모델, 거래표: Path, 자료: Path):
    행 = 표읽기(거래표)
    if not 행:
        print(f"[!] 거래표가 없습니다: {거래표}")
        return 3
    미분류 = Counter(r["가맹점"] for r in 행 if r.get("카테고리") in ("기타", "", None))
    if not 미분류:
        print("분류가 안 된 가맹점이 없습니다. 물어볼 것이 없네요.")
        return 0

    이름들 = [n for n, _ in 미분류.most_common(120)]
    print(f"분류가 안 된 가맹점 {len(미분류)}종류 중 {len(이름들)}개를 물어봅니다.")

    스키마 = {"type": "object", "properties": {"분류": {"type": "array", "items": {
        "type": "object", "properties": {
            "가맹점": {"type": "string"},
            "카테고리": {"type": "string", "enum": 카테고리들},
        }, "required": ["가맹점", "카테고리"]}}}, "required": ["분류"]}

    지시 = ("한국 카드·은행 내역의 가맹점 이름을 보고 어느 카테고리인지 고르는 일을 합니다.\n"
           f"카테고리는 다음 중에서만 고릅니다: {', '.join(카테고리들)}\n"
           "확실하지 않으면 '기타'로 둡니다. 억지로 맞추지 않습니다.\n"
           "가맹점 이름은 입력 그대로 돌려줍니다. 고치거나 줄이지 않습니다.")
    질문 = "다음 가맹점을 분류해 주세요.\n" + "\n".join(이름들)

    답, 오류, 쓴것 = 물어보기(키, 모델, [{"text": 질문}], 스키마, 지시)
    if 오류:
        print(f"[!] {오류}")
        return 1
    비용알림(모델, 쓴것)

    줄 = [[x["가맹점"], x["카테고리"]] for x in 답.get("분류", [])
         if x.get("카테고리") != "기타"]
    기타수 = len(답.get("분류", [])) - len(줄)
    print(f"\n분류됨 {len(줄)}개" + (f" · 판단 보류 {기타수}개" if 기타수 else ""))
    for a, b in 줄[:10]:
        print(f"  {a} → {b}")
    if len(줄) > 10:
        print(f"  … 외 {len(줄)-10}개")
    초안쓰기(자료 / "카테고리규칙_초안.csv", ["가맹점", "카테고리"], 줄)
    return 0


# ============================================================================
# 2. 누구 몫인지 추정
# ============================================================================
def 수혜자작업(키, 모델, 거래표: Path, 자료: Path):
    행 = 표읽기(거래표)
    if not 행:
        print(f"[!] 거래표가 없습니다: {거래표}")
        return 3
    가족 = [r["사람"] for r in 표읽기(자료 / "가족.csv") if r.get("사람")]
    if not 가족:
        가족 = sorted({r["사람"] for r in 행})
    설명 = {r["사람"]: (r.get("비고") or r.get("관계") or "")
          for r in 표읽기(자료 / "가족.csv") if r.get("사람")}

    큰것 = Counter()
    for r in 행:
        if r["구분"] == "지출":
            큰것[r["가맹점"]] += -int(r["금액"])
    이름들 = [n for n, _ in 큰것.most_common(80)]

    print(f"가족 {len(가족)}명 · 가맹점 상위 {len(이름들)}개를 물어봅니다.")

    스키마 = {"type": "object", "properties": {"규칙": {"type": "array", "items": {
        "type": "object", "properties": {
            "키워드": {"type": "string"},
            "수혜자": {"type": "string"},
            "이유": {"type": "string"},
        }, "required": ["키워드", "수혜자"]}}}, "required": ["규칙"]}

    지시 = (
        "가계부의 가맹점 이름을 보고 '그 돈이 누구를 위해 쓰였는지'를 고릅니다.\n"
        "- 특정 가족을 위한 것이 분명할 때만 그 사람을 고릅니다 (학원·유치원·아이 학용품 등).\n"
        "- 온 가족이 함께 쓰는 것은 '가족공통' 으로 합니다 (장보기·주거·통신·가족 외식).\n"
        "- 누구 것인지 알 수 없으면 목록에서 아예 뺍니다. 추측해서 넣지 않습니다.\n"
        "- 키워드는 가맹점 이름에서 변하지 않는 부분만 짧게 씁니다. "
        "예: '청담어학원 목동점' → '청담어학원'\n"
        "- 수혜자는 주어진 가족 이름이나 '가족공통' 중에서만 고릅니다."
    )
    사람설명 = "\n".join(f"- {n}" + (f" ({설명[n]})" if 설명.get(n) else "") for n in 가족)
    질문 = (f"가족:\n{사람설명}\n\n가맹점(금액 큰 순):\n" + "\n".join(이름들))

    답, 오류, 쓴것 = 물어보기(키, 모델, [{"text": 질문}], 스키마, 지시)
    if 오류:
        print(f"[!] {오류}")
        return 1
    비용알림(모델, 쓴것)

    # 모델이 '딸_김서연' 대신 '딸' 처럼 짧게 답할 수 있다. 같은 사람으로 본다.
    맞추기 = {"가족공통": "가족공통"}
    for n in 가족:
        맞추기[n] = n
        맞추기.setdefault(n.split("_")[0], n)
        if "_" in n:
            맞추기.setdefault(n.split("_", 1)[1], n)

    줄, 버린이름 = [], []
    for x in 답.get("규칙", []):
        누구 = 맞추기.get((x.get("수혜자") or "").strip())
        if 누구:
            줄.append([x["키워드"], 누구])
        else:
            버린이름.append(x.get("수혜자", ""))

    print(f"\n규칙 {len(줄)}개"
          + (f" · 가족에 없는 이름이라 버림: {', '.join(sorted(set(버린이름)))}" if 버린이름 else ""))
    개인 = [r for r in 줄 if r[1] != "가족공통"]
    for a, b in (개인 or 줄)[:12]:
        print(f"  {a} → {b}")
    if 개인:
        print(f"  (그 밖에 가족공통 {len(줄) - len(개인)}개)")
    초안쓰기(자료 / "수혜자규칙_초안.csv", ["키워드", "수혜자"], 줄)
    return 0


# ============================================================================
# 3. 증권 사진·PDF → 보험.csv
# ============================================================================
보험머리 = ["사람", "보험사", "상품명", "증권번호(뒤4자리)", "계약일", "만기일",
         "월보험료", "보장항목", "보장금액", "갱신형", "비고"]

보장이름 = ["사망_일반", "사망_재해", "후유장해", "암_일반암", "암_유사암",
         "뇌혈관질환", "허혈성심장질환", "실손_급여", "실손_비급여", "입원일당",
         "수술비", "간병_장기요양", "치매", "치아", "배상책임", "화재_재물",
         "자동차_대인배상1", "자동차_대인배상2", "자동차_대물배상",
         "자동차_자기신체사고", "자동차_자기차량손해", "자동차_무보험차상해",
         "운전자_벌금", "운전자_형사합의", "운전자_변호사선임"]


def 증권작업(키, 모델, 파일들, 자료: Path, 사람: str):
    조각, 담긴 = [], []
    for f in 파일들:
        p = Path(f)
        if not p.exists():
            print(f"[!] 없는 파일: {p}")
            continue
        형식 = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if not (형식.startswith("image/") or 형식 == "application/pdf"):
            print(f"[!] 사진이나 PDF 만 됩니다. 건너뜀: {p.name} ({형식})")
            continue
        if p.stat().st_size > 15 * 1024 * 1024:
            print(f"[!] 너무 큽니다(15MB 넘음). 건너뜀: {p.name}")
            continue
        조각.append({"inline_data": {"mime_type": 형식,
                                   "data": base64.b64encode(p.read_bytes()).decode()}})
        담긴.append(p.name)

    if not 조각:
        print("[!] 읽을 파일이 없습니다.")
        return 2
    print(f"증권 {len(조각)}개를 읽습니다: {', '.join(담긴)}")
    print("사진 한 장이 대략 1,300토큰쯤 들어갑니다.")

    스키마 = {"type": "object", "properties": {"증권": {"type": "array", "items": {
        "type": "object", "properties": {
            "보험사": {"type": "string"}, "상품명": {"type": "string"},
            "증권번호뒤4자리": {"type": "string"},
            "계약일": {"type": "string"}, "만기일": {"type": "string"},
            "월보험료": {"type": "string"},
            "보장": {"type": "array", "items": {"type": "object", "properties": {
                "항목": {"type": "string"}, "금액": {"type": "string"},
                "갱신형": {"type": "string"}, "비고": {"type": "string"},
            }, "required": ["항목", "금액"]}},
        }, "required": ["보험사", "상품명", "보장"]}}}, "required": ["증권"]}

    지시 = (
        "보험 증권 이미지나 PDF 를 읽어 표로 옮기는 일을 합니다.\n"
        "- 문서에 적힌 것만 옮깁니다. 안 보이면 빈 칸으로 둡니다. 추측해서 채우지 않습니다.\n"
        "- 증권번호는 <b>뒤 4자리만</b> 적습니다. 전체를 옮기지 않습니다.\n"
        "- 주민등록번호·계좌번호·주소·전화번호는 절대 옮기지 않습니다.\n"
        f"- 보장 항목 이름은 되도록 다음에서 고릅니다: {', '.join(보장이름)}\n"
        "  마땅한 것이 없으면 증권에 적힌 이름을 그대로 씁니다.\n"
        "- 날짜는 2015-03-02 꼴로 씁니다. 종신이면 '종신'.\n"
        "- 금액은 숫자만 씁니다. 한도가 없으면 '무한'.\n"
        "- 월보험료는 증권당 한 번만, 첫 보장 줄에만 적습니다."
    ).replace("<b>", "").replace("</b>", "")

    조각.append({"text": "이 증권들을 표로 옮겨 주세요."})
    답, 오류, 쓴것 = 물어보기(키, 모델, 조각, 스키마, 지시, 온도=0.0)
    if 오류:
        print(f"[!] {오류}")
        return 1
    비용알림(모델, 쓴것)

    줄 = []
    for s in 답.get("증권", []):
        보장 = s.get("보장") or []
        for i, b in enumerate(보장):
            줄.append([
                사람, s.get("보험사", ""), s.get("상품명", ""),
                (s.get("증권번호뒤4자리", "") or "")[-4:],
                s.get("계약일", ""), s.get("만기일", ""),
                (s.get("월보험료", "") if i == 0 else ""),
                b.get("항목", ""), b.get("금액", ""),
                b.get("갱신형", ""), b.get("비고", ""),
            ])

    print(f"\n증권 {len(답.get('증권', []))}건 · 보장 {len(줄)}줄을 읽었습니다.")
    for s in 답.get("증권", []):
        print(f"  {s.get('보험사', '')} {s.get('상품명', '')} "
              f"— 보장 {len(s.get('보장') or [])}개")
    초안쓰기(자료 / "보험_초안.csv", 보험머리, 줄)
    print("★ 금액과 보장 항목이 증권과 맞는지 꼭 눈으로 대조해 주세요.")
    return 0


# ============================================================================
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="설정을 AI에게 한 번 물어보고 규칙으로 굳힙니다.")
    ap.add_argument("--input", default="out/거래통합.csv")
    ap.add_argument("--data", default="data/private")
    ap.add_argument("--model", default=기본모델)
    ap.add_argument("--person", default="나", help="증권 주인 (--policy 에서 씀)")
    ap.add_argument("--categories", action="store_true")
    ap.add_argument("--who", action="store_true")
    ap.add_argument("--policy", nargs="*", help="증권 사진·PDF 파일들")
    args = ap.parse_args()

    자료 = Path(args.data)
    키, 어디 = 키찾기(자료)
    if not 키:
        print("[!] 키를 찾지 못했습니다.")
        print("    setx GEMINI_API_KEY \"내키\"  또는  data/private/gemini.key 에 저장")
        return 2
    print(f"키: {어디} / 모델: {args.model}\n")

    if args.categories:
        return 카테고리작업(키, args.model, Path(args.input), 자료)
    if args.who:
        return 수혜자작업(키, args.model, Path(args.input), 자료)
    if args.policy is not None:
        if not args.policy:
            print("[!] 증권 파일을 지정해 주세요. 예: --policy 증권1.jpg 증권2.pdf")
            return 2
        return 증권작업(키, args.model, args.policy, 자료, args.person)

    print("할 일을 지정하세요: --categories / --who / --policy <파일들>")
    return 2


if __name__ == "__main__":
    sys.exit(main())

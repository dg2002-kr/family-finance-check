# -*- coding: utf-8 -*-
"""
표준 거래표(out/거래통합.csv)를 읽어 HTML 대시보드 한 장을 만든다.

  python -X utf8 scripts/report.py
  python -X utf8 scripts/report.py --input out/거래통합.csv --output out/우리집_점검.html

외부 라이브러리·CDN·웹폰트를 쓰지 않는다. 인터넷이 끊겨도 열린다.
"""
import argparse
import csv
import datetime as dt
import html
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# ============================================================================
# 고정비 판정 기준 — 느슨하게 하려면 숫자를 키우세요
# ============================================================================
금액편차한도 = 0.10   # 금액이 평균의 ±10% 안에서 움직여야 고정비로 본다
결제일편차한도 = 3.0  # 결제일이 며칠 이내로 일정해야 한다 (일)

# ============================================================================
# 색과 글꼴 — 실습 폴더 CLAUDE.md 팔레트를 따른다
# ============================================================================
CSS = """
:root {
  --accent: #00462A;
  --accent-pale: #E8EFEB;
  --bg-page: #FFFDF1;
  --bg-card: #FFFFFF;
  --neutral: #B9B9B9;
  --border: #E1E4E8;
  --text-primary: #1A1A1A;
  --text-secondary: #5F6368;
  --sub-coral: #F27367;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 16px 64px;
  background: var(--bg-page);
  color: var(--text-primary);
  font-family: Pretendard, 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
  font-size: 15px; line-height: 1.6;
}
.wrap { max-width: 980px; margin: 0 auto; }
h1 { font-size: 26px; font-weight: 700; margin: 0 0 4px; color: var(--accent); }
h2 {
  font-size: 19px; font-weight: 700; margin: 40px 0 14px;
  border-left: 4px solid var(--accent); padding-left: 12px; color: var(--accent);
}
.sub { color: var(--text-secondary); font-size: 14px; margin-bottom: 28px; }

.callout {
  background: var(--accent-pale); border-left: 3px solid var(--accent);
  padding: 14px 16px; border-radius: 4px; margin: 20px 0;
}
.callout p { margin: 0; }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
.kpi {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 4px; padding: 16px 18px;
}
.kpi .label { font-size: 13px; color: var(--text-secondary); margin-bottom: 6px; }
.kpi .value { font-size: 24px; font-weight: 700; color: var(--accent); }
.kpi .note  { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }

table { width: 100%; border-collapse: collapse; background: var(--bg-card); }
th {
  background: var(--accent-pale); color: var(--accent);
  font-weight: 700; font-size: 14px; text-align: left;
  padding: 10px 12px; border-bottom: 1px solid var(--border);
}
td { padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
th.num, td.num { text-align: right; white-space: nowrap; }
tr:last-child td { border-bottom: none; }
tfoot td { font-weight: 700; background: #FAFAF7; }

.bar-cell { width: 42%; min-width: 120px; }
.bar-track { background: #F0F0EC; border-radius: 2px; height: 14px; width: 100%; }
.bar-fill  { background: var(--accent); border-radius: 2px; height: 14px; }
.bar-fill.muted { background: var(--neutral); }

.check {
  margin-top: 10px; font-size: 13px; color: var(--text-secondary);
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 4px; padding: 8px 12px;
}
.check.ok   { color: var(--accent); }
.check.bad  { color: var(--sub-coral); font-weight: 700; }

.footer {
  margin-top: 48px; padding: 14px 16px; border-radius: 4px;
  background: var(--accent-pale); border-left: 3px solid var(--sub-coral);
  font-size: 13px; color: var(--text-primary);
}
.footer strong { color: var(--sub-coral); }
.muted-text { color: var(--text-secondary); font-size: 13px; }

@media (max-width: 640px) {
  body { padding: 16px 12px 48px; }
  .bar-cell { display: none; }
  h1 { font-size: 22px; }
}
"""


# ============================================================================
def 돈(n) -> str:
    return f"{n:,.0f}원"


def esc(s) -> str:
    return html.escape(str(s))


def 막대(값, 최대, muted=False):
    pct = 0 if 최대 <= 0 else max(1.5, 값 / 최대 * 100)
    cls = "bar-fill muted" if muted else "bar-fill"
    return (f'<div class="bar-track"><div class="{cls}" style="width:{pct:.1f}%"></div></div>')


# ============================================================================
def 거래읽기(path: Path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["금액"] = int(r["금액"])
    return rows


def 집계(거래들):
    """지출만 집계한다. 이체는 두 번 세지 않기 위해 뺀다."""
    지출 = [t for t in 거래들 if t["구분"] == "지출"]
    수입 = [t for t in 거래들 if t["구분"] == "수입"]
    이체 = [t for t in 거래들 if t["구분"] == "이체"]

    사람별 = defaultdict(int)
    카테고리별 = defaultdict(int)
    월별 = defaultdict(int)
    월사람 = defaultdict(int)
    월카테고리 = defaultdict(int)

    for t in 지출:
        금 = -t["금액"]                      # 지출은 음수로 저장돼 있다
        월 = t["날짜"][:7]
        사람별[t["사람"]] += 금
        카테고리별[t["카테고리"]] += 금
        월별[월] += 금
        월사람[(월, t["사람"])] += 금
        월카테고리[(월, t["카테고리"])] += 금

    return {
        "지출": 지출, "수입": 수입, "이체": 이체,
        "사람별": dict(사람별), "카테고리별": dict(카테고리별),
        "월별": dict(월별), "월사람": dict(월사람), "월카테고리": dict(월카테고리),
        "총지출": sum(사람별.values()),
        "총수입": sum(t["금액"] for t in 수입),
        "달들": sorted(월별),
        "사람들": sorted(사람별, key=lambda k: -사람별[k]),
    }


# ============================================================================
# 고정비 — 매달 같은 날 비슷한 금액이 빠져나가는 것
# ============================================================================
def 고정비찾기(A):
    """판정 근거를 함께 돌려준다. 근거를 보여줘야 사용자가 오탐을 스스로 걸러낸다."""
    관측개월 = len(A["달들"])
    if 관측개월 < 3:
        return [], 관측개월

    그룹 = defaultdict(list)
    for t in A["지출"]:
        그룹[(t["사람"], t["가맹점"])].append(t)

    결과 = []
    for (사람, 가맹점), ts in 그룹.items():
        달 = {t["날짜"][:7] for t in ts}
        # 매달 빠짐없이, 한 달에 한 번씩
        if len(달) != 관측개월 or len(ts) != 관측개월:
            continue

        금액들 = [-t["금액"] for t in ts]
        평균 = statistics.mean(금액들)
        if 평균 <= 0:
            continue
        금액편차 = statistics.stdev(금액들) / 평균

        결제일들 = [dt.date.fromisoformat(t["날짜"]).day for t in ts]
        결제일편차 = statistics.stdev(결제일들)

        if 금액편차 > 금액편차한도 or 결제일편차 > 결제일편차한도:
            continue

        # 결제일 ±2일까지는 확실한 고정비로 본다 (28·31일처럼 월말 결제는 달마다 날짜가 밀린다)
        확신 = "높음" if (금액편차 <= 0.02 and 결제일편차 <= 2.0) else "보통"
        마지막 = max(t["날짜"] for t in ts)
        결과.append({
            "가맹점": 가맹점, "사람": 사람,
            "월금액": round(평균), "연환산": round(평균 * 12),
            "카테고리": ts[0]["카테고리"],
            "확신": 확신, "마지막": 마지막,
            "근거": (f"{관측개월}개월 중 {len(달)}개월 · "
                   f"금액 편차 {금액편차*100:.1f}% · "
                   f"결제일 {'매달 ' + str(결제일들[0]) + '일' if 결제일편차 == 0 else f'±{결제일편차:.1f}일'}"),
        })

    결과.sort(key=lambda r: -r["월금액"])
    return 결과, 관측개월


def 중복구독찾기(고정비들):
    """같은 이름이 두 사람 이상에게서 각각 빠져나가는 것."""
    이름별 = defaultdict(list)
    for f in 고정비들:
        이름별[f["가맹점"]].append(f)
    return {이름: fs for 이름, fs in 이름별.items() if len({f["사람"] for f in fs}) >= 2}


def 전월대비(A):
    """마지막 달과 그 직전 달을 카테고리별로 비교한다."""
    if len(A["달들"]) < 2:
        return None, None, []
    이번, 지난 = A["달들"][-1], A["달들"][-2]
    카테고리 = sorted({c for (m, c) in A["월카테고리"]})
    행 = []
    for c in 카테고리:
        a = A["월카테고리"].get((이번, c), 0)
        b = A["월카테고리"].get((지난, c), 0)
        if a == 0 and b == 0:
            continue
        행.append({"카테고리": c, "이번달": a, "지난달": b, "차이": a - b,
                   "비율": None if b == 0 else (a - b) / b * 100})
    행.sort(key=lambda r: -abs(r["차이"]))
    return 이번, 지난, 행


# ============================================================================
def 표_고정비(고정비들, 관측개월, 중복구독):
    if not 고정비들:
        return ('<div class="check">3개월 이상 자료가 쌓이면 고정비를 찾아드립니다. '
                f'지금은 {관측개월}개월치입니다.</div>')

    월합 = sum(f["월금액"] for f in 고정비들)
    연합 = sum(f["연환산"] for f in 고정비들)

    경고 = ""
    if 중복구독:
        항목 = " / ".join(
            f'{esc(이름)} ({", ".join(esc(f["사람"]) for f in fs)}, 합쳐서 월 {돈(sum(f["월금액"] for f in fs))})'
            for 이름, fs in 중복구독.items())
        경고 = f"""<div class="callout">
  <p><strong>같은 서비스가 두 사람 이상에게서 각각 빠져나가고 있어요.</strong><br>{항목}</p>
</div>"""

    행 = []
    for f in 고정비들:
        배지 = ("" if f["확신"] == "높음"
                else '<span class="muted-text"> (확인 필요)</span>')
        행.append(f"""<tr>
  <td>{esc(f["가맹점"])}{배지}<br><span class="muted-text">{esc(f["근거"])}</span></td>
  <td>{esc(f["사람"])}</td>
  <td class="num">{돈(f["월금액"])}</td>
  <td class="num">{돈(f["연환산"])}</td>
  <td class="num muted-text">{esc(f["마지막"])}</td>
</tr>""")

    return f"""{경고}<table>
<thead><tr><th>항목 · 판정 근거</th><th>사람</th><th class="num">월</th>
<th class="num">1년이면</th><th class="num">마지막 결제</th></tr></thead>
<tbody>{''.join(행)}</tbody>
<tfoot><tr><td>고정비 {len(고정비들)}건 합계</td><td></td>
<td class="num">{돈(월합)}</td><td class="num">{돈(연합)}</td><td></td></tr></tfoot>
</table>
<div class="check">프로그램은 <strong>매달 반복되는 결제</strong>를 찾아줄 뿐, 그게 필요한 지출인지는 알 수 없습니다.
마지막 결제일과 판정 근거를 보고 직접 판단해 주세요.</div>"""


def 표_전월대비(이번, 지난, 행들):
    if not 행들:
        return '<div class="check">비교할 달이 아직 두 달치가 안 됩니다.</div>'
    최대 = max(abs(r["차이"]) for r in 행들)
    tr = []
    for r in 행들:
        d = r["차이"]
        기호 = "▲" if d > 0 else ("▼" if d < 0 else "-")
        색 = "color:var(--sub-coral);font-weight:700" if d > 0 else "color:var(--accent)"
        비율 = "새로 생김" if r["비율"] is None else f"{r['비율']:+.1f}%"
        if r["이번달"] == 0:
            비율 = "이번 달 없음"
        tr.append(f"""<tr>
  <td>{esc(r["카테고리"])}</td>
  <td class="num">{돈(r["지난달"])}</td>
  <td class="num">{돈(r["이번달"])}</td>
  <td class="num" style="{색}">{기호} {돈(abs(d))}</td>
  <td class="num muted-text">{esc(비율)}</td>
  <td class="bar-cell">{막대(abs(d), 최대, muted=(d < 0))}</td>
</tr>""")
    return f"""<table>
<thead><tr><th>카테고리</th><th class="num">{esc(지난)}</th><th class="num">{esc(이번)}</th>
<th class="num">차이</th><th class="num">증감률</th><th>　</th></tr></thead>
<tbody>{''.join(tr)}</tbody>
</table>
<div class="check">늘어난 항목은 <span style="color:var(--sub-coral);font-weight:700">▲ 진한 막대</span>,
줄어든 항목은 <span style="color:var(--text-secondary)">▼ 회색 막대</span>입니다. 색과 기호를 함께 표시했습니다.</div>"""


# ============================================================================
def 표_구성원(A):
    최대 = max(A["사람별"].values()) if A["사람별"] else 0
    총 = A["총지출"]
    행 = []
    for 이름 in A["사람들"]:
        금 = A["사람별"][이름]
        비중 = 0 if 총 == 0 else 금 / 총 * 100
        행.append(f"""<tr>
  <td>{esc(이름)}</td>
  <td class="num">{돈(금)}</td>
  <td class="num">{비중:.1f}%</td>
  <td class="bar-cell">{막대(금, 최대)}</td>
</tr>""")
    합 = sum(A["사람별"].values())
    맞음 = 합 == 총
    검산 = (f'<div class="check ok">검산: 구성원 합계 {돈(합)} = 가구 총지출 {돈(총)} ✓</div>'
            if 맞음 else
            f'<div class="check bad">검산 불일치: 구성원 합계 {돈(합)} ≠ 가구 총지출 {돈(총)} ✗</div>')
    return f"""<table>
<thead><tr><th>구성원</th><th class="num">지출</th><th class="num">비중</th><th>　</th></tr></thead>
<tbody>{''.join(행)}</tbody>
</table>{검산}"""


def 표_카테고리(A):
    항목 = sorted(A["카테고리별"].items(), key=lambda kv: -kv[1])
    최대 = 항목[0][1] if 항목 else 0
    총 = A["총지출"]
    행 = []
    for 이름, 금 in 항목:
        비중 = 0 if 총 == 0 else 금 / 총 * 100
        행.append(f"""<tr>
  <td>{esc(이름)}</td>
  <td class="num">{돈(금)}</td>
  <td class="num">{비중:.1f}%</td>
  <td class="bar-cell">{막대(금, 최대)}</td>
</tr>""")
    return f"""<table>
<thead><tr><th>카테고리</th><th class="num">지출</th><th class="num">비중</th><th>　</th></tr></thead>
<tbody>{''.join(행)}</tbody>
<tfoot><tr><td>합계</td><td class="num">{돈(총)}</td><td class="num">100.0%</td><td></td></tr></tfoot>
</table>"""


def 표_월별(A):
    사람들 = A["사람들"]
    머리 = "".join(f'<th class="num">{esc(p)}</th>' for p in 사람들)
    행 = []
    for 월 in A["달들"]:
        칸 = "".join(f'<td class="num">{돈(A["월사람"].get((월, p), 0))}</td>' for p in 사람들)
        행.append(f'<tr><td>{esc(월)}</td>{칸}<td class="num">{돈(A["월별"][월])}</td></tr>')
    return f"""<table>
<thead><tr><th>월</th>{머리}<th class="num">가구 합계</th></tr></thead>
<tbody>{''.join(행)}</tbody>
</table>"""


# ============================================================================
def html만들기(A, 거래들, 입력파일):
    파일수 = len({t["원본파일"].split(":")[0] for t in 거래들})
    중복 = [t for t in 거래들 if t["중복의심"] == "Y"]
    중복금액 = sum(abs(t["금액"]) for t in 중복) // 2

    고정비들, 관측개월 = 고정비찾기(A)
    중복구독 = 중복구독찾기(고정비들)
    고정비월합 = sum(f["월금액"] for f in 고정비들)
    고정비연합 = sum(f["연환산"] for f in 고정비들)   # 표 합계와 어긋나지 않게 같은 값을 쓴다
    이번, 지난, 변화 = 전월대비(A)

    기간 = f'{A["달들"][0]} ~ {A["달들"][-1]}' if A["달들"] else "-"
    생성 = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    중복안내 = ""
    if 중복:
        중복안내 = f"""<div class="callout">
  <p><strong>같은 거래가 두 번 잡힌 것으로 보이는 게 {len(중복)//2}쌍 있습니다</strong>
  (약 {돈(중복금액)}). 가계부 앱과 카드사 파일에 같은 결제가 함께 들어 있을 때 생깁니다.
  자동으로 지우지 않았으니, 위 금액만큼 부풀어 있을 수 있다는 점을 감안해 주세요.</p>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>우리집 가계 점검</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

  <h1>우리집 가계 점검</h1>
  <div class="sub">{esc(기간)} · 파일 {파일수}개 · 거래 {len(거래들)}건 · {esc(생성)} 기준</div>

  <div class="kpis">
    <div class="kpi"><div class="label">가구 총지출</div>
      <div class="value">{돈(A["총지출"])}</div>
      <div class="note">이체·카드대금 제외</div></div>
    <div class="kpi"><div class="label">가구 총수입</div>
      <div class="value">{돈(A["총수입"])}</div>
      <div class="note">확인된 입금만</div></div>
    <div class="kpi"><div class="label">매달 나가는 고정비</div>
      <div class="value">{돈(고정비월합)}</div>
      <div class="note">1년이면 {돈(고정비연합)}</div></div>
    <div class="kpi"><div class="label">중복 의심</div>
      <div class="value">{len(중복)//2}쌍</div>
      <div class="note">자동으로 지우지 않음</div></div>
  </div>

  {중복안내}

  <h2>구성원별 지출</h2>
  {표_구성원(A)}

  <h2>카테고리별 지출</h2>
  {표_카테고리(A)}

  <h2>매달 빠져나가는 고정비</h2>
  {표_고정비(고정비들, 관측개월, 중복구독)}

  <h2>지난달과 무엇이 달라졌나 ({esc(지난 or "-")} → {esc(이번 or "-")})</h2>
  {표_전월대비(이번, 지난, 변화)}

  <h2>월별 추이</h2>
  {표_월별(A)}

  <div class="footer">
    <strong>이 파일에는 실제 거래 내역이 들어 있습니다.</strong>
    메신저나 메일로 공유하지 마세요.<br>
    <span class="muted-text">
      이 도구는 숫자를 모아 보여주는 정리 도구이며, 투자나 보험 가입·해지를 권유하지 않습니다.
      판단은 본인이 하시고, 필요하면 자격을 갖춘 전문가와 상담하세요.<br>
      원본: {esc(입력파일)}
    </span>
  </div>

</div>
</body>
</html>"""


# ============================================================================
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="거래표를 HTML 대시보드로 만듭니다.")
    ap.add_argument("--input", default="out/거래통합.csv")
    ap.add_argument("--output", default="out/우리집_점검.html")
    args = ap.parse_args()

    입력 = Path(args.input)
    if not 입력.exists():
        print(f"[!] 거래표가 없습니다: {입력}")
        print("    먼저 python -X utf8 scripts/parse.py 를 실행하세요.")
        return 3

    거래들 = 거래읽기(입력)
    if not 거래들:
        print("[!] 거래표가 비어 있습니다.")
        return 3

    A = 집계(거래들)
    출력 = Path(args.output)
    출력.parent.mkdir(parents=True, exist_ok=True)
    출력.write_text(html만들기(A, 거래들, 입력.name), encoding="utf-8")

    print(f"기간 {A['달들'][0]} ~ {A['달들'][-1]} / 거래 {len(거래들)}건")
    print(f"가구 총지출 {A['총지출']:,}원 / 구성원 {len(A['사람들'])}명")
    합 = sum(A["사람별"].values())
    print(f"검산: 구성원 합계 {합:,}원 {'=' if 합 == A['총지출'] else '≠'} 가구 총지출 {A['총지출']:,}원")

    고정비들, _ = 고정비찾기(A)
    print(f"\n고정비 {len(고정비들)}건 / 월 {sum(f['월금액'] for f in 고정비들):,}원 "
          f"/ 1년 {sum(f['연환산'] for f in 고정비들):,}원")
    for f in 고정비들:
        print(f"  {f['가맹점']:<22} {f['사람']:<12} 월 {f['월금액']:>9,}원  [{f['확신']}] {f['근거']}")
    for 이름, fs in 중복구독찾기(고정비들).items():
        print(f"  ! 중복 구독: {이름} — {', '.join(f['사람'] for f in fs)}")
    print(f"\n저장: {출력}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

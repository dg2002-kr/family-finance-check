# -*- coding: utf-8 -*-
"""
표준 거래표(out/거래통합.csv)를 읽어 가계부 앱 같은 대시보드 한 장을 만든다.

  python -X utf8 scripts/report.py
  python -X utf8 scripts/report.py --input out/거래통합.csv --output out/우리집_점검.html

외부 라이브러리·CDN·웹폰트를 쓰지 않는다. 인터넷이 끊겨도 열린다.
표 대신 카드와 목록으로 구성해 휴대폰에서도 가로로 잘리지 않는다.
"""
import argparse
import csv
import datetime as dt
import html
import json
import colorsys
import math
import re
import struct
import zlib
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# ============================================================================
# 고정비 판정 기준 — 느슨하게 하려면 숫자를 키우세요
# ============================================================================
금액편차한도 = 0.10   # 금액이 평균의 ±10% 안에서 움직여야 고정비로 본다
결제일편차한도 = 3.0  # 결제일이 며칠 이내로 일정해야 한다 (일)

상세개월한도 = 12     # 상세 보기에 담을 최근 개월 수 (파일이 무거워지지 않게)

# ============================================================================
# 색
#   실습 폴더 CLAUDE.md 의 문서용 팔레트(크림 배경·진초록) 대신
#   앱 화면에 맞는 밝은 회색 바탕 + 선명한 초록으로 간다. 사용자 요청에 따른 것.
# ============================================================================
#   색이 뜻을 갖는 곳은 '누구'뿐이다. 구성원만 서로 다른 색을 쓰고,
#   카테고리·자산처럼 '무엇'에 해당하는 것은 초록 한 가지의 농담으로만 구분한다.
#   색이 많으면 볼 때마다 무슨 뜻인지 다시 배워야 한다.
구성원색 = ["#00A86B", "#4C6FFF", "#FFA61A", "#FF6B6B", "#8B5CF6", "#00B8D9"]
공통색 = "#7C8BA1"
회색 = "#C7CDD6"

def _hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, l / 100, s / 100)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


# 한눈에 알아보게 붙이는 그림글자. Windows·Mac 에 기본으로 깔린 것만 쓴다.
카테고리아이콘 = {
    "식비": "🍚", "장보기": "🛒", "교육": "📚", "교통": "🚗", "의료": "🏥",
    "주거": "🏠", "통신비": "📱", "보험": "🛡️", "쇼핑": "🛍️", "문화": "🎬",
    "여가": "✈️", "생활": "🧺", "운동": "🏃", "구독": "📺",
    "수입": "💰", "이체": "🔁", "기타": "🧩",
}
자산아이콘 = {"부동산": "🏢", "금융자산": "📈", "현금": "💵", "부채": "💳"}
보장아이콘 = {
    "사망": "🕊️", "암": "🎗️", "실손": "🏥", "자동차": "🚗", "수술": "🩺",
    "입원": "🛏️", "치아": "🦷", "배상": "⚖️", "운전자": "🚨", "뇌혈관": "🧠",
    "허혈성": "❤️", "간병": "🧑‍⚕️", "후유장해": "♿", "화재": "🔥",
}


def 아이콘(이름: str, 표=None, 기본="🧩") -> str:
    표 = 표 if 표 is not None else 카테고리아이콘
    if 이름 in 표:
        return 표[이름]
    for 키, 그림 in 표.items():
        if 이름.startswith(키):
            return 그림
    return 기본


def 그림칸(이름, 표=None, 기본="🧩") -> str:
    return f'<div class="ico">{아이콘(이름, 표, 기본)}</div>'


def 농담(n, 계열="초록"):
    """한 계열 안에서 색상·채도·밝기를 함께 조금씩 옮겨 서로 구분되게 만든다.

    같은 색을 밝기만 바꿔 늘어놓으면 항목이 열 개를 넘을 때 구분이 안 된다.
    색상을 좁은 범위에서 같이 돌리면 한 식구로 보이면서도 서로 구별된다.
    큰 항목이 진하고 작은 항목이 연하다.
    """
    띠 = {
        "초록": (188, 68, 64, 58, 34, 57),       # 청록 → 연두 (소비)
        "파랑": (224, 152, 62, 56, 33, 58),       # 남색 → 청록 (자산)
        "보라": (280, 196, 54, 52, 36, 60),
    }
    h0, h1, s0, s1, l0, l1 = 띠.get(계열, 띠["초록"])
    if n <= 1:
        return [_hsl(h0, s0, (l0 + l1) / 2)]
    걸음 = lambda a, b, i: a + (b - a) * (i / (n - 1))          # noqa: E731
    # 밝기를 한 칸씩 엇갈리게 해 바로 옆 항목과 더 확실히 갈라 놓는다
    엇갈림 = lambda i: 4.5 if i % 2 else -4.5                    # noqa: E731
    return [_hsl(걸음(h0, h1, i), 걸음(s0, s1, i),
                 min(72, max(26, 걸음(l0, l1, i) + 엇갈림(i)))) for i in range(n)]

CSS = """
:root {
  --bg: #F4F6F8;
  --surface: #FFFFFF;
  --ink: #0F1620;
  --ink2: #5C6875;
  --ink3: #96A0AC;
  --line: #EDF0F3;
  --brand: #00A86B;
  --brand-deep: #00563A;
  --brand-soft: #E6F7EF;
  --up: #FF4D4F;
  --up-soft: #FFECEC;
  --loss: #2E7CF6;   /* 국내 증권 앱 관행: 오르면 빨강, 내리면 파랑 */
  --down: #00A86B;
  --down-soft: #E6F7EF;
  --r-lg: 18px;
  --r-md: 14px;
  --r-sm: 10px;
  --sh: 0 1px 2px rgba(15,22,32,.04), 0 6px 20px rgba(15,22,32,.05);
  --sh-hi: 0 2px 6px rgba(15,22,32,.07), 0 12px 30px rgba(15,22,32,.09);
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  padding: 36px 24px 80px;
  background: var(--bg);
  color: var(--ink);
  font-family: Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI',
               'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
  font-size: 15px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  letter-spacing: -0.01em;
}
.app { max-width: 940px; margin: 0 auto; }
.tnum { font-variant-numeric: tabular-nums; }

/* ---------- 탭 ---------- */
.tabs {
  position: sticky; top: 0; z-index: 30;
  display: flex; gap: 4px; padding: 10px 0 12px;
  background: linear-gradient(var(--bg) 78%, rgba(244,246,248,0));
  margin-bottom: 4px;
}
.tab-btn {
  flex: 1; border: none; cursor: pointer;
  background: #E7EBF0; color: var(--ink2);
  font-family: inherit; font-size: 13.5px; font-weight: 700; letter-spacing: -0.02em;
  padding: 11px 8px; border-radius: 11px;
  transition: background .13s, color .13s;
}
.tab-btn:hover { background: #DDE3EA; }
.tab-btn[aria-selected="true"] {
  background: var(--ink); color: #fff;
}
.tab-btn .n {
  display: inline-block; margin-left: 5px; padding: 1px 6px;
  border-radius: 999px; background: var(--up); color: #fff; font-size: 11px;
}
.tab-btn[aria-selected="true"] .n { background: var(--up); }
.panel[hidden] { display: none; }

/* ---------- 사람 고르기 (보험) ---------- */
.subtabs {
  display: flex; gap: 6px; overflow-x: auto; padding: 2px 0 13px;
  -webkit-overflow-scrolling: touch; scrollbar-width: none;
}
.subtabs::-webkit-scrollbar { display: none; }
.sub-btn {
  flex: none; cursor: pointer; white-space: nowrap;
  border: 1px solid var(--line); background: var(--surface); color: var(--ink2);
  font-family: inherit; font-size: 13px; font-weight: 700; letter-spacing: -0.02em;
  padding: 8px 14px; border-radius: 999px;
  display: inline-flex; align-items: center; gap: 6px;
  transition: background .13s, color .13s, border-color .13s;
}
.sub-btn:hover { border-color: var(--ink3); }
.sub-btn[aria-selected="true"] { background: var(--ink); color: #fff; border-color: var(--ink); }
.sub-btn .c { font-size: 11px; opacity: .7; font-weight: 700; }
.sub-btn .c.none { color: var(--up); opacity: 1; }
.sub-btn[aria-selected="true"] .c.none { color: #FF9A9C; }
.subpanel[hidden] { display: none; }

.pstat {
  display: flex; gap: 18px; flex-wrap: wrap;
  padding: 14px 18px; margin-bottom: 11px;
  background: var(--surface); border-radius: var(--r-md); box-shadow: var(--sh);
}
.pstat div { min-width: 0; }
.pstat .k { font-size: 11.5px; color: var(--ink3); font-weight: 600; }
.pstat .v {
  font-size: 17px; font-weight: 800; letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}
.gapbox { padding: 12px 16px; }

/* ---------- 유형 펼치기 (자산) ---------- */
.acc-body[hidden] { display: none; }
.acc-body {
  background: #F7F9FB; border-radius: var(--r-sm);
  margin: 2px 0 8px; padding: 4px 0;
}
.acc-body .aitem { padding: 10px 16px 10px 18px; }
.acc-body .acc-body { background: #FFF; margin: 0 10px 8px; }
.hbox { padding: 12px 14px; }
.hsum { display: flex; gap: 16px; flex-wrap: wrap; padding-bottom: 11px; border-bottom: 1px solid var(--line); margin-bottom: 4px; }
.hsum .k { font-size: 11px; color: var(--ink3); font-weight: 600; }
.hsum .v { font-size: 14.5px; font-weight: 800; letter-spacing: -0.03em; }
.hrow { display: flex; align-items: center; gap: 12px; padding: 9px 0; border-bottom: 1px dotted var(--line); }
.hrow:last-of-type { border-bottom: none; }
.hmain { flex: 1; min-width: 0; }
.hname { font-size: 13.5px; font-weight: 700; }
.hsub { font-size: 12px; color: var(--ink2); margin-top: 3px; line-height: 1.5; }
.hside { text-align: right; flex: none; }
.hval { font-size: 13.5px; font-weight: 800; }
.hpl { font-size: 11.5px; font-weight: 700; margin-top: 1px; }
.hnote { font-size: 11.5px; color: var(--ink2); margin-top: 9px; line-height: 1.6; }

/* 회사 살림 — 공시 재무 */
.finbox { margin: 4px 0 8px; padding: 9px 0 0; border-top: 1px dotted var(--line); }
.fins { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 6px; }
.fin { background: #F6F8FA; border-radius: var(--r-sm); padding: 7px 9px; }
.fin .fk { font-size: 10.5px; color: var(--ink2); font-weight: 700; white-space: nowrap; }
.fin .fv { font-size: 12.5px; font-weight: 800; margin-top: 1px; letter-spacing: -0.02em;
           font-variant-numeric: tabular-nums; }

/* 오늘의 소식 — 키워드 단추, 누르면 제목과 원문 링크 */
.news { margin: 2px 0 10px; padding: 9px 0 0; border-top: 1px dotted var(--line); }
.nlabel { font-size: 11.5px; color: var(--ink2); font-weight: 800; margin-bottom: 8px; }
.nchips { display: flex; flex-direction: column; gap: 6px; }
.nchip {
  border: 1px solid var(--line); background: var(--surface); color: var(--ink);
  font-family: inherit; font-size: 13px; font-weight: 700; cursor: pointer;
  padding: 9px 13px; border-radius: var(--r-sm); text-align: left;
  line-height: 1.45; word-break: keep-all;
  transition: background .13s, border-color .13s, color .13s;
}
.nchip .nsrc { display: block; font-size: 10.5px; color: var(--ink3); font-weight: 600; margin-top: 3px; }
.nchip[aria-pressed="true"] .nsrc { color: #C9D2DC; }
.nchip:hover { border-color: var(--ink3); color: var(--ink); }
.nchip[aria-pressed="true"] { background: var(--ink); color: #fff; border-color: var(--ink); }
.nbox {
  margin-top: 8px; padding: 10px 12px; border-radius: var(--r-sm);
  background: #F3F6F9; border-left: 3px solid var(--ink3);
}
.nbox[hidden] { display: none; }
.ntitle { font-size: 12.5px; font-weight: 700; line-height: 1.5; word-break: keep-all; }
.nmeta { font-size: 11px; color: var(--ink3); margin-top: 3px; }
.nlink {
  display: inline-block; margin-top: 7px; font-size: 11.5px; font-weight: 800;
  color: var(--brand-deep); text-decoration: none;
}
.nlink:hover { text-decoration: underline; }
.hhead { display: flex; align-items: center; gap: 11px; padding-bottom: 12px; }
.hh1 { font-size: 15px; font-weight: 800; letter-spacing: -0.02em; }
.hh2 { font-size: 11.5px; color: var(--ink3); margin-top: 1px; }
.hqbox {
  margin-top: 12px; padding: 12px 14px; border-radius: var(--r-sm);
  background: #FFF8F0; border: 1px solid #FFE6CC;
}
.hqt { font-size: 11px; font-weight: 800; color: #9A5B00; margin-bottom: 7px; }
.hq { font-size: 12.5px; margin-bottom: 8px; }
.hq:last-child { margin-bottom: 0; }
.hq b { display: block; font-weight: 700; color: var(--ink); }
.hq span { color: var(--ink2); }
.acc-body .aitem .rtitle { font-size: 13.5px; font-weight: 600; }
.acc-body .aitem .rval { font-size: 14px; }
.row[data-acc] { cursor: pointer; }
.row[data-acc]:hover { background: #F6F8FA; }
.row[data-acc].open { background: var(--brand-soft); }
.gapbox .t { font-size: 12px; color: var(--ink3); font-weight: 700; margin-bottom: 7px; }

/* ---------- 더 보기 ---------- */
.more[hidden] { display: none; }
.more-btn {
  display: block; width: 100%; border: none; cursor: pointer;
  background: transparent; color: var(--ink2);
  font-family: inherit; font-size: 12.5px; font-weight: 700;
  padding: 12px 8px; border-top: 1px solid var(--line);
  transition: background .13s;
}
.more-btn:hover { background: #F6F8FA; color: var(--brand-deep); }

/* ---------- 머리말 ---------- */
.top { margin-bottom: 14px; }
.top h1 { font-size: 20px; font-weight: 800; margin: 0; letter-spacing: -0.03em; }
.top .period { color: var(--ink3); font-size: 13px; margin-top: 3px; }

/* ---------- 히어로 ---------- */
.hero {
  background: var(--surface); border-radius: var(--r-lg);
  padding: 26px 26px 22px; box-shadow: var(--sh); margin-bottom: 14px;
}
.hero .k { font-size: 13.5px; color: var(--ink2); font-weight: 600; }
.hero .v {
  font-size: 40px; font-weight: 800; letter-spacing: -0.045em;
  margin: 4px 0 10px; line-height: 1.1; font-variant-numeric: tabular-nums;
}
.hero .v span { font-size: 22px; font-weight: 700; margin-left: 2px; color: var(--ink2); }
.hero .cmp { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; font-size: 13.5px; color: var(--ink2); }

.pill {
  display: inline-flex; align-items: center; gap: 4px;
  border-radius: 999px; padding: 4px 11px;
  font-size: 12.5px; font-weight: 700; letter-spacing: -0.02em; white-space: nowrap;
}
.pill.up { background: var(--up-soft); color: var(--up); }
.pill.down { background: var(--down-soft); color: var(--down); }
.pill.flat { background: #F1F3F6; color: var(--ink2); }
.pill.ghost { background: #F1F3F6; color: var(--ink2); font-weight: 600; }

/* 히어로 안의 작은 월 막대 */
.mini { display: flex; gap: 8px; margin-top: 22px; }
.mini .m { flex: 1 1 0; min-width: 0; cursor: pointer; border-radius: 6px; padding-top: 3px; }
.mini .m:hover .mb { background: #C2CBD5; }
.mini .m.now:hover .mb, .mini .m.open .mb { background: var(--brand); }
.mini .m.open { background: var(--brand-soft); }
.mini .m.open .ml { color: var(--brand-deep); font-weight: 800; }
.minihint { font-size: 11.5px; color: var(--ink3); margin-top: 12px; }

/* 해마다 견주기 */
.ytitle { font-size: 13px; font-weight: 800; color: var(--ink2); margin-bottom: 12px; }
.yrow { display: flex; align-items: center; gap: 11px; margin-bottom: 9px; }
.ylab { width: 92px; flex: none; font-size: 12.5px; font-weight: 700; }
.ylab span { display: block; font-size: 10.5px; color: var(--ink3); font-weight: 500; }
.ybar { flex: 1; height: 15px; background: #EDF1F5; border-radius: 4px; overflow: hidden; min-width: 0; }
.ybar i {
  display: block; height: 100%; border-radius: 4px;
  background-image: linear-gradient(90deg, rgba(255,255,255,.25), rgba(255,255,255,0));
}
.yval { width: 86px; flex: none; text-align: right; font-size: 13px; font-weight: 800; }
.ycmp { margin-top: 14px; padding-top: 13px; border-top: 1px solid var(--line); }
.ycmp-t { font-size: 13px; font-weight: 700; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ycmp-b { font-size: 12.5px; color: var(--ink2); margin-top: 6px; word-break: keep-all; }
@media (max-width: 720px) {
  .ylab { width: 68px; font-size: 11.5px; }
  .yval { width: 72px; font-size: 12px; }
  .yrow { gap: 8px; }
}
.hero .detail-host { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 8px; }
.mini .bw { height: 52px; display: flex; align-items: flex-end; }
.mini .mb { width: 100%; background: #E3E9EF; border-radius: 5px 5px 2px 2px; }
.mini .m.now .mb { background: var(--brand); }
.mini .ml {
  font-size: 10.5px; color: var(--ink3); text-align: center;
  margin-top: 7px; white-space: nowrap;
}
.mini .m.now .ml { color: var(--brand-deep); font-weight: 800; }

/* ---------- 통계 카드 ---------- */
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 8px; }
.stat { background: var(--surface); border-radius: var(--r-md); padding: 18px 20px; box-shadow: var(--sh); }
.stat .k { font-size: 12.5px; color: var(--ink2); font-weight: 600; }
.stat .v {
  font-size: 22px; font-weight: 800; letter-spacing: -0.04em;
  margin: 3px 0 2px; font-variant-numeric: tabular-nums;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.stat .k { min-height: 2.6em; }
.stat .s { font-size: 12px; color: var(--ink3); }

/* ---------- 번 돈 − 쓴 돈 = 남은 돈 ---------- */
.flow {
  display: grid; grid-template-columns: 1fr auto 1fr auto 1fr;
  align-items: center; gap: 6px;
  background: var(--surface); border-radius: var(--r-md);
  padding: 18px 16px; box-shadow: var(--sh);
}
.fcell { text-align: center; min-width: 0; }
.fcell.key { background: var(--brand-soft); border-radius: var(--r-sm); padding: 8px 6px; margin: -8px -2px; }
.fk { font-size: 12px; color: var(--ink2); font-weight: 700; }
.fv {
  font-size: 19px; font-weight: 800; letter-spacing: -0.04em; margin: 4px 0 2px;
  font-variant-numeric: tabular-nums; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.fv.in { color: var(--ink); }
.fs { font-size: 11.5px; color: var(--ink3); }
.fop { font-size: 17px; font-weight: 800; color: var(--ink3); padding: 0 2px; }
.tab-lead {
  font-size: 13px; color: var(--ink2); line-height: 1.6;
  margin: 0 0 18px; padding: 11px 14px;
  background: var(--surface); border-radius: var(--r-sm); box-shadow: var(--sh);
}
.tab-lead b { color: var(--ink); }
h3.sub-h { font-size: 15px; font-weight: 800; letter-spacing: -0.03em; margin: 30px 0 3px; }

/* ---------- 섹션 ---------- */
h2 { font-size: 17px; font-weight: 800; letter-spacing: -0.03em; margin: 36px 0 3px; }
.lead { color: var(--ink3); font-size: 13px; margin: 0 0 14px; }

.card { background: var(--surface); border-radius: var(--r-lg); box-shadow: var(--sh); overflow: hidden; }
.card.pad { padding: 8px 6px; }

/* ---------- 목록 행 ---------- */
.row {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 20px; cursor: pointer;
  border-radius: var(--r-md); transition: background .13s;
}
.row + .row { box-shadow: inset 0 1px 0 var(--line); }
.row:hover { background: #F8FAFB; }
.row.open { background: var(--brand-soft); box-shadow: none; }
.row.open + .row { box-shadow: none; }
.row.static { cursor: default; }
.row.static:hover { background: transparent; }

.ava {
  width: 40px; height: 40px; border-radius: 13px; flex: none;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 800; font-size: 16px; letter-spacing: -0.02em;
}
.swatch { width: 10px; height: 10px; border-radius: 3px; flex: none; }
.ico {
  width: 36px; height: 36px; border-radius: 12px; flex: none;
  display: flex; align-items: center; justify-content: center;
  font-size: 17px; line-height: 1; background: var(--brand-soft);
  font-family: "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif;
}
.ico.plain { background: #F1F3F6; }

.rmain { flex: 1; min-width: 0; }
.rtitle {
  font-size: 15px; font-weight: 700; letter-spacing: -0.02em;
  display: flex; align-items: center; gap: 7px; flex-wrap: wrap;
}
/* 이름이 글자 사이에서 끊기지 않게 한다 */
.nm { white-space: nowrap; }
.rmeta, .lead, .fb { word-break: keep-all; }
.rmeta { font-size: 12.5px; color: var(--ink3); margin-top: 1px; }
.rside { text-align: right; flex: none; }
.rval { font-size: 16px; font-weight: 800; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }
.rsub { font-size: 12px; color: var(--ink3); margin-top: 1px; font-variant-numeric: tabular-nums; }

.track { height: 6px; border-radius: 999px; background: #EDF1F5; margin-top: 8px; overflow: hidden; }
.track i {
  display: block; height: 100%; border-radius: 999px;
  background-image: linear-gradient(90deg, rgba(255,255,255,.28), rgba(255,255,255,0));
  transition: width .3s cubic-bezier(.4,0,.2,1);
}

.tag {
  font-size: 11px; font-weight: 700; border-radius: 999px;
  padding: 2px 8px; background: #F1F3F6; color: var(--ink2); white-space: nowrap;
}
.tag.warn { background: var(--up-soft); color: var(--up); }

/* ---------- 도넛 ---------- */
.donutbox { display: grid; grid-template-columns: 210px 1fr; gap: 6px; align-items: center; }
.card.focus .donutbox { grid-template-columns: 172px 1fr; align-items: start; }
/* 유형을 펼치면 총자산 도넛은 작고 흐리게 물러나고, 펼친 유형이 앞에 선다 */
.card.focus .donutcol > .donut {
  width: 96px; height: 96px; opacity: .3; filter: saturate(.55);
  margin: 6px auto 2px;
}
.card.focus .donutcol > .donut .mid .n { font-size: 11px; }
.card.focus .donutcol > .donut .mid .t { font-size: 9px; }
.donut { transition: width .22s ease, height .22s ease, opacity .22s ease; }
/* 왼쪽 칸: 총자산 도넛 아래에 지금 펼친 유형의 도넛이 따라 붙는다 */
.donutcol { position: sticky; top: 66px; }
.subdonut { padding-top: 2px; }
.subdonut[hidden] { display: none; }
.subdonut .donut { width: 150px; height: 150px; margin: 2px auto 8px; }
.subdonut .donut .mid .n { font-size: 14px; }

/* 자산 항목 상세 — 중요한 것만 단추처럼 */
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); gap: 8px; }
.fact { background: #F6F8FA; border-radius: var(--r-sm); padding: 9px 11px; }
.fact.up { background: var(--up-soft); }
.fact.loss { background: #EAF2FE; }
.fk { font-size: 10.5px; color: var(--ink3); font-weight: 700; white-space: nowrap; }
.fv {
  font-size: 13.5px; font-weight: 800; margin-top: 2px;
  letter-spacing: -0.02em; font-variant-numeric: tabular-nums; word-break: keep-all;
}
.fact.up .fv { color: var(--up); }
.fact.loss .fv { color: var(--loss); }
.dot2 { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.donut { position: relative; width: 190px; height: 190px; margin: 14px auto; }
.donut svg { width: 100%; height: 100%; display: block; transform: rotate(-90deg); }
.donut .mid {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; text-align: center; pointer-events: none;
}
.donut .mid .t { font-size: 11.5px; color: var(--ink3); font-weight: 600; }
.donut .mid .n {
  font-size: 19px; font-weight: 800; letter-spacing: -0.035em; font-variant-numeric: tabular-nums;
}

/* ---------- 월별 막대 ---------- */
.plot { position: relative; }
.yax { position: absolute; left: 0; right: 0; top: 26px; height: 170px; pointer-events: none; }
.yax i { position: absolute; left: 62px; right: 18px; height: 1px; background: var(--line); }
.yax i.zero { background: #DCE2E8; bottom: 0; }
.yax b {
  position: absolute; left: 0; width: 54px; text-align: right;
  font-size: 10.5px; color: var(--ink3); font-weight: 600;
  transform: translateY(50%); font-variant-numeric: tabular-nums; letter-spacing: -0.03em;
}
.yax b.zero { bottom: 0; }
.bars { display: flex; align-items: flex-end; gap: 14px; padding: 22px 18px 14px 68px; position: relative; }
.bcol .sum { display: none; }
.bcol.now .sum, .bcol.open .sum { display: block; }
.bars:has(.bcol.open) .bcol.now:not(.open) .sum { display: none; }
.bcol { flex: 1 1 0; min-width: 0; text-align: center; }
.bcol .area { height: 170px; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; }
.bcol .sum {
  font-size: 11.5px; font-weight: 700; margin-bottom: 7px;
  white-space: nowrap; font-variant-numeric: tabular-nums; letter-spacing: -0.04em;
}
.bcol .mon { white-space: nowrap; }
.bcol {
  cursor: pointer; border-radius: var(--r-sm);
  padding-top: 4px; transition: background .13s;
}
.bcol:hover { background: #F6F8FA; }
.bcol .stk {
  width: 100%; max-width: 78px; margin: 0 auto;
  display: flex; flex-direction: column-reverse;
  border-radius: 8px 8px 4px 4px; overflow: hidden; min-height: 3px;
  transition: box-shadow .13s;
}
.bcol .stk i { display: block; width: 100%; transition: filter .13s; }
.bcol .stk i:hover { filter: brightness(1.12); }
.bcol.open .stk { box-shadow: 0 0 0 2px var(--brand); }
.bcol.open { background: var(--brand-soft); }
.bcol .mon { font-size: 12px; color: var(--ink3); margin-top: 10px; }
.bcol.now .mon { color: var(--ink); font-weight: 700; }
.bcol.open .mon { color: var(--brand-deep); font-weight: 800; }

.legend { display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 0 20px 18px; font-size: 12.5px; color: var(--ink2); }
.legend .it { display: flex; align-items: center; gap: 7px; }
.legend b { color: var(--ink); font-weight: 700; }

/* ---------- 알림 ---------- */
.note {
  background: var(--surface); border-radius: var(--r-md);
  padding: 15px 18px; box-shadow: var(--sh); margin: 14px 0;
  font-size: 13.5px; color: var(--ink2); display: flex; gap: 12px; align-items: flex-start;
}
.note .bar { width: 3px; align-self: stretch; border-radius: 999px; background: var(--brand); flex: none; }
.note.warn .bar { background: var(--up); }
.note b, .note strong { color: var(--ink); }
.note p { margin: 0; }

.hint { font-size: 12.5px; color: var(--ink3); margin: 14px 2px 0; }

/* ---------- 보장 칩 ---------- */
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.chip {
  font-size: 11.5px; font-weight: 600; border-radius: 999px; padding: 3px 10px;
  background: var(--brand-soft); color: var(--brand-deep); white-space: nowrap;
}
.chip.off { background: #F4F6F8; color: var(--ink3); }
.chip.dup { background: var(--up-soft); color: var(--up); }
.chip .x {
  margin-left: 5px; font-size: 10.5px; font-weight: 600; opacity: .8;
  padding-left: 5px; border-left: 1px solid currentColor;
}
.chip .x.must { color: var(--up); opacity: 1; font-weight: 800; }
.chip { line-height: 1.7; padding: 4px 10px; }

.covgrp { padding: 12px 0; border-top: 1px solid var(--line); }
.covgrp:first-child { border-top: none; }
.covhead {
  font-size: 12px; font-weight: 800; color: var(--ink2);
  display: flex; align-items: center; gap: 7px; letter-spacing: -0.02em;
}
.covhead .cnt {
  font-size: 11px; font-weight: 700; color: var(--ink3);
  background: #F1F3F6; border-radius: 999px; padding: 1px 7px;
}
.chip b { font-weight: 800; }

/* ---------- 점검 항목 ---------- */
.flags { display: grid; gap: 11px; }
.flags > .more:not([hidden]) { display: grid; gap: 11px; }
.flags > .more-btn {
  background: var(--surface); border-radius: var(--r-md);
  box-shadow: var(--sh); border: none; padding: 14px;
}
.flag { background: var(--surface); border-radius: var(--r-md); padding: 17px 19px; box-shadow: var(--sh); }
.flag { padding: 0; }
.flag-head {
  display: flex; align-items: center; gap: 12px;
  padding: 16px 18px; cursor: pointer; border-radius: var(--r-md);
  transition: background .13s;
}
.flag-head:hover { background: #F8FAFB; }
.flag.open .flag-head { background: var(--brand-soft); border-radius: var(--r-md) var(--r-md) 0 0; }
.flag .fmain { flex: 1; min-width: 0; }
.flag .fsum { font-size: 12.5px; color: var(--ink3); margin-top: 3px; word-break: keep-all; }
.flag.open .chev { transform: rotate(45deg); border-color: var(--brand); }
.flag-body { padding: 4px 18px 17px; }
.flag-body[hidden] { display: none; }
.flag .ft { font-weight: 800; font-size: 14.5px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; letter-spacing: -0.02em; }
.flag .fb { font-size: 13px; color: var(--ink2); }
.flag .fq {
  font-size: 12.5px; color: var(--ink); background: #F6F8FA;
  border-radius: var(--r-sm); padding: 10px 13px; margin-top: 10px;
}
.flag .fq .q { color: var(--ink3); font-weight: 700; font-size: 11px; display: block; margin-bottom: 3px; }
.src { font-size: 11px; color: var(--ink3); margin-top: 7px; }

/* ---------- 상세 ---------- */
.detail-host { padding: 4px 6px 12px; }
.detail-inline {
  padding: 6px 4px 12px; margin: 2px 0 6px;
  background: #F8FAFB; border-radius: var(--r-sm);
  box-shadow: inset 0 1px 0 var(--line), inset 0 -1px 0 var(--line);
}
.detail-inline[hidden] { display: none; }
.detail-host[hidden] { display: none; }
.dtl-path {
  font-size: 11.5px; color: var(--ink3); padding: 2px 12px 9px;
  border-bottom: 1px solid var(--line); margin-bottom: 2px;
}
/* 단계가 깊어질수록 안쪽으로 들여쓰고 글자를 줄인다 */
.grp-items > .grp { padding: 9px 0 9px 14px; border-top: 1px dashed var(--line); }
.grp-items > .grp .grp-n { font-size: 12.5px; font-weight: 600; }
.grp-items > .grp .grp-v { font-size: 12.5px; }
.grp-items .grp-items > .grp { padding-left: 22px; }
.grp-items .grp-items > .grp .grp-n { font-size: 12px; font-weight: 500; }
.dtl-head {
  font-size: 12.5px; color: var(--ink2); font-weight: 700;
  padding: 10px 12px 8px; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;
}
/* 항목별 묶음 */
.grp { padding: 11px 12px; border-top: 1px solid var(--line); }
.grp:first-of-type { border-top: none; }
.grp-row { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.grp-n { font-weight: 700; font-size: 13.5px; flex: 1; min-width: 0; word-break: keep-all; }
.grp-c { font-size: 11.5px; color: var(--ink3); white-space: nowrap; }
.grp-v {
  font-weight: 800; font-size: 13.5px; white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.gdot { width: 9px; height: 9px; border-radius: 3px; flex: none; display: inline-block; }
.grp-items { margin-top: 10px; }
.mixwrap { margin-top: 7px; transition: width .3s cubic-bezier(.4,0,.2,1); }
.mix { display: flex; height: 9px; border-radius: 999px; overflow: hidden; background: #E9EDF1; }
.mix span {
  display: block; height: 100%;
  background-image: linear-gradient(180deg, rgba(255,255,255,.2), rgba(0,0,0,.05));
}
.mixlab { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 5px; font-size: 11px; color: var(--ink3); }
.mixc {
  display: inline-flex; align-items: center; gap: 4px; white-space: nowrap;
  border: 1px solid transparent; border-radius: 999px; padding: 2px 8px 2px 5px;
}
.mixc i { width: 6px; height: 6px; border-radius: 50%; display: inline-block; flex: none; }
.mixe { font-size: 12px; line-height: 1;
        font-family: "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif; }
.mixc b { color: var(--ink); font-weight: 800; }
.mixlab { gap: 4px 6px; }
.chev2 {
  width: 6px; height: 6px; flex: none;
  border-right: 2px solid var(--ink3); border-bottom: 2px solid var(--ink3);
  transform: rotate(-45deg); transition: transform .13s ease;
}
.grp.open > .grp-row .chev2 { transform: rotate(45deg); border-color: var(--brand); }

.dtl-row {
  display: flex; align-items: center; gap: 12px;
  padding: 9px 12px; border-radius: var(--r-sm); background: #F8FAFB; margin-bottom: 6px;
}
.dtl-main { flex: 1; min-width: 0; }
.dtl-t { font-size: 13.5px; font-weight: 700; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.dtl-s { font-size: 11.5px; color: var(--ink3); margin-top: 1px; word-break: break-all; }
.dtl-a { font-size: 14px; font-weight: 800; white-space: nowrap; font-variant-numeric: tabular-nums; }
.dtl-a.in { color: var(--brand); }
.dtl-note { font-size: 11.5px; color: var(--ink3); padding: 6px 12px 0; }

.chev {
  width: 7px; height: 7px; flex: none; margin-left: 2px;
  border-right: 2px solid var(--ink3); border-bottom: 2px solid var(--ink3);
  transform: rotate(-45deg); transition: transform .15s ease;
}
.row.open .chev { transform: rotate(45deg); border-color: var(--brand); }

/* ---------- 검산·꼬리말 ---------- */
.check {
  font-size: 12.5px; color: var(--ink3); margin: 10px 4px 0;
  display: flex; align-items: center; gap: 7px;
}
.check.ok b { color: var(--brand); }
.check.bad { color: var(--up); font-weight: 700; }

.footer {
  margin-top: 46px; background: var(--surface); border-radius: var(--r-md);
  padding: 18px 20px; box-shadow: var(--sh); font-size: 12.5px; color: var(--ink3);
}
.footer .warn { color: var(--up); font-weight: 700; }

/* ==========================================================================
   휴대폰
   ========================================================================== */
@media (max-width: 720px) {
  body { padding: 22px 16px 60px; }
  .flow { grid-template-columns: 1fr; gap: 2px; padding: 14px; }
  .fcell { display: flex; align-items: baseline; justify-content: space-between; text-align: left; gap: 10px; }
  .fcell.key { margin: 4px 0 0; padding: 10px 12px; }
  .fk { flex: 0 0 auto; }
  .fv { font-size: 17px; margin: 0; }
  .fs { flex: 1 1 100%; text-align: right; margin-top: -2px; }
  .fop { display: none; }
  .hero { padding: 22px 20px 18px; border-radius: var(--r-md); }
  .hero .v { font-size: 33px; }
  .hero .v span { font-size: 19px; }
  .stats { grid-template-columns: 1fr 1fr; gap: 10px; }
  .stat { padding: 14px 15px; }
  .stat .v { font-size: 18px; }
  .stat .k { min-height: 0; font-size: 12px; }
  .stat .s { font-size: 11.5px; }
  h2 { font-size: 16px; margin-top: 30px; }
  .card { border-radius: var(--r-md); }
  .row { padding: 11px 13px; gap: 10px; }
  .ava { width: 34px; height: 34px; border-radius: 10px; font-size: 14px; }
  .chev { display: none; }            /* 좁은 화면에서는 이름과 금액에 자리를 준다 */
  .row[data-acc] .chev { display: block; }   /* 단, 펼쳐지는 줄은 표시를 남긴다 */
  .rmeta { font-size: 11.5px; }
  .rside .rsub { font-size: 11px; }
  .rtitle { font-size: 14.5px; }
  .rval { font-size: 15px; }
  .donutbox { grid-template-columns: 1fr; }
  .donut { width: 168px; height: 168px; margin: 18px auto 6px; }
  .donutcol { position: static; display: flex; gap: 10px; justify-content: center;
              flex-wrap: wrap; align-items: center; }
  .donutcol > .donut { margin: 10px auto 2px; }
  .subdonut .donut { width: 132px; height: 132px; margin: 6px auto; }
  .subdonut .donut .mid .n { font-size: 12.5px; }
  .facts { grid-template-columns: repeat(auto-fit, minmax(108px, 1fr)); gap: 6px; }
  .fact { padding: 8px 9px; }
  .fv { font-size: 12.5px; }
  /* 좁은 화면에서는 달이 12칸이라 글자가 겹친다. 연도와 금액은 접는다 */
  .bars { gap: 5px; padding: 16px 10px 10px 44px; }
  .yax { top: 18px; height: 132px; }
  .yax i { left: 40px; right: 10px; }
  .yax b { width: 34px; font-size: 9.5px; }
  .bcol { padding-top: 2px; }
  .bcol .area { height: 132px; }
  .bcol.now .sum, .bcol.open .sum { font-size: 10.5px; }
  /* 하나를 펼치면 그 달 금액만 보여 라벨이 겹치지 않게 한다 */
  .bars:has(.bcol.open) .bcol.now:not(.open) .sum { display: none; }
  .bcol .mon { font-size: 10.5px; margin-top: 7px; }
  .bcol .mon .yy { display: none; }
  .legend { padding: 0 15px 16px; gap: 6px 14px; }
  .mini { gap: 7px; }
}

@media (max-width: 400px) {
  .hero .v { font-size: 29px; }
  .rside .rval { font-size: 13px; }
  .rtitle { font-size: 13.5px; }
  .ava { width: 30px; height: 30px; font-size: 13px; }
}

@media print {
  body { background: #fff; }
  .hint, .detail-host, .check { display: none !important; }
  .card, .hero, .stat, .footer { box-shadow: none; border: 1px solid var(--line); }
}
"""


# ============================================================================
# 홈 화면에 추가했을 때 쓸 아이콘 — 바깥 그림 파일 없이 직접 그린다
# ============================================================================
def _png(폭, 높이, 점찍기):
    """아주 단순한 PNG 만들기. 라이브러리 없이 zlib 만 쓴다."""
    줄 = bytearray()
    for y in range(높이):
        줄.append(0)                       # 필터 없음
        for x in range(폭):
            줄 += bytes(점찍기(x, y))
    def 덩이(종류, 속):
        s = 종류 + 속
        return struct.pack(">I", len(속)) + s + struct.pack(">I", zlib.crc32(s) & 0xFFFFFFFF)
    return (bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A])
            + 덩이(b"IHDR", struct.pack(">IIBBBBB", 폭, 높이, 8, 6, 0, 0, 0))
            + 덩이(b"IDAT", zlib.compress(bytes(줄), 9))
            + 덩이(b"IEND", b""))


def 아이콘만들기(경로: Path, 크기: int):
    """진한 바탕에 막대 세 개. 대시보드를 한 글자로 줄인 모양."""
    바탕 = (15, 22, 32)
    막대 = [((0, 168, 107), 0.30, 0.62), ((76, 111, 255), 0.47, 0.44), ((255, 166, 26), 0.64, 0.78)]
    둥근 = 크기 * 0.22

    def 점(x, y):
        # 모서리를 둥글린 사각형 밖이면 투명
        for cx, cy in ((둥근, 둥근), (크기 - 둥근, 둥근), (둥근, 크기 - 둥근), (크기 - 둥근, 크기 - 둥근)):
            if ((x < 둥근 and cx == 둥근) or (x > 크기 - 둥근 and cx != 둥근)) and                ((y < 둥근 and cy == 둥근) or (y > 크기 - 둥근 and cy != 둥근)):
                if (x - cx) ** 2 + (y - cy) ** 2 > 둥근 ** 2:
                    return (0, 0, 0, 0)
        for 색, 왼, 높 in 막대:
            x0 = 크기 * 왼
            x1 = x0 + 크기 * 0.13
            y0 = 크기 * (0.80 - 높 * 0.58)
            if x0 <= x <= x1 and y0 <= y <= 크기 * 0.80:
                return 색 + (255,)
        return 바탕 + (255,)

    경로.write_bytes(_png(크기, 크기, 점))


def 앱으로만들기(폴더: Path, 이름="우리집 가계"):
    """홈 화면에 추가하면 앱처럼 열리도록 아이콘과 설명 파일을 둔다."""
    폴더.mkdir(parents=True, exist_ok=True)
    for 크기 in (192, 512):
        아이콘만들기(폴더 / f"icon-{크기}.png", 크기)
    (폴더 / "manifest.json").write_text(json.dumps({
        "name": 이름, "short_name": "가계",
        "start_url": "./우리집_점검.html", "scope": "./",
        "display": "standalone", "orientation": "portrait",
        "background_color": "#F4F6F8", "theme_color": "#0F1620",
        "icons": [{"src": f"icon-{s}.png", "sizes": f"{s}x{s}", "type": "image/png",
                   "purpose": "any maskable"} for s in (192, 512)],
    }, ensure_ascii=False, indent=1), encoding="utf-8")


# ============================================================================
def 돈(n) -> str:
    return f"{n:,.0f}원"


def 짧은돈(n) -> str:
    """6,389,600 → 약 639만원"""
    n = abs(round(n))
    if n >= 100_000_000:
        return f"약 {n/100_000_000:.1f}억원"
    if n >= 10_000:
        return f"약 {n//10_000:,}만원"
    return f"{n:,}원"


def 막대금액(n) -> str:
    """막대 위에 얹는 아주 짧은 표기. 12,730,289 → 1,273만"""
    n = abs(round(n))
    if n >= 100_000_000:
        return f"{n/100_000_000:.1f}억"
    if n >= 10_000:
        return f"{n//10_000:,}만"
    return f"{n:,}"


def 눈금값(최대, 개수=4):
    """0 위로 올릴 눈금 금액을 보기 좋은 단위로 고른다. 17,169,000 → 500만·1,000만·1,500만"""
    if 최대 <= 0:
        return []
    거친 = 최대 / 개수
    자리 = 10 ** math.floor(math.log10(거친))
    간격 = 자리 * 10
    for c in (1, 2, 2.5, 5, 10):
        if c * 자리 >= 거친:
            간격 = c * 자리
            break
    값, v = [], 간격
    while v <= 최대 * 1.001:
        값.append(int(round(v)))
        v += 간격
    return 값


def 눈금선(눈금, 최대):
    """막대 뒤에 가로선을 깔고 왼쪽에 금액을 적는다.

    막대마다 숫자를 얹으면 24칸에서 전부 겹친다. 축으로 옮기면 한 번만 읽으면 된다.
    """
    값들 = 눈금값(최대)
    if not 값들 or 눈금 <= 0:
        return ""
    칸 = "".join(f'<i style="bottom:{v / 눈금 * 100:.2f}%"></i>'
                f'<b style="bottom:{v / 눈금 * 100:.2f}%">{막대금액(v)}</b>' for v in 값들)
    return f'<div class="yax"><i class="zero"></i><b class="zero">0</b>{칸}</div>'


def esc(s) -> str:
    return html.escape(str(s))


def 은는(말: str) -> str:
    """받침이 있으면 '은', 없으면 '는'."""
    if not 말:
        return "는"
    끝 = 말[-1]
    if not ("가" <= 끝 <= "힣"):
        return "는"
    return "은" if (ord(끝) - 0xAC00) % 28 else "는"


def 머리글자(이름: str) -> str:
    """아바타에 넣을 한 글자. '아빠_김정우' → '아'"""
    s = str(이름).strip()
    return s[0] if s else "?"


def 접기(행들, 보일수=5, 단위="개"):
    """목록이 길면 앞부분만 보이고 나머지는 눌러서 펼친다 (단계적 공개)."""
    if len(행들) <= 보일수:
        return "".join(행들)
    남 = len(행들) - 보일수
    return ("".join(행들[:보일수]) +
            f'<div class="more" hidden>{"".join(행들[보일수:])}</div>'
            f'<button class="more-btn" type="button">나머지 {남}{단위} 더 보기</button>')


def 증감칩(차이, 기준=None):
    if 차이 == 0 or 기준 in (0, None):
        return '<span class="pill flat">변화 없음</span>'
    비율 = 차이 / 기준 * 100
    cls, 기호 = ("up", "▲") if 차이 > 0 else ("down", "▼")
    return f'<span class="pill {cls}">{기호} {abs(비율):.0f}%</span>'


# ============================================================================
# 자료 읽기와 집계 (계산은 여기서만 한다)
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

    사람별, 카테고리별 = defaultdict(int), defaultdict(int)
    월별, 월사람, 월카테고리 = defaultdict(int), defaultdict(int), defaultdict(int)
    수혜자별, 월수혜자, 수혜자카테고리 = defaultdict(int), defaultdict(int), defaultdict(int)

    for t in 지출:
        금 = -t["금액"]                      # 지출은 음수로 저장돼 있다
        월 = t["날짜"][:7]
        받은 = t.get("수혜자") or t["사람"]
        사람별[t["사람"]] += 금
        수혜자별[받은] += 금
        카테고리별[t["카테고리"]] += 금
        월별[월] += 금
        월사람[(월, t["사람"])] += 금
        월수혜자[(월, 받은)] += 금
        월카테고리[(월, t["카테고리"])] += 금
        수혜자카테고리[(받은, t["카테고리"])] += 금

    def 정렬(d):
        return sorted(d, key=lambda k: (k == "가족공통", -d[k]))   # 가족공통은 뒤로

    return {
        "지출": 지출, "수입": 수입, "이체": 이체,
        "사람별": dict(사람별), "카테고리별": dict(카테고리별),
        "수혜자별": dict(수혜자별), "월수혜자": dict(월수혜자),
        "수혜자카테고리": dict(수혜자카테고리),
        "월별": dict(월별), "월사람": dict(월사람), "월카테고리": dict(월카테고리),
        "총지출": sum(사람별.values()),
        "총수입": sum(t["금액"] for t in 수입),
        "달들": sorted(월별),
        "사람들": sorted(사람별, key=lambda k: -사람별[k]),
        "수혜자들": 정렬(수혜자별),
    }


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
        if len(달) != 관측개월 or len(ts) != 관측개월:   # 매달 빠짐없이, 한 달에 한 번
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
        결과.append({
            "가맹점": 가맹점, "사람": 사람,
            "월금액": round(평균), "연환산": round(평균 * 12),
            "카테고리": ts[0]["카테고리"],
            "확신": 확신, "마지막": max(t["날짜"] for t in ts),
            "근거": (f"{관측개월}개월 내내 · 금액 편차 {금액편차*100:.1f}% · "
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
    행 = []
    for c in sorted({c for (m, c) in A["월카테고리"]}):
        a = A["월카테고리"].get((이번, c), 0)
        b = A["월카테고리"].get((지난, c), 0)
        if a == 0 and b == 0:
            continue
        행.append({"카테고리": c, "이번달": a, "지난달": b, "차이": a - b,
                   "비율": None if b == 0 else (a - b) / b * 100})
    행.sort(key=lambda r: -abs(r["차이"]))
    return 이번, 지난, 행


# ============================================================================
# 자산 · 가족 · 보험 (거래가 아니라 현황 자료)
# ============================================================================


def 표읽기(path: Path):
    if not path or not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def 자산집계(행들):
    분류별, 항목 = defaultdict(int), []
    for r in 행들:
        try:
            금 = int(str(r.get("평가금액", "")).replace(",", "").strip() or 0)
        except ValueError:
            continue
        분류 = (r.get("분류") or "기타").strip()
        분류별[분류] += 금

        def 숫자(칸):
            try:
                return float(str(r.get(칸, "")).replace(",", "").strip() or 0)
            except ValueError:
                return 0

        항목.append({"사람": (r.get("사람") or "").strip(), "분류": 분류,
                    "세부항목": (r.get("세부항목") or "").strip(),
                    "기관": (r.get("기관") or "").strip(), "금액": 금,
                    "원금": int(숫자("원금")), "이율": 숫자("이율"),
                    "만기일": (r.get("만기일") or "").strip(),
                    "기준일": (r.get("기준일") or "").strip(),
                    "비고": (r.get("비고") or "").strip()})
    자산 = sum(v for k, v in 분류별.items() if k != "부채")
    부채 = 분류별.get("부채", 0)
    항목.sort(key=lambda x: -x["금액"])
    return {"분류별": dict(분류별), "항목": 항목, "총자산": 자산, "부채": 부채, "순자산": 자산 - 부채}


def 실손세대(계약일: str) -> str:
    """판매 시기로 실손보험 세대를 구분한다 (1세대 ~2009.09 / 2세대 ~2017.03 / 3세대 ~2021.06 / 4세대~)."""
    try:
        d = dt.date.fromisoformat(계약일[:10])
    except (ValueError, TypeError):
        return ""
    if d < dt.date(2009, 10, 1):
        return "1세대"
    if d < dt.date(2017, 4, 1):
        return "2세대"
    if d < dt.date(2021, 7, 1):
        return "3세대"
    return "4세대"


실손자기부담 = {
    "1세대": "자기부담이 거의 없는 대신 보험료가 비싼 편입니다.",
    "2세대": "표준형 기준 자기부담률이 20%입니다.",
    "3세대": "비급여는 30%와 2만원 중 큰 금액을 본인이 부담합니다.",
    "4세대": "비급여는 30%와 3만원 중 큰 금액을 본인이 부담합니다.",
}

# 실제 손해액까지만 보상되는 담보 — 여러 건 들어도 합쳐서 더 받지 못한다
비례보상담보 = {"실손_급여", "실손_비급여", "배상책임", "자동차_대물배상", "자동차_자기차량손해"}

# 보험 약관에 흔히 들어가는 보장 항목을 갈래별로 모은 점검표.
# 가입 여부를 한눈에 보려고 쓰는 목록이지, 모두 들어야 한다는 뜻도
# 법으로 정해진 표준도 아니다. (자동차 의무 담보만 예외로 아래에 표시)
표준보장 = [
    ("사망·장해",   ["사망_일반", "사망_재해", "후유장해"]),
    ("암·큰 병",    ["암_일반암", "암_유사암", "뇌혈관질환", "허혈성심장질환"]),
    ("의료비",      ["실손_급여", "실손_비급여", "입원일당", "수술비"]),
    ("간병·노후",   ["간병_장기요양", "치매"]),
    ("생활 위험",   ["치아", "배상책임", "화재_재물"]),
    ("자동차·운전", ["자동차_대인배상1", "자동차_대인배상2", "자동차_대물배상",
                  "자동차_자기신체사고", "자동차_자기차량손해", "자동차_무보험차상해",
                  "운전자_벌금", "운전자_형사합의", "운전자_변호사선임"]),
]
표준보장전체 = [항 for _, 항들 in 표준보장 for 항 in 항들]

# 자동차손해배상보장법상 의무 가입 담보
의무담보 = {"자동차_대인배상1", "자동차_대물배상"}


def 금액읽기_문자(s):
    s = (s or "").strip()
    if not s:
        return None
    if s in ("무한", "무제한"):
        return "무한"
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return s


def 보험집계(행들):
    증권, 보장 = {}, defaultdict(lambda: defaultdict(list))
    for r in 행들:
        사람 = (r.get("사람") or "").strip()
        보험사 = (r.get("보험사") or "").strip()
        상품 = (r.get("상품명") or "").strip()
        if not (사람 and 보험사):
            continue
        키 = (사람, 보험사, 상품)
        if 키 not in 증권:
            증권[키] = {"사람": 사람, "보험사": 보험사, "상품명": 상품,
                      "계약일": (r.get("계약일") or "").strip(),
                      "만기일": (r.get("만기일") or "").strip(),
                      "월보험료": 0, "갱신형": (r.get("갱신형") or "").strip(),
                      "비고": (r.get("비고") or "").strip(), "보장": []}
        보험료 = 금액읽기_문자(r.get("월보험료"))
        if isinstance(보험료, int):
            증권[키]["월보험료"] = 보험료
        항목 = (r.get("보장항목") or "").strip()
        금 = 금액읽기_문자(r.get("보장금액"))
        if 항목:
            증권[키]["보장"].append((항목, 금))
            보장[항목][사람].append({"보험사": 보험사, "상품명": 상품, "금액": 금,
                                  "비고": (r.get("비고") or "").strip()})
    return {"증권": list(증권.values()), "보장": {k: dict(v) for k, v in 보장.items()}}


def 보험점검(보험, 가족들, 고정비들, 월지출):
    """사실만 짚고, 확인할 질문을 붙인다. 가입·해지를 권하지 않는다."""
    오늘 = dt.date.today()
    신호 = []

    # 1) 실손처럼 실제 손해액까지만 보상되는 담보를 한 사람이 두 건 이상 가진 경우
    for 항목, 사람별 in 보험["보장"].items():
        if 항목 not in 비례보상담보:
            continue
        for 사람, 건들 in 사람별.items():
            if len(건들) >= 2:
                목록 = ", ".join(f'{b["보험사"]} {b["상품명"]}' for b in 건들)
                신호.append({
                    "급": "warn", "제목": f"{사람} · {항목} 보장이 {len(건들)}건입니다",
                    "본문": (f"{목록}. 실손의료보험처럼 실제 부담한 금액까지만 보상하는 담보는 "
                           f"여러 건에 가입해도 실제 의료비를 넘겨 받지 못합니다(비례보상). "
                           f"개인 실손과 회사 단체 실손이 겹칠 때는 실손보험 중지제도를 쓸 수 있습니다."),
                    "질문": "두 건이 각각 얼마씩 나눠 보상되는지, 중지제도를 쓸 수 있는 조건은 무엇인지 확인하고 싶습니다.",
                    "출처": "금융감독원 실손보험 중복가입 안내",
                })

    # 2) 보장이 아예 없는 가족
    가입자 = {s["사람"] for s in 보험["증권"]}
    for 이름 in 가족들:
        if 이름 not in 가입자:
            신호.append({
                "급": "warn", "제목": f"{이름} 님은 등록된 증권이 한 건도 없습니다",
                "본문": "다른 가족은 실손·암 보장을 가지고 있는데 이 사람만 비어 있습니다. "
                      "실제로 없는 것인지, 증권을 아직 못 옮겨 적은 것인지 확인이 필요합니다.",
                "질문": "이 사람 앞으로 된 보험이 있는지, 있다면 증권을 다시 받을 수 있는지 알고 싶습니다.",
                "출처": "",
            })
        else:
            없는것 = [항 for 항 in ("실손_급여", "암_일반암")
                    if 이름 not in 보험["보장"].get(항, {})]
            if 없는것:
                신호.append({
                    "급": "info", "제목": f"{이름} 님은 {' · '.join(없는것)} 보장이 없습니다",
                    "본문": "가족 중 다른 사람은 가지고 있는 보장입니다. 빠진 것인지 일부러 넣지 않은 것인지 확인해 보세요.",
                    "질문": f"{' · '.join(없는것)} 보장이 정말 없는지, 다른 증권에 포함돼 있지는 않은지 확인하고 싶습니다.",
                    "출처": "",
                })

    # 3) 실손 세대 안내
    세대표 = []
    for s in 보험["증권"]:
        if any(항.startswith("실손") for 항, _ in s["보장"]):
            g = 실손세대(s["계약일"])
            if g:
                세대표.append(f'{s["사람"]} {s["보험사"]} <b>{g}</b> — {실손자기부담[g]}')
    if 세대표:
        신호.append({
            "급": "info", "제목": "실손보험은 가입 시기에 따라 자기부담이 다릅니다",
            "본문": "<br>".join(세대표),
            "질문": "내 실손이 몇 세대이고 비급여 자기부담이 얼마인지, 전환하면 무엇이 달라지는지 설명을 듣고 싶습니다.",
            "출처": "실손의료보험 세대 구분 (2009.10 / 2017.04 / 2021.07 판매 기준)",
        })

    # 4) 만기·갱신이 1년 안에 오는 것
    임박 = []
    for s in 보험["증권"]:
        try:
            만기 = dt.date.fromisoformat(s["만기일"][:10])
        except (ValueError, TypeError):
            continue
        남은 = (만기 - 오늘).days
        if 0 <= 남은 <= 365:
            임박.append(f'{s["사람"]} {s["보험사"]} {s["상품명"]} — {만기} (D-{남은})')
    if 임박:
        신호.append({
            "급": "info", "제목": f"1년 안에 만기·갱신이 오는 증권 {len(임박)}건",
            "본문": "<br>".join(임박),
            "질문": "갱신하면 보험료가 얼마가 되는지, 보장 내용이 달라지는 부분이 있는지 미리 알고 싶습니다.",
            "출처": "",
        })

    # 5) 암보험 면책·감액 안내
    암증권 = [s for s in 보험["증권"] if any(항.startswith("암") for 항, _ in s["보장"])]
    if 암증권:
        신호.append({
            "급": "info", "제목": "암보험은 가입 직후 바로 다 나오지 않습니다",
            "본문": ("보통 가입일부터 90일이 지나야 보장이 시작되고(면책 기간), 그 뒤로도 1~2년 동안은 "
                   "진단금의 절반만 지급하는 감액 기간을 두는 경우가 많습니다. "
                   "유사암(갑상선암 등)은 면책이 적용되지 않는 대신 진단금이 일반암보다 훨씬 적습니다."),
            "질문": "내 암보험의 면책 기간과 감액 기간이 언제 끝나는지, 유사암 진단금은 얼마인지 확인하고 싶습니다.",
            "출처": "암보험 약관 일반 조건",
        })

    # 6) 자동차보험 의무 담보
    차증권 = [s for s in 보험["증권"] if any(항.startswith("자동차") for 항, _ in s["보장"])]
    if 차증권:
        신호.append({
            "급": "info", "제목": "자동차보험 의무 담보가 들어 있는지 확인해 두세요",
            "본문": ("대인배상Ⅰ과 대물배상 2천만원 이상은 법으로 정해진 의무 가입 담보입니다. "
                   "대인배상Ⅱ·자기신체사고·무보험차상해·자기차량손해는 종합보험 쪽이라 선택입니다."),
            "질문": "지금 가입한 자동차보험에 의무 담보가 모두 들어 있는지, 자기부담금은 얼마인지 확인하고 싶습니다.",
            "출처": "자동차손해배상보장법상 의무보험",
        })

    # 7) 증권 ↔ 실제 출금 대조 (이 도구의 핵심)
    증권료 = defaultdict(int)
    for s in 보험["증권"]:
        if s["월보험료"]:
            증권료[s["보험사"]] += s["월보험료"]
    출금 = defaultdict(int)
    for f in 고정비들:
        if f["카테고리"] == "보험":
            보험사 = f["가맹점"].split()[0]
            출금[보험사] += f["월금액"]

    for 보험사 in sorted(set(증권료) | set(출금)):
        증, 출 = 증권료.get(보험사, 0), 출금.get(보험사, 0)
        if 증 == 0 and 출 > 0:
            신호.append({
                "급": "warn", "제목": f"증권 목록에 없는데 매달 {돈(출)}이 나가고 있어요 — {보험사}",
                "본문": "거래 내역에는 매달 같은 날 같은 금액이 빠져나가는데, 옮겨 적은 증권 목록에는 없습니다. "
                      "가계부 앱은 소비만, 보험 앱은 보험만 보기 때문에 이런 건 어느 쪽에서도 잘 안 잡힙니다.",
                "질문": f"{보험사}에서 매달 {돈(출)}이 출금되는데 어떤 보험인지, 증권을 다시 받을 수 있는지 알고 싶습니다.",
                "출처": "",
            })
        elif 출 == 0 and 증 > 0:
            신호.append({
                "급": "info", "제목": f"증권은 있는데 출금 기록이 안 보여요 — {보험사} (월 {돈(증)})",
                "본문": "다른 계좌에서 나가고 있거나, 회사가 대신 내고 있거나, 이미 끝난 계약일 수 있습니다.",
                "질문": f"{보험사} 보험료가 어느 계좌에서 나가고 있는지, 계약이 유지 중인지 확인하고 싶습니다.",
                "출처": "",
            })
        elif 증 and 출 and abs(증 - 출) > max(1000, 증 * 0.05):
            신호.append({
                "급": "info", "제목": f"증권상 보험료와 실제 출금액이 다릅니다 — {보험사}",
                "본문": f"증권 기준 월 {돈(증)} / 실제 출금 월 {돈(출)} (차이 {돈(abs(증-출))}). "
                      f"가족 중 일부 증권이 다른 계좌에서 나가거나, 갱신으로 보험료가 바뀌었을 수 있습니다.",
                "질문": f"{보험사}에 가입된 계약이 모두 몇 건이고 각각 얼마씩 나가는지 확인하고 싶습니다.",
                "출처": "",
            })

    # 8) 보험료 부담 비중 (사실 계산)
    총보험료 = sum(s["월보험료"] for s in 보험["증권"])
    if 총보험료 and 월지출:
        신호.append({
            "급": "info", "제목": f"증권 기준 월 보험료는 {돈(총보험료)}입니다",
            "본문": f"가구 월평균 지출 {돈(월지출)}의 <b>{총보험료/월지출*100:.1f}%</b>, "
                  f"1년이면 {짧은돈(총보험료*12)}입니다.",
            "질문": "지금 보장 내용에 비해 보험료가 적정한지, 같은 보장을 유지하면서 조정할 여지가 있는지 묻고 싶습니다.",
            "출처": "",
        })

    순서 = {"warn": 0, "info": 1}
    신호.sort(key=lambda s: 순서.get(s["급"], 9))
    return 신호


# ============================================================================
# 화면 조각
# ============================================================================
def 히어로(A, 이번, 지난):
    비교 = '<span class="pill flat">비교할 지난달 자료 없음</span>'
    if 이번 and 지난 and A["월별"].get(지난):
        d = A["월별"][이번] - A["월별"][지난]
        비교 = (f'{증감칩(d, A["월별"][지난])}'
                f'<span>{esc(지난)} {돈(A["월별"][지난])} → '
                f'<b style="color:var(--ink)">{esc(이번)} {돈(A["월별"][이번])}</b></span>')

    보일달 = A["달들"][-12:]
    값들 = [A["월별"][m] for m in 보일달]
    최대, 최소 = max(값들), min(값들)
    폭 = (최대 - 최소) or 최대 or 1
    칸 = []
    for m in 보일달:
        v = A["월별"][m]
        높이 = 34 + (v - 최소) / 폭 * 66      # 차이가 작아도 눈에 보이게 아래를 띄운다
        이번달 = " now" if m == 이번 else ""
        칸.append(f'<div class="m{이번달}" data-kind="month" data-key="{esc(m)}" '
                  f'title="{esc(m)} {돈(v)} — 눌러서 보기">'
                  f'<div class="bw"><div class="mb" style="height:{높이:.1f}%"></div></div>'
                  f'<div class="ml">{int(m[5:])}월</div></div>')

    return f"""<div class="hero" data-group>
  <div class="k">가구 총지출 · {esc(A["달들"][0])} ~ {esc(A["달들"][-1])}</div>
  <div class="v tnum">{A["총지출"]:,}<span>원</span></div>
  <div class="cmp">{비교}</div>
  <div class="mini">{''.join(칸)}</div>
  <div class="detail-host" hidden></div>
  <div class="minihint">막대를 누르면 그달 내역이 열립니다</div>
</div>"""


def 다음달예상(A, 고정비월합):
    """최근 석 달 평균과 작년 같은 달을 함께 보여준다. 예측이 아니라 참고용 수치다."""
    달들 = A["달들"]
    if len(달들) < 3:
        return ""
    끝 = dt.date.fromisoformat(달들[-1] + "-01")
    다음 = (끝.replace(day=28) + dt.timedelta(days=7)).replace(day=1).strftime("%Y-%m")
    최근3 = sum(A["월별"][m] for m in 달들[-3:]) // 3
    작년 = A["월별"].get(f"{int(다음[:4])-1}-{다음[5:]}")

    꼬리 = f" · 작년 같은 달 {짧은돈(작년)}" if 작년 else ""
    변동 = max(0, 최근3 - 고정비월합)
    return f"""<div class="stat" style="grid-column:1/-1;margin-top:2px">
  <div class="k">{esc(다음)} 예상 지출</div>
  <div class="v tnum">{돈(최근3)}</div>
  <div class="s">최근 석 달 평균 기준{꼬리}<br>
    이 가운데 {돈(고정비월합)}은 이미 정해진 고정비, 나머지 {돈(변동)}이 쓰기 나름입니다.</div>
</div>"""


def 연도비교(A):
    """해마다 얼마나 썼는지, 그리고 같은 기간끼리 견주면 올해가 어떤지.

    연 총액만 비교하면 진행 중인 해가 무조건 적게 나온다.
    작년 대비 초과 여부는 '같은 달까지'를 잘라 견줘야 뜻이 있다.
    """
    해별, 해월 = defaultdict(int), defaultdict(set)
    for m, v in A["월별"].items():
        해별[m[:4]] += v
        해월[m[:4]].add(m[5:])
    해들 = sorted(해별)
    if len(해들) < 2:
        return ""

    올해 = 해들[-1]
    작년 = 해들[-2]
    같은달 = sorted(해월[올해] & 해월[작년])
    올해같은 = sum(A["월별"][f"{올해}-{d}"] for d in 같은달)
    작년같은 = sum(A["월별"][f"{작년}-{d}"] for d in 같은달)

    최대 = max(해별.values()) or 1
    단계 = 농담(len(해들))
    줄 = []
    for i, y in enumerate(해들):
        진행 = " (자료 " + f"{len(해월[y])}개월)" if len(해월[y]) < 12 else ""
        줄.append(f"""<div class="yrow">
  <div class="ylab">{esc(y)}년<span>{진행}</span></div>
  <div class="ybar"><i style="width:{해별[y]/최대*100:.1f}%;background:{단계[i]}"></i></div>
  <div class="yval tnum">{짧은돈(해별[y])}</div>
</div>""")

    견줌 = ""
    if 같은달 and 작년같은:
        차 = 올해같은 - 작년같은
        비 = 차 / 작년같은 * 100
        칩 = 증감칩(차, 작년같은)
        기간 = f"{int(같은달[0])}~{int(같은달[-1])}월" if len(같은달) > 1 else f"{int(같은달[0])}월"
        말 = ("작년 같은 기간보다 많이 쓰고 있습니다." if 차 > 0
              else "작년 같은 기간보다 적게 쓰고 있습니다." if 차 < 0
              else "작년 같은 기간과 거의 같습니다.")
        견줌 = f"""<div class="ycmp">
  <div class="ycmp-t">같은 기간({기간})끼리 견주면 {칩}</div>
  <div class="ycmp-b">{esc(작년)}년 {돈(작년같은)} → <b>{esc(올해)}년 {돈(올해같은)}</b>
    · {돈(abs(차))} {"더" if 차 > 0 else "덜"} 썼습니다. {말}</div>
</div>"""
    else:
        견줌 = ('<div class="ycmp"><div class="ycmp-b">두 해에 겹치는 달이 없어 '
                '같은 기간끼리 견주지 못했습니다. 자료가 더 쌓이면 보여드려요.</div></div>')

    return f"""<div class="card" style="padding:16px 18px">
  <div class="ytitle">해마다 견주기</div>
  {''.join(줄)}
  {견줌}
</div>"""


def 통계카드(A, 자산, 고정비월합, 고정비연합, 확인):
    개월 = max(1, len(A["달들"]))
    남은돈 = A["총수입"] - A["총지출"]
    남은비율 = 남은돈 / A["총수입"] * 100 if A["총수입"] else 0
    자산카드 = ""
    if 자산["총자산"]:
        자산카드 = f"""<div class="stat"><div class="k">총자산</div>
    <div class="v tnum" style="color:var(--brand-deep)">{짧은돈(자산["총자산"])}</div>
    <div class="s">{'순자산 ' + 짧은돈(자산["순자산"]) if 자산["부채"] else 돈(자산["총자산"])}</div></div>"""
    return f"""<div class="stats">
  {자산카드}
  <div class="stat"><div class="k">매달 빠져나가는 고정비</div>
    <div class="v tnum">{돈(고정비월합)}</div>
    <div class="s">1년이면 {짧은돈(고정비연합)}</div></div>
  <div class="stat"><div class="k">쓰고 남은 돈</div>
    <div class="v tnum" style="color:{'var(--brand-deep)' if 남은돈 > 0 else 'var(--up)'}">
      {'' if 남은돈 > 0 else '−'}{짧은돈(abs(남은돈))}</div>
    <div class="s">월평균 수입 {짧은돈(A["총수입"] / 개월)} 중 {남은비율:.0f}%</div></div>
  <div class="stat"><div class="k">확인할 항목</div>
    <div class="v tnum" style="color:{'var(--up)' if 확인 else 'var(--ink)'}">{확인}건</div>
    <div class="s">아래에서 하나씩 짚어드려요</div></div>
  {다음달예상(A, 고정비월합)}
</div>"""


def 구역_수입(A, 색맵):
    """번 돈 · 쓴 돈 · 남은 돈. 지금까지 대시보드에 없던 반쪽이다.

    지출만 보면 '많이 썼다/적게 썼다'밖에 알 수 없다.
    번 돈과 나란히 놓아야 그게 감당할 만한 소비였는지가 보인다.
    """
    수입들 = A["수입"]
    if not 수입들:
        return ('<div class="note"><div class="bar"></div><p>수입으로 잡힌 거래가 없습니다. '
                '급여가 들어오는 <b>은행 거래내역</b>을 폴더에 넣으면 여기에 표시됩니다.</p></div>')

    개월 = max(1, len(A["달들"]))
    번돈, 쓴돈 = A["총수입"], A["총지출"]
    남은돈 = 번돈 - 쓴돈

    사람별, 월별 = {}, {}
    for x in 수입들:
        사람별[x["사람"]] = 사람별.get(x["사람"], 0) + x["금액"]
        월별[x["날짜"][:7]] = 월별.get(x["날짜"][:7], 0) + x["금액"]

    비율 = 남은돈 / 번돈 * 100 if 번돈 else 0
    좋음 = 남은돈 > 0
    흐름 = f"""<div class="flow">
  <div class="fcell"><div class="fk">번 돈</div>
    <div class="fv in tnum">{돈(번돈)}</div>
    <div class="fs">월평균 {짧은돈(번돈 / 개월)}</div></div>
  <div class="fop">−</div>
  <div class="fcell"><div class="fk">쓴 돈</div>
    <div class="fv tnum">{돈(쓴돈)}</div>
    <div class="fs">월평균 {짧은돈(쓴돈 / 개월)}</div></div>
  <div class="fop">=</div>
  <div class="fcell key"><div class="fk">남은 돈</div>
    <div class="fv tnum" style="color:{'var(--brand-deep)' if 좋음 else 'var(--up)'}">
      {'' if 좋음 else '−'}{돈(남은돈)}</div>
    <div class="fs">번 돈의 {비율:.0f}% · 월평균 {짧은돈(abs(남은돈) / 개월)}</div></div>
</div>"""

    쓴폭 = min(100, 쓴돈 / 번돈 * 100) if 번돈 else 100
    띠 = f"""<div class="split" style="margin-top:12px">
  <span style="width:{쓴폭:.1f}%;background:{회색}" title="쓴 돈 {돈(쓴돈)}"></span>
  <span style="width:{100 - 쓴폭:.1f}%;background:var(--brand)" title="남은 돈 {돈(남은돈)}"></span>
</div>
<div class="legend">
  <span class="it"><span class="swatch" style="border-radius:50%;background:{회색}"></span>
    <b>쓴 돈</b> {쓴폭:.0f}%</span>
  <span class="it"><span class="swatch" style="border-radius:50%;background:var(--brand)"></span>
    <b>남은 돈</b> {100 - 쓴폭:.0f}%</span>
</div>"""

    벌이 = sorted(사람별.items(), key=lambda kv: -kv[1])
    행 = []
    for 사람, 금 in 벌이:
        큰것 = sorted(((x["가맹점"], x["금액"]) for x in 수입들 if x["사람"] == 사람),
                    key=lambda kv: -kv[1])
        이름들 = []
        for 가맹점, _ in 큰것:
            if 가맹점 not in 이름들:
                이름들.append(가맹점)
        행.append(f"""<div class="row" data-kind="income" data-key="{esc(사람)}">
  <div class="ava" style="background:{색맵.get(사람, 회색)}">{esc(머리글자(사람))}</div>
  <div class="rmain">
    <div class="rtitle"><span class="nm">{esc(사람)}</span></div>
    <div class="rmeta">월평균 {짧은돈(금 // 개월)} · {esc(" · ".join(이름들[:3]))}</div>
    <div class="track"><i style="width:{금 / 번돈 * 100:.1f}%;
      background:{색맵.get(사람, 회색)}"></i></div>
  </div>
  <div class="rside"><div class="rval tnum">{돈(금)}</div>
    <div class="rsub">{금 / 번돈 * 100:.1f}%</div></div>
  <div class="chev"></div>
</div>""")

    최대 = max(월별.values()) or 1
    눈금 = 최대 * 1.04
    # 평균은 성과급 달에 끌려 올라가므로 가운뎃값을 평달 기준으로 쓴다
    줄 = sorted(월별.get(m, 0) for m in A["달들"])
    평달 = 줄[len(줄) // 2] if 줄 else 0
    칸들 = []
    for 월 in A["달들"]:
        합 = 월별.get(월, 0)
        튐 = 합 > 평달 * 1.1
        칸들.append(f"""<div class="bcol" data-kind="incomemonth" data-key="{esc(월)}">
  <div class="area">
    <div class="sum" style="color:{'var(--brand-deep)' if 튐 else 'var(--ink3)'}">
      {막대금액(합)}</div>
    <div class="stk" style="height:{합 / 눈금 * 100:.2f}%">
      <i style="height:100%;background:{'var(--brand)' if 튐 else '#9FB3C8'}"
         title="{esc(월)} 수입 {돈(합)}"></i></div>
  </div>
  <div class="mon"><span class="yy">{esc(월[:4])}.</span>{int(월[5:])}월</div>
</div>""")

    return f"""{흐름}{띠}
<div class="card pad" data-group style="margin-top:14px">{"".join(행)}
  <div class="detail-host" hidden></div>
</div>
<h3 class="sub-h">언제 들어왔나</h3>
<p class="lead">성과급이나 상여가 들어온 달은 <b>진한 색</b>으로 표시했습니다.</p>
<div class="card" data-group><div class="plot">{눈금선(눈금, 최대)}
  <div class="bars">{"".join(칸들)}</div></div>
  <div class="detail-host" hidden></div></div>
<div class="check">세로 눈금은 왼쪽에 있습니다. 막대를 누르면 그달에 들어온 돈이 하나씩 열려요.</div>"""


def 목록_수혜자(A, 색맵):
    """누구를 위해 쓴 돈인지. 돈을 낸 사람이 아니라 그 돈이 쓰인 사람 기준."""
    총, 개월 = A["총지출"], max(1, len(A["달들"]))
    행 = []
    for 사람 in A["수혜자들"]:
        금 = A["수혜자별"][사람]
        추이 = [A["월수혜자"].get((m, 사람), 0) for m in A["달들"]]
        칩 = 증감칩(추이[-1] - 추이[-2], 추이[-2]) if len(추이) >= 2 else ""
        큰것 = sorted(((c, v) for (p, c), v in A["수혜자카테고리"].items() if p == 사람),
                    key=lambda kv: -kv[1])[:1]
        설명 = 큰것[0][0] if 큰것 else "-"
        행.append(f"""<div class="row" data-kind="beneficiary" data-key="{esc(사람)}">
  <div class="ava" style="background:{색맵[사람]}">{esc(머리글자(사람))}</div>
  <div class="rmain">
    <div class="rtitle"><span class="nm">{esc(사람)}</span>{칩}</div>
    <div class="rmeta">월 {짧은돈(금//개월)} · {esc(설명)}</div>
    <div class="track"><i style="width:{금/총*100:.1f}%;background:{색맵[사람]}"></i></div>
  </div>
  <div class="rside"><div class="rval tnum">{돈(금)}</div>
    <div class="rsub">{금/총*100:.1f}%</div></div>
  <div class="chev"></div>
</div>""")

    합 = sum(A["수혜자별"].values())
    검산 = (f'<div class="check ok">수혜자 합계 <b>{돈(합)}</b> = 가구 총지출 {돈(총)} ✓</div>'
            if 합 == 총 else
            f'<div class="check bad">검산 불일치: 수혜자 합계 {돈(합)} ≠ 가구 총지출 {돈(총)} ✗</div>')

    전체판 = (f'{비중막대([(p, A["수혜자별"][p]) for p in A["수혜자들"]], 색맵)}'
             f'<div class="card pad" data-group>{"".join(행)}'
             f'<div class="detail-host" hidden></div></div>{검산}')

    버튼 = ['<button class="sub-btn" type="button" data-sub="who-all" '
           'aria-selected="true">전체 비교</button>']
    판들 = [f'<div class="subpanel" id="who-all">{전체판}</div>']
    for i, 사람 in enumerate(A["수혜자들"]):
        버튼.append(f'<button class="sub-btn" type="button" data-sub="who-{i}" aria-selected="false">'
                   f'<span class="dot" style="background:{색맵[사람]};width:8px;height:8px;'
                   f'border-radius:50%;display:inline-block"></span>'
                   f'{esc(사람.split("_")[0])}</button>')
        판들.append(f'<div class="subpanel" id="who-{i}" hidden>{사람소비판(사람, A, 색맵)}</div>')

    return (f'<div data-subgroup><div class="subtabs">{"".join(버튼)}</div>'
            f'{"".join(판들)}</div>')


def 사람소비판(사람, A, 색맵):
    """한 사람 몫의 지출만 카테고리별로 모아 보여준다."""
    금, 개월 = A["수혜자별"][사람], max(1, len(A["달들"]))
    추이 = [A["월수혜자"].get((m, 사람), 0) for m in A["달들"]]
    칩 = 증감칩(추이[-1] - 추이[-2], 추이[-2]) if len(추이) >= 2 else ""

    항목 = sorted(((c, v) for (p, c), v in A["수혜자카테고리"].items() if p == 사람),
                key=lambda kv: -kv[1])
    최대 = 항목[0][1] if 항목 else 1
    단계 = 농담(len(항목))
    행 = []
    for i, (c, v) in enumerate(항목):
        행.append(f"""<div class="row" data-kind="benecat"
     data-key="{esc(사람)}" data-key2="{esc(c)}">
  <div class="ico" style="background:{단계[i]}26">{아이콘(c)}</div>
  <div class="rmain">
    <div class="rtitle"><span class="nm">{esc(c)}</span></div>
    <div class="rmeta">월 {짧은돈(v//개월)}</div>
    <div class="track"><i style="width:{v/최대*100:.1f}%;background:{단계[i]}"></i></div>
  </div>
  <div class="rside"><div class="rval tnum">{돈(v)}</div>
    <div class="rsub">{v/금*100:.1f}%</div></div>
  <div class="chev"></div>
</div>""")

    return f"""<div class="pstat">
  <div><div class="k">{esc(사람)} 몫</div><div class="v tnum">{돈(금)}</div></div>
  <div><div class="k">월평균</div><div class="v tnum">{돈(금//개월)}</div></div>
  <div><div class="k">가구 안에서</div><div class="v tnum">{금/A["총지출"]*100:.1f}%</div></div>
  <div><div class="k">지난달 대비</div><div class="v">{칩 or "-"}</div></div>
</div>
<div class="card pad" data-group>{접기(행, 6, "개")}
  <div class="detail-host" hidden></div>
</div>"""


def 요약_이번달(A, 이번):
    """요약 탭에 올리는 이번 달 카테고리 Top. 눌러서 가맹점·거래까지 내려갈 수 있다."""
    if not 이번:
        return ""
    항목 = sorted(((c, v) for (m, c), v in A["월카테고리"].items()
                 if m == 이번 and c not in ("수입", "이체")), key=lambda kv: -kv[1])
    if not 항목:
        return ""
    총, 최대 = sum(v for _, v in 항목), 항목[0][1]
    행 = []
    for c, v in 항목:
        행.append(f"""<div class="row" data-kind="monthcategory"
     data-key="{esc(이번)}" data-key2="{esc(c)}">
  {그림칸(c)}
  <div class="rmain">
    <div class="rtitle"><span class="nm">{esc(c)}</span></div>
    <div class="track"><i style="width:{v/최대*100:.1f}%;background:var(--brand)"></i></div>
  </div>
  <div class="rside"><div class="rval tnum">{돈(v)}</div>
    <div class="rsub">{v/총*100:.1f}%</div></div>
  <div class="chev"></div>
</div>""")
    return f"""<div class="card pad" data-group>{접기(행, 5, "개")}
  <div class="detail-host" hidden></div>
</div>"""


def 목록_결제자(A):
    """누구 카드에서 나갔나. 위와 숫자가 다른 것이 정상이다."""
    총 = A["총지출"]
    행 = []
    for 사람 in A["사람들"]:
        금 = A["사람별"][사람]
        행.append(f"""<div class="row" data-kind="member" data-key="{esc(사람)}">
  <div class="rmain">
    <div class="rtitle" style="font-size:14px"><span class="nm">{esc(사람)}</span></div>
    <div class="track"><i style="width:{금/총*100:.1f}%;background:#B4BECB"></i></div>
  </div>
  <div class="rside"><div class="rval tnum" style="font-size:14.5px">{돈(금)}</div>
    <div class="rsub">{금/총*100:.1f}%</div></div>
  <div class="chev"></div>
</div>""")
    return f"""<div class="card pad" data-group>{''.join(행)}
  <div class="detail-host" hidden></div>
</div>"""


def 비중막대(항목들, 색맵):
    """비중을 한 줄 막대로 보여주고 아래에 범례를 단다."""
    총 = sum(v for _, v in 항목들) or 1
    칸 = "".join(f'<span style="width:{v/총*100:.2f}%;background:{색맵.get(k, 회색)}" '
                 f'title="{esc(k)} {돈(v)}"></span>' for k, v in 항목들)
    범례 = "".join(
        f'<span class="it"><span class="swatch" style="border-radius:50%;'
        f'background:{색맵.get(k, 회색)}"></span><b>{esc(k.split("_")[0])}</b> '
        f'{v/총*100:.1f}%</span>' for k, v in 항목들)
    return f'<div class="split">{칸}</div><div class="legend">{범례}</div>'


def 도넛(항목들, 색맵, 총, 가운데="총지출"):
    """항목들 = [(이름, 금액)]. 회전은 CSS transform 으로 처리한다."""
    r, 두께 = 62, 22
    C = 2 * math.pi * r
    누적, 조각 = 0.0, []
    for 이름, 금 in 항목들:
        비 = 금 / 총 if 총 else 0
        길이 = C * 비
        틈 = min(2.2, 길이 * 0.18) if 비 > 0.012 else 0      # 조각 사이 숨구멍
        조각.append(
            f'<circle cx="80" cy="80" r="{r}" fill="none" stroke="{색맵.get(이름, 회색)}" '
            f'stroke-width="{두께}" stroke-linecap="butt" '
            f'stroke-dasharray="{max(0.4, 길이-틈):.2f} {C-길이+틈:.2f}" '
            f'stroke-dashoffset="{-누적:.2f}"><title>{esc(이름)} {돈(금)}</title></circle>')
        누적 += 길이
    return f"""<div class="donut">
  <svg viewBox="0 0 160 160" role="img" aria-label="카테고리 비중">
    <circle cx="80" cy="80" r="{r}" fill="none" stroke="#EDF1F5" stroke-width="{두께}"/>
    {''.join(조각)}
  </svg>
  <div class="mid"><div class="t">{가운데}</div><div class="n tnum">{짧은돈(총)}</div></div>
</div>"""


def 구역_카테고리(A):
    항목 = sorted(A["카테고리별"].items(), key=lambda kv: -kv[1])
    총 = A["총지출"]
    단계 = 농담(len(항목))
    색맵 = {이름: 단계[i] for i, (이름, _) in enumerate(항목)}

    행 = []
    for 이름, 금 in 항목:
        색 = 색맵[이름]
        행.append(f"""<div class="row" data-kind="category" data-key="{esc(이름)}">
  <div class="ico" style="background:{색}26">{아이콘(이름)}</div>
  <div class="rmain">
    <div class="rtitle">{esc(이름)}</div>
    <div class="track"><i style="width:{금/총*100:.1f}%;background:{색}"></i></div>
  </div>
  <div class="rside"><div class="rval tnum">{돈(금)}</div>
    <div class="rsub">{금/총*100:.1f}%</div></div>
  <div class="chev"></div>
</div>""")

    return f"""<div class="card" data-group>
  <div class="donutbox">
    {도넛(항목[:6], 색맵, 총)}
    <div class="pad" style="padding:8px 6px">{''.join(행[:6])}</div>
  </div>
  <div class="pad" style="padding:0 6px 0;box-shadow:inset 0 1px 0 var(--line)">{접기(행[6:], 0, "개")}</div>
  <div class="detail-host" hidden></div>
</div>"""


def 차트_월별(A, 색맵, 이번):
    """월별 가구 지출을 구성원별로 쌓은 막대.

    SVG 대신 CSS 막대로 그린다. SVG 는 viewBox 가 화면 폭에 맞춰 줄어들면서
    글자까지 같이 작아져 휴대폰에서 읽기 어려워진다.
    """
    달들, 사람들 = A["달들"], A["수혜자들"]
    if not 달들:
        return ""
    최대 = max(A["월별"].values()) or 1
    눈금 = 최대 * 1.04

    칸들 = []
    for 월 in 달들:
        합 = A["월별"][월]
        조각 = []
        for 사람 in 사람들:                      # column-reverse 라 첫 사람이 아래에 쌓인다
            v = A["월수혜자"].get((월, 사람), 0)
            if v <= 0:
                continue
            조각.append(f'<i data-person="{esc(사람)}" '
                       f'style="height:{v/합*100:.2f}%;background:{색맵[사람]}" '
                       f'title="{esc(월)} · {esc(사람)} 몫 {돈(v)} — 눌러서 보기"></i>')
        지금 = " now" if 월 == 이번 else ""
        색 = "var(--ink)" if 월 == 이번 else "var(--ink3)"
        칸들.append(f"""<div class="bcol{지금}" data-kind="month" data-key="{esc(월)}">
  <div class="area">
    <div class="sum" style="color:{색}">{막대금액(합)}</div>
    <div class="stk" style="height:{합/눈금*100:.2f}%">{''.join(조각)}</div>
  </div>
  <div class="mon"><span class="yy">{esc(월[:4])}.</span>{int(월[5:])}월</div>
</div>""")

    범례 = "".join(
        f'<span class="it"><span class="swatch" style="background:{색맵[p]}"></span>'
        f'<b>{esc(p)}</b></span>' for p in 사람들)

    return (f'<div class="card" data-group><div class="plot">{눈금선(눈금, 최대)}'
            f'<div class="bars">{"".join(칸들)}</div></div>'
            f'<div class="legend">{범례}</div><div class="detail-host" hidden></div></div>'
            f'<div class="check">세로 눈금은 왼쪽에 있습니다. 막대를 누르면 그달 내역이 열려요. '
            f'막대 안의 <b>색 구간</b>을 누르면 그 사람 몫만 볼 수 있습니다.</div>')


def 목록_고정비(고정비들, 관측개월, 중복구독):
    if not 고정비들:
        return (f'<div class="note"><div class="bar"></div><p>3개월 이상 자료가 쌓이면 '
                f'고정비를 찾아드립니다. 지금은 {관측개월}개월치입니다.</p></div>')

    월합 = sum(f["월금액"] for f in 고정비들)
    연합 = sum(f["연환산"] for f in 고정비들)

    경고 = ""
    if 중복구독:
        항목 = " / ".join(
            f'<b>{esc(이름)}</b> — {", ".join(esc(f["사람"]) for f in fs)} '
            f'(합쳐서 월 {돈(sum(f["월금액"] for f in fs))})'
            for 이름, fs in 중복구독.items())
        경고 = (f'<div class="note warn"><div class="bar"></div>'
                f'<p><strong>같은 서비스가 두 사람 이상에게서 각각 빠져나가고 있어요.</strong><br>{항목}</p></div>')

    행 = []
    for f in 고정비들:
        배지 = "" if f["확신"] == "높음" else '<span class="tag">확인 필요</span>'
        행.append(f"""<div class="row" data-kind="fixed" data-key="{esc(f["가맹점"])}" data-key2="{esc(f["사람"])}">
  {그림칸(f["카테고리"])}
  <div class="rmain">
    <div class="rtitle"><span class="nm">{esc(f["가맹점"])}</span>{배지}</div>
    <div class="rmeta">{esc(f["사람"])} · {esc(f["근거"])} · 마지막 {esc(f["마지막"])}</div>
  </div>
  <div class="rside"><div class="rval tnum">{돈(f["월금액"])}</div>
    <div class="rsub">1년 {짧은돈(f["연환산"])}</div></div>
  <div class="chev"></div>
</div>""")

    합계행 = f"""<div class="row static" style="background:#F8FAFB">
  <div class="swatch" style="background:var(--brand)"></div>
  <div class="rmain"><div class="rtitle">고정비 {len(고정비들)}건 합계</div></div>
  <div class="rside"><div class="rval tnum" style="color:var(--brand-deep)">{돈(월합)}</div>
    <div class="rsub">1년 {짧은돈(연합)}</div></div>
</div>"""

    return f"""{경고}<div class="card pad" data-group>{접기(행, 5, "건")}{합계행}
  <div class="detail-host" hidden></div>
</div>
<div class="check">프로그램은 매달 반복되는 결제를 찾아줄 뿐, 그게 필요한 지출인지는 알 수 없습니다.
판단 근거와 마지막 결제일을 보고 직접 정해 주세요.</div>"""


def 목록_전월대비(이번, 지난, 행들):
    if not 행들:
        return ('<div class="note"><div class="bar"></div>'
                '<p>비교할 달이 아직 두 달치가 안 됩니다.</p></div>')
    행 = []
    for r in 행들:
        d = r["차이"]
        if d > 0:
            칩, 색 = f'<span class="pill up">▲ {돈(abs(d))}</span>', "var(--up)"
        elif d < 0:
            칩, 색 = f'<span class="pill down">▼ {돈(abs(d))}</span>', "var(--brand)"
        else:
            칩, 색 = '<span class="pill flat">그대로</span>', "var(--ink3)"
        비율 = ("이번 달 없음" if r["이번달"] == 0 else
               ("지난달엔 없던 항목" if r["비율"] is None else f"{r['비율']:+.1f}%"))
        행.append(f"""<div class="row" data-kind="delta" data-key="{esc(r["카테고리"])}">
  {그림칸(r["카테고리"])}
  <div class="rmain">
    <div class="rtitle"><span class="nm">{esc(r["카테고리"])}</span>{칩}</div>
    <div class="rmeta">{esc(지난)} {돈(r["지난달"])} → {esc(이번)} {돈(r["이번달"])}</div>
  </div>
  <div class="rside"><div class="rval tnum" style="color:{색};font-size:14px">{esc(비율)}</div></div>
  <div class="chev"></div>
</div>""")
    return f"""<div class="card pad" data-group>{접기(행, 5, "개")}
  <div class="detail-host" hidden></div>
</div>
<div class="check">늘어난 항목은 빨강 ▲, 줄어든 항목은 초록 ▼ 입니다. 색과 기호를 함께 씁니다.</div>"""


def 종목집계(행들):
    """보유종목.csv → (사람, 기관, 세부항목) 별 종목 목록.

    오늘 시세를 인터넷에서 가져오지 않는다. 이 도구는 네트워크 호출을 하지 않는다.
    증권사에서 내려받은 잔고에 적힌 현재가를 그대로 쓴다.
    """
    묶음 = defaultdict(list)
    for r in 행들:
        try:
            수량 = float(str(r.get("수량", "")).replace(",", "") or 0)
            매수 = float(str(r.get("매수단가", "")).replace(",", "") or 0)
            현재 = float(str(r.get("현재가", "")).replace(",", "") or 0)
        except ValueError:
            continue
        if 수량 <= 0:
            continue
        원금, 평가 = round(수량 * 매수), round(수량 * 현재)
        묶음[((r.get("사람") or "").strip(), (r.get("기관") or "").strip(),
             (r.get("세부항목") or "").strip())].append({
            "종목명": (r.get("종목명") or "").strip(), "수량": 수량,
            "매수단가": 매수, "현재가": 현재, "원금": 원금, "평가": 평가,
            "손익": 평가 - 원금, "수익률": (평가 - 원금) / 원금 * 100 if 원금 else 0,
            "매수일자": (r.get("매수일자") or "").strip(),
        })
    for v in 묶음.values():
        v.sort(key=lambda x: -x["평가"])
    return dict(묶음)


def 보유일수(매수일자: str) -> int:
    try:
        return max(1, (dt.date.today() - dt.date.fromisoformat(매수일자[:10])).days)
    except (ValueError, TypeError):
        return 0


def 연환산(원금, 평가, 일수):
    """보유 기간을 고려한 연 수익률. 기간이 다른 종목을 나란히 놓고 보기 위한 것."""
    if 원금 <= 0 or 평가 <= 0 or 일수 <= 0:
        return None
    try:
        return ((평가 / 원금) ** (365 / 일수) - 1) * 100
    except (OverflowError, ValueError):
        return None


def 기간말(일수: int) -> str:
    if 일수 <= 0:
        return ""
    년, 남 = divmod(일수, 365)
    달 = 남 // 30
    if 년 and 달:
        return f"{년}년 {달}개월"
    if 년:
        return f"{년}년"
    return f"{달}개월" if 달 else f"{일수}일"


def 종목점검(종목들, 평가합, 손익합):
    """사실만 짚고 확인할 질문을 붙인다. 사거나 팔라고 하지 않는다."""
    질문 = []
    if not 종목들 or 평가합 <= 0:
        return 질문

    으뜸 = 종목들[0]
    비중 = 으뜸["평가"] / 평가합 * 100
    if 비중 >= 30:
        질문.append((f'{esc(으뜸["종목명"])} 한 종목이 이 계좌의 {비중:.0f}%입니다',
                    "한 종목을 어디까지 담을지 미리 정해 두셨는지, 지금이 그 선 안인지 확인해 보세요."))

    오래손실 = [s for s in 종목들 if s["손익"] < 0 and 보유일수(s["매수일자"]) >= 365]
    if 오래손실:
        이름 = ", ".join(esc(s["종목명"]) for s in 오래손실[:3])
        질문.append((f'{이름} — 1년 넘게 손실 구간입니다',
                    "살 때 어떤 근거로 샀는지, 그 근거가 지금도 유효한지 스스로 점검해 보세요."))

    if 손익합 != 0:
        기여 = sorted(종목들, key=lambda s: -abs(s["손익"]))[0]
        몫 = 기여["손익"] / 손익합 * 100 if 손익합 else 0
        if abs(몫) >= 50:
            질문.append((f'전체 손익의 {abs(몫):.0f}%가 {esc(기여["종목명"])} 하나에서 나왔습니다',
                        "계좌 전체 수익률이 한 종목에 좌우되고 있지는 않은지 봐 두세요."))

    return 질문


def 큰돈(n):
    """302000000000000 → 302.0조"""
    n = abs(n or 0)
    if n >= 1_0000_0000_0000:
        return f"{n/1_0000_0000_0000:.1f}조"
    if n >= 1_0000_0000:
        return f"{n/1_0000_0000:,.0f}억"
    if n >= 1_0000:
        return f"{n//1_0000:,}만"
    return f"{n:,}"


def 재무칸(종목명, 재무):
    """공시된 재무와 잔고의 현재가로 낸 값. 좋고 나쁨은 말하지 않는다."""
    v = (재무 or {}).get("종목", {}).get(종목명)
    if not v:
        return ""
    출처 = v.get("출처", "")
    칸 = []
    for 그림, 이름, 값, 꼴 in [
        ("💵", "매출", v.get("매출액"), "큰돈"),
        ("📈", "영업이익", v.get("영업이익"), "큰돈"),
        ("🧾", "영업이익률", v.get("영업이익률"), "퍼센트"),
        ("💰", "당기순이익", v.get("당기순이익"), "큰돈"),
        ("🏦", "자본총계", v.get("자본총계"), "큰돈"),
        ("📊", "ROE", v.get("ROE"), "퍼센트"),
        ("🪙", "EPS", v.get("EPS"), "원"),
        ("📕", "BPS", v.get("BPS"), "원"),
        ("⚖️", "PER", v.get("PER"), "배"),
        ("📐", "PBR", v.get("PBR"), "배"),
    ]:
        if 값 is None:
            continue
        글 = (큰돈(값) + "원" if 꼴 == "큰돈" else
             f"{값}%" if 꼴 == "퍼센트" else
             f"{값:,}원" if 꼴 == "원" else f"{값}배")
        칸.append(f'<div class="fin"><div class="fk">{그림} {esc(이름)}</div>'
                  f'<div class="fv">{esc(글)}</div></div>')
    if not 칸:
        return ""
    꼬리 = (f'{v.get("해", "")}년 사업보고서'
           + (" · 전자공시(DART)" if 출처 == "DART" else " · 가상 값(예시)"))
    return (f'<div class="finbox"><div class="nlabel">📑 회사 살림</div>'
            f'<div class="fins">{"".join(칸)}</div>'
            f'<div class="hnote">{esc(꼬리)} · PER·PBR 은 잔고에 적힌 현재가로 낸 값입니다. '
            f'좋고 나쁨을 판단하거나 사고팔기를 권하지 않습니다.</div></div>')


def 뉴스칸(종목명, 뉴스):
    """키워드 단추. 누르면 제목·언론사·날짜가 열리고 원문으로 갈 수 있다.
    기사 본문은 담지 않는다."""
    기사들 = (뉴스 or {}).get("종목", {}).get(종목명) or []
    if not 기사들:
        return ""
    단추 = []
    for i, a in enumerate(기사들[:5]):
        단추.append(
            f'<button type="button" class="nchip" data-n="{esc(종목명)}|{i}">'
            f'{esc(a.get("키워드") or "소식")}'
            f'<span class="nsrc">{esc(a.get("출처", ""))}'
            f'{" · " + esc(a.get("날짜", "")) if a.get("날짜") else ""}</span></button>')
    속 = []
    for i, a in enumerate(기사들[:5]):
        속.append(
            f'<div class="nbox" data-n="{esc(종목명)}|{i}" hidden>'
            f'<div class="ntitle">{esc(a.get("제목", ""))}</div>'
            f'<div class="nmeta">{esc(a.get("출처", ""))}'
            f'{" · " + esc(a.get("날짜", "")) if a.get("날짜") else ""}</div>'
            f'<a class="nlink" href="{esc(a.get("링크", "#"))}" target="_blank" '
            f'rel="noopener noreferrer">원문 보기 →</a></div>')
    return (f'<div class="news"><div class="nlabel">📰 오늘의 소식</div>'
            f'<div class="nchips">{"".join(단추)}</div>{"".join(속)}</div>')


def 종목판(종목들, 적힌금액, 기관="", 사람="", 뉴스=None, 재무=None):
    """한 항목 안의 종목별 상세."""
    평가합 = sum(s["평가"] for s in 종목들)
    원금합 = sum(s["원금"] for s in 종목들)
    손익 = 평가합 - 원금합
    률 = 손익 / 원금합 * 100 if 원금합 else 0
    색 = "var(--up)" if 손익 > 0 else ("var(--loss)" if 손익 < 0 else "var(--ink3)")
    기호 = "▲" if 손익 > 0 else ("▼" if 손익 < 0 else "-")

    줄 = []
    for s in 종목들:
        c = "var(--up)" if s["손익"] > 0 else ("var(--loss)" if s["손익"] < 0 else "var(--ink3)")
        k = "▲" if s["손익"] > 0 else ("▼" if s["손익"] < 0 else "-")
        수량표기 = f'{s["수량"]:,.0f}' if s["수량"] == int(s["수량"]) else f'{s["수량"]:,.2f}'
        일수 = 보유일수(s["매수일자"])
        연 = 연환산(s["원금"], s["평가"], 일수)
        비중 = s["평가"] / 평가합 * 100 if 평가합 else 0
        꼬리 = []
        if 일수:
            꼬리.append(f'{기간말(일수)} 보유')
        if 연 is not None:
            꼬리.append(f'연 {연:+.1f}%')
        꼬리.append(f'계좌의 {비중:.0f}%')
        줄.append(f"""<div class="hrow">
  <div class="hmain">
    <div class="hname">{esc(s["종목명"])}</div>
    <div class="hsub">{수량표기}주 · 매수 {s["매수단가"]:,.0f}원 → 현재 {s["현재가"]:,.0f}원
      · {esc(s["매수일자"])}</div>
    <div class="hsub">{" · ".join(꼬리)}</div>
  </div>
  <div class="hside">
    <div class="hval tnum">{s["평가"]:,.0f}원</div>
    <div class="hpl tnum" style="color:{c}">{k} {abs(s["손익"]):,.0f}원 ({s["수익률"]:+.1f}%)</div>
  </div>
</div>
{재무칸(s["종목명"], 재무)}{뉴스칸(s["종목명"], 뉴스)}""")

    어긋남 = ""
    if 적힌금액 and abs(적힌금액 - 평가합) > max(1000, 적힌금액 * 0.001):
        어긋남 = (f'<div class="hnote">자산에 적어 둔 금액 {돈(적힌금액)}과 종목 합계 '
                 f'{돈(평가합)}이 {돈(abs(적힌금액-평가합))} 다릅니다. 기준일이 다를 수 있어요.</div>')

    점검 = 종목점검(종목들, 평가합, 손익)
    점검칸 = ""
    if 점검:
        항목 = "".join(f'<div class="hq"><b>{제목}</b><span>{설명}</span></div>'
                     for 제목, 설명 in 점검)
        점검칸 = f'<div class="hqbox"><div class="hqt">확인해볼 것</div>{항목}</div>'

    머리 = (f'<div class="hhead">{그림칸("금융자산", 자산아이콘, "🏦")}'
           f'<div><div class="hh1">{esc(기관) or "증권 계좌"}</div>'
           f'<div class="hh2">{esc(사람.split("_")[0]) + " · " if 사람 else ""}'
           f'{len(종목들)}종목</div></div></div>')

    return f"""<div class="hbox">
  {머리}
  <div class="hsum">
    <div><div class="k">평가금액</div><div class="v tnum">{평가합:,.0f}원</div></div>
    <div><div class="k">매수원금</div><div class="v tnum">{원금합:,.0f}원</div></div>
    <div><div class="k">평가손익</div>
      <div class="v tnum" style="color:{색}">{기호} {abs(손익):,.0f}원 ({률:+.1f}%)</div></div>
  </div>
  {"".join(줄)}
  {어긋남}
  {점검칸}
  <div class="hnote">현재가는 <b>증권사에서 내려받은 잔고 파일에 적힌 값</b>입니다.
    이 도구는 시세를 조회하지 않고, 사거나 팔라고 권하지도 않습니다.
    판단에 쓰실 사실만 모아 둔 것입니다.</div>
</div>"""


def 자산상세판(x, 분류금액, 총자산):
    """종목 목록이 없는 자산도 눌러서 볼 수 있게, 중요한 것만 단추로 보여준다."""
    평가, 원금 = x["금액"], x["원금"]
    칩 = [("💰", "평가금액", 돈(평가), "")]

    if 원금:
        손익 = 평가 - 원금
        률 = 손익 / 원금 * 100
        색 = "up" if 손익 > 0 else ("loss" if 손익 < 0 else "")
        기호 = "▲" if 손익 > 0 else ("▼" if 손익 < 0 else "-")
        칩.append(("📥", "원금", 돈(원금), ""))
        칩.append(("📊", "평가손익", f"{기호} {돈(abs(손익))} ({률:+.1f}%)", 색))

    if x["이율"]:
        칩.append(("📈", "금리", f"{x['이율']:g}%", ""))
        if 평가:
            칩.append(("🧮", "연 이자(단순)", 돈(평가 * x["이율"] / 100), ""))

    if x["만기일"]:
        try:
            남 = (dt.date.fromisoformat(x["만기일"][:10]) - dt.date.today()).days
            칩.append(("📅", "만기", f"{x['만기일']} (D{남:+d})",
                      "up" if 0 <= 남 <= 90 else ""))
        except (ValueError, TypeError):
            칩.append(("📅", "만기", x["만기일"], ""))

    if x["기관"]:
        칩.append(("🏦", "어디에", x["기관"], ""))
    칩.append(("👤", "명의", x["사람"].split("_")[0] if x["사람"] else "-", ""))
    if 분류금액:
        칩.append(("🥧", f"{x['분류']} 안에서", f"{평가/분류금액*100:.1f}%", ""))
    if 총자산:
        칩.append(("🏠", "총자산에서", f"{평가/총자산*100:.1f}%", ""))
    if x["기준일"]:
        칩.append(("🕒", "기준일", x["기준일"], ""))

    비고 = x["비고"]
    표시 = []
    for 열쇠, 그림, 말 in [("세액공제", "🧾", "세액공제 상품"),
                       ("예금자보호", "🛟", "예금자보호 대상"),
                       ("실거주", "🏡", "실거주"),
                       ("월세", "🔑", "임대 수입 있음"),
                       ("중도인출", "🔒", "중도인출 제한"),
                       ("55세", "⏳", "55세 이후 인출"),
                       ("환율", "💱", "환율 영향"),
                       ("수시", "⚡", "수시 입출금")]:
        if 열쇠 in 비고:
            표시.append(f'<span class="chip">{그림} {말}</span>')

    칸 = "".join(
        f'<div class="fact{" " + c if c else ""}"><div class="fk">{g} {esc(k)}</div>'
        f'<div class="fv">{esc(v)}</div></div>' for g, k, v, c in 칩)
    꼬리 = f'<div class="chips" style="margin-top:10px">{"".join(표시)}</div>' if 표시 else ""
    남은비고 = esc(비고) if 비고 and not 표시 else ""

    return (f'<div class="hbox">'
            f'<div class="hhead">{그림칸(x["분류"], 자산아이콘, "🏦")}'
            f'<div><div class="hh1">{esc(x["세부항목"])}</div>'
            f'<div class="hh2">{esc(x["분류"])}'
            f'{" · " + esc(x["기관"]) if x["기관"] else ""}</div></div></div>'
            f'<div class="facts">{칸}</div>{꼬리}'
            f'{f"<div class=hnote>{남은비고}</div>" if 남은비고 else ""}</div>')


def 구역_자산(자산, 종목=None, 뉴스=None, 재무=None):
    """유형별로 묶고 소계를 보여준다. 줄을 누르면 그 안의 항목이 펼쳐진다.
    (자산 관리 앱들이 공통으로 쓰는 방식 — 현금·투자·부동산·대출로 묶고 그룹마다 소계)"""
    if not 자산["항목"]:
        return ""
    분류 = sorted(((k, v) for k, v in 자산["분류별"].items() if k != "부채"), key=lambda kv: -kv[1])
    단계 = 농담(len(분류), "파랑")
    색맵 = {k: 단계[i] for i, (k, _) in enumerate(분류)}
    총 = 자산["총자산"]

    묶음, 속도넛들 = [], []
    for 묶음번호, (이름, 금) in enumerate(분류):
        속한 = sorted((x for x in 자산["항목"] if x["분류"] == 이름), key=lambda x: -x["금액"])
        최대 = 속한[0]["금액"] if 속한 else 1
        속단계 = 농담(len(속한), "파랑")
        속색 = {x["세부항목"] + x["기관"]: 속단계[i] for i, x in enumerate(속한)}

        조각 = []
        for i, x in enumerate(속한):
            종목들 = (종목 or {}).get((x["사람"], x["기관"], x["세부항목"]))
            안내 = f'<span class="tag">종목 {len(종목들)}개</span>' if 종목들 else ""
            속 = (종목판(종목들, x["금액"], x["기관"], x["사람"], 뉴스, 재무) if 종목들
                 else 자산상세판(x, 금, 총))
            조각.append(
                f'<div class="row aitem" data-acc>'
                f'<span class="dot2" style="background:{속단계[i]}"></span>'
                f'<div class="rmain">'
                f'<div class="rtitle"><span class="nm">{esc(x["세부항목"])}</span>{안내}</div>'
                f'<div class="rmeta">{esc(x["사람"].split("_")[0])}'
                f'{" · " + esc(x["기관"]) if x["기관"] else ""}</div>'
                f'<div class="track"><i style="width:{x["금액"]/최대*100:.1f}%;'
                f'background:{속단계[i]}"></i></div></div>'
                f'<div class="rside"><div class="rval tnum">{돈(x["금액"])}</div>'
                f'<div class="rsub">{x["금액"]/금*100:.0f}%</div></div>'
                f'<div class="chev"></div></div>'
                f'<div class="acc-body" hidden>{속}</div>')

        속도넛들.append(
            f'<div class="subdonut" data-for="{묶음번호}" hidden>'
            f'{도넛([(x["세부항목"] + x["기관"], x["금액"]) for x in 속한], 속색, 금, esc(이름))}'
            f'</div>')
        항목줄 = "".join(조각)
        묶음.append(f"""<div class="row" data-acc data-donut="{묶음번호}">
  <div class="ico" style="background:{색맵[이름]}26">{아이콘(이름, 자산아이콘, "🏦")}</div>
  <div class="rmain">
    <div class="rtitle"><span class="nm">{esc(이름)}</span>
      <span class="tag">{len(속한)}건</span></div>
    <div class="track"><i style="width:{금/총*100:.1f}%;background:{색맵[이름]}"></i></div>
  </div>
  <div class="rside"><div class="rval tnum">{짧은돈(금).replace("약 ", "")}</div>
    <div class="rsub">{금/총*100:.1f}%</div></div>
  <div class="chev"></div>
</div>
<div class="acc-body" hidden>{항목줄}</div>""")

    부채줄 = ""
    if 자산["부채"]:
        부채줄 = (f'<div class="check">부채 {돈(자산["부채"])}를 빼면 순자산은 '
                 f'<b>{돈(자산["순자산"])}</b>입니다.</div>')

    return f"""<div class="card">
  <div class="donutbox">
    <div class="donutcol">{도넛(분류, 색맵, 총, "총자산")}{''.join(속도넛들)}</div>
    <div class="pad" style="padding:8px 6px">{''.join(묶음)}</div>
  </div>
</div>
<div class="check">유형을 누르면 그 안에 무엇이 들어 있는지 펼쳐집니다.</div>{부채줄}"""


def 구역_보험(보험, 가족들):
    if not 보험["증권"]:
        return ('<div class="note"><div class="bar"></div><p>보험 증권을 옮겨 적은 파일이 없습니다. '
                '<b>templates/보험_입력양식.csv</b> 를 채워 <b>보험.csv</b> 로 저장하면 여기에 정리해 드려요.</p></div>')

    순서 = [이름 for 이름 in 가족들] or sorted({s["사람"] for s in 보험["증권"]})
    줄 = []
    for 항목 in sorted(보험["보장"], key=lambda k: (k.split("_")[0], k)):
        사람별 = 보험["보장"][항목]
        칩 = []
        for 이름 in 순서:
            건들 = 사람별.get(이름)
            if not 건들:
                칩.append(f'<span class="chip off">{esc(이름.split("_")[0])} 없음</span>')
                continue
            금들 = [b["금액"] for b in 건들]
            if any(g == "무한" for g in 금들):
                표기 = "무한"
            else:
                합 = sum(g for g in 금들 if isinstance(g, int))
                표기 = 짧은돈(합).replace("약 ", "") if 합 else "가입"
            겹 = f' ×{len(건들)}' if len(건들) > 1 else ""
            칩.append(f'<span class="chip">{esc(이름.split("_")[0])} <b>{표기}</b>{겹}</span>')
        중복표시 = ('<span class="tag warn">중복 보상 안 됨</span>'
                  if 항목 in 비례보상담보 and any(len(v) > 1 for v in 사람별.values()) else "")
        줄.append(f"""<div class="row static">
  {그림칸(항목, 보장아이콘, "🛡️")}
  <div class="rmain"><div class="rtitle">{esc(항목)}{중복표시}</div>
    <div class="chips">{''.join(칩)}</div></div>
</div>""")

    증권줄 = []
    for s in sorted(보험["증권"], key=lambda x: (-x["월보험료"], x["사람"])):
        보험료 = 돈(s["월보험료"]) if s["월보험료"] else "출금 기록 없음"
        세대 = ""
        if any(항.startswith("실손") for 항, _ in s["보장"]):
            g = 실손세대(s["계약일"])
            세대 = f'<span class="tag">{g}</span>' if g else ""
        증권줄.append(f"""<div class="row static">
  <div class="rmain"><div class="rtitle">{esc(s["보험사"])} {esc(s["상품명"])}{세대}</div>
    <div class="rmeta">{esc(s["사람"])} · {esc(s["계약일"])} ~ {esc(s["만기일"])}
      · 보장 {len(s["보장"])}개{" · " + esc(s["비고"]) if s["비고"] else ""}</div></div>
  <div class="rside"><div class="rval tnum" style="font-size:14px">{보험료}</div></div>
</div>""")

    전체판 = (f'<div class="card pad">{접기(줄, 6, "개")}</div>'
             f'<h2 style="margin-top:26px;font-size:15px">가입한 증권 {len(보험["증권"])}건</h2>'
             f'<div class="card pad">{접기(증권줄, 5, "건")}</div>')

    # ── 사람별 화면 ──────────────────────────────────────────────────
    버튼 = ['<button class="sub-btn" type="button" data-sub="ins-all" '
           'aria-selected="true">전체 비교</button>']
    판들 = [f'<div class="subpanel" id="ins-all">{전체판}</div>']

    for i, 이름 in enumerate(순서):
        증권들 = [s for s in 보험["증권"] if s["사람"] == 이름]
        없음 = " none" if not 증권들 else ""
        버튼.append(f'<button class="sub-btn" type="button" data-sub="ins-{i}" '
                   f'aria-selected="false">{esc(이름.split("_")[0])}'
                   f'<span class="c{없음}">{len(증권들)}</span></button>')
        판들.append(f'<div class="subpanel" id="ins-{i}" hidden>{사람보험판(이름, 증권들, 보험, 순서)}</div>')

    return (f'<div data-subgroup><div class="subtabs">{"".join(버튼)}</div>'
            f'{"".join(판들)}</div>')


def 사람보험판(이름, 증권들, 보험, 순서):
    """한 사람의 보장과 증권만 모아 보여준다."""
    if not 증권들:
        가진사람 = sorted({p for 사람별 in 보험["보장"].values() for p in 사람별})
        return (f'<div class="note warn"><div class="bar"></div>'
                f'<p><strong>{esc(이름)} 님 앞으로 등록된 증권이 없습니다.</strong><br>'
                f'{", ".join(esc(p.split("_")[0]) for p in 가진사람)} 님은 보장을 가지고 있어요. '
                f'실제로 없는 것인지, 증권을 아직 못 옮겨 적은 것인지 확인해 보세요.</p></div>')

    보험료 = sum(s["월보험료"] for s in 증권들)

    # 이 사람이 가진 보장
    내보장 = []
    for 항목, 사람별 in 보험["보장"].items():
        건들 = 사람별.get(이름)
        if not 건들:
            continue
        금들 = [b["금액"] for b in 건들]
        무한 = any(g == "무한" for g in 금들)
        합 = sum(g for g in 금들 if isinstance(g, int))
        내보장.append((항목, 건들, 무한, 합))
    내보장.sort(key=lambda x: (not x[2], -x[3]))

    내것 = {항목: (건들, 무한, 합) for 항목, 건들, 무한, 합 in 내보장}
    가진사람 = {항목: set(사람별) for 항목, 사람별 in 보험["보장"].items()}

    def 칩(항목):
        if 항목 in 내것:
            건들, 무한, 합 = 내것[항목]
            금 = "무한" if 무한 else (짧은돈(합).replace("약 ", "") if 합 else "가입")
            겹 = ""
            if len(건들) > 1:
                겹 = ('<span class="x dup">×%d 중복 보상 안 됨</span>' % len(건들)
                      if 항목 in 비례보상담보 else '<span class="x">×%d</span>' % len(건들))
            회사 = ", ".join(b["보험사"] for b in 건들)
            return (f'<span class="chip{" dup" if 겹 and "dup" in 겹 else ""}" '
                    f'title="{esc(항목)} · {esc(회사)}">{아이콘(항목, 보장아이콘, "🛡️")} '
                    f'{esc(항목)} <b>{금}</b>{겹}</span>')
        남 = 가진사람.get(항목, set()) - {이름}
        이름들 = [p.split("_")[0] for p in sorted(남)]
        꼬리 = (f'<span class="x">{", ".join(esc(n) for n in 이름들)}'
               f'{은는(이름들[-1])} 있음</span>' if 이름들 else "")
        의무 = '<span class="x must">의무</span>' if 항목 in 의무담보 else ""
        return (f'<span class="chip off">{아이콘(항목, 보장아이콘, "🛡️")} '
                f'{esc(항목)}{의무}{꼬리}</span>')

    갈래 = []
    for 갈래이름, 항목들 in 표준보장:
        있음 = sum(1 for c in 항목들 if c in 내것)
        갈래.append(f"""<div class="covgrp">
  <div class="covhead">{esc(갈래이름)}<span class="cnt">{있음}/{len(항목들)}</span></div>
  <div class="chips">{"".join(칩(c) for c in 항목들)}</div>
</div>""")

    # 점검표에 없는 보장을 따로 가지고 있으면 그것도 보여준다
    그밖 = [c for c in 내것 if c not in 표준보장전체]
    if 그밖:
        갈래.append(f"""<div class="covgrp">
  <div class="covhead">그 밖의 보장<span class="cnt">{len(그밖)}</span></div>
  <div class="chips">{"".join(칩(c) for c in sorted(그밖))}</div>
</div>""")

    보장판 = (f'<div class="card" style="padding:6px 16px 14px">{"".join(갈래)}</div>'
             f'<div class="check">초록은 가입한 보장, 회색은 없는 보장입니다. '
             f'회색 옆에 가족 중 누가 가지고 있는지 적어 뒀어요. '
             f'이 목록은 <b>많이 드는 보장을 모아 둔 점검표</b>일 뿐, 다 들어야 한다는 뜻이 아닙니다.</div>')
    공백칸 = ""

    증권줄 = []
    for s in sorted(증권들, key=lambda x: -x["월보험료"]):
        료 = 돈(s["월보험료"]) if s["월보험료"] else "출금 기록 없음"
        세대 = ""
        if any(항.startswith("실손") for 항, _ in s["보장"]):
            g = 실손세대(s["계약일"])
            세대 = f'<span class="tag">{g}</span>' if g else ""
        증권줄.append(f"""<div class="row static">
  <div class="rmain"><div class="rtitle"><span class="nm">{esc(s["보험사"])} {esc(s["상품명"])}</span>{세대}</div>
    <div class="rmeta">{esc(s["계약일"])} ~ {esc(s["만기일"])} · 보장 {len(s["보장"])}개
      {" · " + esc(s["비고"]) if s["비고"] else ""}</div></div>
  <div class="rside"><div class="rval tnum" style="font-size:13.5px">{료}</div></div>
</div>""")

    return f"""<div class="pstat">
  <div><div class="k">월 보험료</div><div class="v tnum">{돈(보험료)}</div></div>
  <div><div class="k">1년이면</div><div class="v tnum">{짧은돈(보험료*12)}</div></div>
  <div><div class="k">증권</div><div class="v tnum">{len(증권들)}건</div></div>
  <div><div class="k">보장 항목</div><div class="v tnum">{len(내보장)}개</div></div>
</div>
{보장판}{공백칸}
<h2 style="margin-top:26px;font-size:15px">{esc(이름.split("_")[0])} 님 증권 {len(증권들)}건</h2>
<div class="card pad">{"".join(증권줄)}</div>"""


def 한줄요약(본문: str, 길이=52) -> str:
    """카드를 접었을 때 보여줄 한 줄. 본문의 첫 문장을 쓴다."""
    글 = re.sub(r"<br\s*/?>", " ", 본문)
    글 = re.sub(r"<[^>]+>", "", 글)
    글 = re.sub(r"\s+", " ", 글).strip()
    첫 = re.split(r"(?<=다\.)\s|(?<=요\.)\s|\.\s", 글)[0].strip()
    return 첫 if len(첫) <= 길이 else 첫[:길이 - 1].rstrip() + "…"


def 구역_AI(조언):
    """scripts/advise.py 가 받아온 분석. 파일이 없으면 이 구역은 통째로 빠진다."""
    if not 조언:
        return ""
    카드 = []
    for x in 조언.get("발견", []):
        카드.append(("🔎", x.get("제목", ""), x.get("설명", ""), ""))
    for x in 조언.get("살펴볼점", []):
        카드.append(("❓", x.get("제목", ""), x.get("설명", ""), x.get("규모", "")))

    줄 = []
    for 그림, 제목, 설명, 규모 in 카드:
        꼬리 = f'<span class="tag">{esc(규모)}</span>' if 규모 else ""
        줄.append(f"""<div class="flag">
  <div class="flag-head">
    <div class="ico plain">{그림}</div>
    <div class="fmain">
      <div class="ft">{esc(제목)}{꼬리}</div>
      <div class="fsum">{esc(한줄요약(설명))}</div>
    </div>
    <div class="chev"></div>
  </div>
  <div class="flag-body" hidden><div class="fb">{esc(설명)}</div></div>
</div>""")

    모델 = esc(조언.get("모델", "Gemini"))
    return f"""<div class="note"><div class="bar"></div>
  <p><strong>{esc(조언.get("한줄", ""))}</strong></p>
</div>
<div class="flags">{"".join(줄)}</div>
<div class="check">이 부분은 <b>{모델}</b> 이 집계한 숫자를 읽고 쓴 글입니다.
사실과 다를 수 있으니 위의 표와 대조해 보세요.
숫자를 보내 분석을 받는 기능이라, 켜 두면 <b>집계한 합계가 구글로 전송</b>됩니다.
거래 하나하나나 계좌·증권번호는 보내지 않습니다.</div>"""


def 구역_점검(신호들):
    """접었을 때는 제목과 한 줄만, 누르면 근거와 상담 질문까지 펼친다."""
    if not 신호들:
        return ""
    카드 = []
    for s in 신호들:
        배지 = ('<span class="tag warn">확인 필요</span>' if s["급"] == "warn"
                else '<span class="tag">알아두기</span>')
        출처 = f'<div class="src">근거: {esc(s["출처"])}</div>' if s["출처"] else ""
        그림 = "⚠️" if s["급"] == "warn" else "💡"
        카드.append(f"""<div class="flag">
  <div class="flag-head">
    <div class="ico{'' if s['급'] == 'warn' else ' plain'}">{그림}</div>
    <div class="fmain">
      <div class="ft">{s["제목"]}{배지}</div>
      <div class="fsum">{esc(한줄요약(s["본문"]))}</div>
    </div>
    <div class="chev"></div>
  </div>
  <div class="flag-body" hidden>
    <div class="fb">{s["본문"]}</div>
    <div class="fq"><span class="q">상담할 때 이렇게 물어보세요</span>{esc(s["질문"])}</div>
    {출처}
  </div>
</div>""")
    return f'<div class="flags">{접기(카드, 4, "가지")}</div>'


# ============================================================================
# 상세 보기용 데이터 — 파일 하나로 열리도록 HTML 안에 직접 넣는다
# (file:// 로 열면 브라우저가 바깥 파일을 못 읽기 때문)
# ============================================================================
def 상세데이터(거래들, 달들):
    담을달 = set(달들[-상세개월한도:])
    데이터 = [{
        "d": t["날짜"], "p": t["사람"], "b": t.get("수혜자") or t["사람"],
        "m": t["가맹점"], "a": t["금액"],
        "c": t["카테고리"], "k": t["구분"], "f": t["원본파일"],
        "x": 1 if t["중복의심"] == "Y" else 0,
    } for t in 거래들 if t["날짜"][:7] in 담을달]
    # </script> 로 HTML이 일찍 끊기지 않게 < 를 이스케이프한다
    return json.dumps(데이터, ensure_ascii=False).replace("<", "\\u003c")


JS = """
(function () {
  var TX = JSON.parse(document.getElementById('tx-data').textContent);
  var MONTHS = JSON.parse(document.getElementById('month-data').textContent);
  var WHOCOLOR = JSON.parse(document.getElementById('color-data').textContent);

  // 파이썬의 색 계단과 같은 규칙. 큰 것이 진하다.
  function hsl(h, s, l) { return 'hsl(' + h.toFixed(1) + ',' + s.toFixed(1) + '%,' + l.toFixed(1) + '%)'; }
  function 계단(n, i) {
    if (n <= 1) return hsl(188, 64, 45);
    var t = i / (n - 1);
    var l = 34 + (57 - 34) * t + (i % 2 ? 4.5 : -4.5);
    return hsl(188 + (68 - 188) * t, 64 + (58 - 64) * t, Math.min(72, Math.max(26, l)));
  }

  function won(n) { return Math.abs(n).toLocaleString('ko-KR') + '원'; }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

  // ── 어디를 눌렀느냐에 따라 어떤 순서로 잘게 쪼개 보여줄지 ──────────────
  //    c = 카테고리, m = 가맹점, b = 누구 몫, p = 누가 결제, mon = 월
  var CHAIN = {
    month:       ['b', 'c', 'm'],
    monthperson: ['c', 'm'],
    beneficiary: ['c', 'm'],
    member:      ['c', 'm'],
    category:    ['b', 'm'],
    delta:       ['mon', 'm'],
    monthcategory: ['m'],
    benecat:     ['m'],
    fixed:       ['mon'],
    income:      ['mon', 'm'],
    incomemonth: ['m']
  };
  var DIMNAME = { c: '카테고리', m: '가맹점', b: '누구 몫', p: '결제한 사람', mon: '월' };

  function dimOf(t, dim) {
    if (dim === 'c') return t.c;
    if (dim === 'm') return t.m;
    if (dim === 'b') return t.b;
    if (dim === 'p') return t.p;
    if (dim === 'mon') return t.d.slice(0, 7);
    return '';
  }

  function pick(kind, key, key2) {
    if (kind === 'beneficiary') return TX.filter(function (t) { return t.b === key; });
    if (kind === 'member')   return TX.filter(function (t) { return t.p === key; });
    if (kind === 'category') return TX.filter(function (t) { return t.c === key; });
    if (kind === 'fixed')    return TX.filter(function (t) { return t.m === key && t.p === key2; });
    if (kind === 'month')    return TX.filter(function (t) { return t.d.slice(0, 7) === key; });
    if (kind === 'income')   return TX.filter(function (t) { return t.k === '수입' && t.p === key; });
    if (kind === 'incomemonth') return TX.filter(function (t) {
      return t.k === '수입' && t.d.slice(0, 7) === key;
    });
    if (kind === 'monthcategory') return TX.filter(function (t) {
      return t.d.slice(0, 7) === key && t.c === key2;
    });
    if (kind === 'benecat') return TX.filter(function (t) {
      return t.b === key && t.c === key2;
    });
    if (kind === 'monthperson') return TX.filter(function (t) {
      return t.d.slice(0, 7) === key && t.b === key2;
    });
    if (kind === 'delta')    return TX.filter(function (t) {
      return t.c === key && (t.d.slice(0, 7) === MONTHS.cur || t.d.slice(0, 7) === MONTHS.prev);
    });
    return [];
  }

  // 펼칠 때마다 다음 단계를 만들기 위해 행 묶음을 들고 있는다
  var STORE = {}, SEQ = 0;

  function 거래목록(rows) {
    rows = rows.slice().sort(function (a, b) { return a.d < b.d ? 1 : -1; });
    var shown = rows.slice(0, 60);
    var body = shown.map(function (t) {
      var dup = t.x ? '<span class="tag warn">중복 의심</span>' : '';
      var isIn = t.k === '수입';
      return '<div class="dtl-row">' +
        '<div class="dtl-main">' +
          '<div class="dtl-t">' + esc(t.m) + dup + '</div>' +
          '<div class="dtl-s">' + t.d + ' · ' + esc(t.c) + ' · ' +
            (t.b && t.b !== t.p ? esc(t.p) + ' 결제 → ' + esc(t.b) + ' 몫' : esc(t.p)) +
            ' · ' + esc(t.f) + '</div>' +
        '</div>' +
        '<div class="dtl-a' + (isIn ? ' in' : '') + '">' + (isIn ? '+' : '') + won(t.a) + '</div>' +
      '</div>';
    }).join('');
    return body + (rows.length > shown.length
      ? '<div class="dtl-note">' + rows.length + '건 중 60건만 보여드려요. 전체는 out/거래통합.csv 에 있습니다.</div>'
      : '');
  }

  function 묶음목록(rows, chain, depth) {
    if (depth >= chain.length) return 거래목록(rows);
    var dim = chain[depth], map = {}, keys = [];
    rows.forEach(function (t) {
      var k = dimOf(t, dim) || '기타';
      if (!map[k]) { map[k] = { sum: 0, n: 0, rows: [] }; keys.push(k); }
      map[k].sum += Math.abs(t.a); map[k].n++; map[k].rows.push(t);
    });
    var 뒤로 = { '수입': 1, '이체': 1 };          // 소비가 아닌 것은 아래로 내린다
    keys.sort(function (a, b) {
      var pa = 뒤로[a] || 0, pb = 뒤로[b] || 0;
      return pa !== pb ? pa - pb : map[b].sum - map[a].sum;
    });
    var 소비 = keys.filter(function (k) { return !뒤로[k]; });
    var max = 소비.length ? map[소비[0]].sum : (keys.length ? map[keys[0]].sum : 1);
    var 다음 = depth + 1 < chain.length ? DIMNAME[chain[depth + 1]] + '별' : '거래 하나하나';

    return keys.map(function (k) {
      var g = map[k], id = 'g' + (++SEQ);
      // 사람으로 나눌 때는 막대에 쓴 색을 그대로 쓴다. 색이 다르면 같은 사람인 줄 모른다.
      var 색 = ((dim === 'b' || dim === 'p') && WHOCOLOR[k])
               ? WHOCOLOR[k] : 계단(keys.length, keys.indexOf(k));
      STORE[id] = { rows: g.rows, chain: chain, depth: depth + 1 };
      return '<div class="grp" data-id="' + id + '">' +
        '<div class="grp-row" title="누르면 ' + 다음 + '로 나뉩니다">' +
          '<span class="chev2"></span>' +
          '<span class="gdot" style="background:' + 색 + '"></span>' +
          '<span class="grp-n">' + esc(k) + '</span>' +
          '<span class="grp-c">' + g.n + '건</span>' +
          '<span class="grp-v">' + won(g.sum) + '</span>' +
        '</div>' +
        누구몫(g.rows, Math.min(100, g.sum / max * 100), 색) +
        '<div class="grp-items" hidden></div>' +
      '</div>';
    }).join('');
  }

  // 가족 그림글자 — 이름 앞머리로 고른다
  function 얼굴(이름) {
    var n = String(이름 || '');
    if (n.indexOf('가족') === 0 || n.indexOf('공통') >= 0) return '👨‍👩‍👧‍👦';
    if (n.indexOf('아빠') === 0 || n.indexOf('남편') === 0) return '👨';
    if (n.indexOf('엄마') === 0 || n.indexOf('아내') === 0) return '👩';
    if (n.indexOf('딸') === 0) return '👧';
    if (n.indexOf('아들') === 0) return '👦';
    if (n.indexOf('막내') === 0) return '🧒';
    if (n.indexOf('할') === 0) return '🧓';
    return '🙂';
  }

  // 이 묶음이 누구를 위해 쓰인 돈인지 — 위 막대와 같은 폭으로 그린다.
  // 100% 폭으로 그리면 금액이 더 큰 것처럼 보인다.
  function 누구몫(rows, 폭, 바탕) {
    var 몫 = {}, 총 = 0;
    rows.forEach(function (t) {
      if (t.k !== '지출') return;
      var b = t.b || t.p;
      몫[b] = (몫[b] || 0) + (-t.a);
      총 += -t.a;
    });
    var 이름들 = Object.keys(몫);
    var 띠 = 'width:' + (폭 || 100).toFixed(1) + '%';

    // 소비가 아닌 묶음(수입·이체)이나 한 사람 몫이면 한 가지 색으로만 그린다
    if (총 <= 0) {
      return '<div class="mixwrap" style="' + 띠 + '"><div class="mix">' +
             '<span style="width:100%;background:' + (바탕 || '#C7CDD6') + '"></span></div></div>';
    }
    이름들.sort(function (a, b) { return 몫[b] - 몫[a]; });
    if (이름들.length < 2) {
      return '<div class="mixwrap" style="' + 띠 + '"><div class="mix">' +
             '<span style="width:100%;background:' + (WHOCOLOR[이름들[0]] || 바탕 || '#C7CDD6') +
             '" title="' + esc(이름들[0]) + ' ' + won(몫[이름들[0]]) + '"></span></div></div>';
    }

    var 칸 = 이름들.map(function (n) {
      return '<span style="width:' + (몫[n] / 총 * 100).toFixed(2) + '%;background:' +
             (WHOCOLOR[n] || '#C7CDD6') + '" title="' + esc(n) + ' ' + won(몫[n]) + '"></span>';
    }).join('');
    var 칩 = 이름들.slice(0, 5).map(function (n, i) {
      var c = WHOCOLOR[n] || '#C7CDD6';
      return '<span class="mixc" style="border-color:' + c + '55' + (i === 0 ? ';background:' + c + '1A' : '') + '">' +
             '<span class="mixe">' + 얼굴(n) + '</span>' +
             '<i style="background:' + c + '"></i>' +
             esc(n.split('_')[0]) + ' <b>' + (몫[n] / 총 * 100).toFixed(0) + '%</b></span>';
    }).join('');
    var 더 = 이름들.length > 5 ? '<span class="mixc muted-text">외 ' + (이름들.length - 5) + '명</span>' : '';
    return '<div class="mixwrap" style="' + 띠 + '"><div class="mix">' + 칸 + '</div></div>' +
           '<div class="mixlab">' + 칩 + 더 + '</div>';
  }

  function 제목(kind, key, key2) {
    if (kind === 'fixed') return esc(key) + ' (' + esc(key2) + ') 결제 이력';
    if (kind === 'delta') return esc(key) + ' · ' + MONTHS.prev + ' ~ ' + MONTHS.cur;
    if (kind === 'month') return key + ' 한 달';
    if (kind === 'monthperson') return key + ' · ' + esc(key2) + ' 몫';
    if (kind === 'monthcategory') return key + ' · ' + esc(key2);
    if (kind === 'benecat') return esc(key) + ' · ' + esc(key2);
    if (kind === 'income') return esc(key) + ' 님이 번 돈';
    if (kind === 'incomemonth') return key + ' 에 들어온 돈';
    return esc(key);
  }

  function 머리(kind, key, key2, rows) {
    var 수입쪽 = (kind === 'income' || kind === 'incomemonth');
    var 합 = 0;
    rows.forEach(function (t) {
      if (수입쪽) { if (t.k === '수입') 합 += t.a; }
      else if (t.k === '지출') 합 += -t.a;
    });
    var 길 = (CHAIN[kind] || []).map(function (d) { return DIMNAME[d]; });
    길.push('개별 거래');
    return '<div class="dtl-head"><span>' + 제목(kind, key, key2) + '</span>' +
           '<span>' + rows.length + '건 · ' + (수입쪽 ? '수입 ' : '지출 ') +
           합.toLocaleString('ko-KR') + '원</span></div>' +
           '<div class="dtl-path">누를수록 잘게 나뉩니다 · ' + 길.join(' → ') + '</div>';
  }

  // ── 1단계: 카드·막대를 누르면 열린다 ──────────────────────────────────
  document.querySelectorAll('[data-kind]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      var 묶음 = el.closest('[data-group]');
      if (!묶음) return;

      // 목록의 한 줄을 누르면 그 줄 바로 밑에 연다.
      // 카드 맨 아래에 열면 어느 줄을 눌렀는지 알 수 없다.
      var 줄인가 = el.classList.contains('row');
      var host;
      if (줄인가) {
        host = el.nextElementSibling;
        if (!host || !host.classList.contains('detail-inline')) {
          host = document.createElement('div');
          host.className = 'detail-inline';
          el.after(host);
        }
      } else {
        host = 묶음.querySelector('.detail-host');
      }
      if (!host) return;

      var kind = el.dataset.kind, key = el.dataset.key, key2 = el.dataset.key2;
      var 조각 = e.target.closest ? e.target.closest('i[data-person]') : null;
      if (조각 && kind === 'month') { kind = 'monthperson'; key2 = 조각.dataset.person; }

      var 표 = kind + '|' + key + '|' + (key2 || '');
      var 열려있음 = el.classList.contains('open') && host.dataset.sig === 표;

      묶음.querySelectorAll('.open').forEach(function (o) { o.classList.remove('open'); });
      묶음.querySelectorAll('.detail-inline').forEach(function (d) {
        if (d !== host) d.remove();
      });
      var 공용 = 묶음.querySelector('.detail-host');
      if (공용 && 공용 !== host) { 공용.innerHTML = ''; 공용.hidden = true; 공용.dataset.sig = ''; }
      host.innerHTML = ''; host.hidden = true; host.dataset.sig = '';
      if (열려있음) { if (줄인가) host.remove(); return; }

      var rows = pick(kind, key, key2);
      host.innerHTML = 머리(kind, key, key2, rows) +
                       묶음목록(rows, CHAIN[kind] || ['c', 'm'], 0);
      host.hidden = false;
      host.dataset.sig = 표;
      el.classList.add('open');
    });
  });

  // ── 탭 ────────────────────────────────────────────────────────────────
  function 탭열기(id) {
    document.querySelectorAll('.panel').forEach(function (p) { p.hidden = p.id !== id; });
    document.querySelectorAll('.tab-btn').forEach(function (b) {
      b.setAttribute('aria-selected', String(b.dataset.tab === id));
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
    try { sessionStorage.setItem('ff-tab', id); } catch (e) {}
  }
  document.querySelectorAll('.tab-btn').forEach(function (b) {
    b.addEventListener('click', function () { 탭열기(b.dataset.tab); });
  });
  try {
    var 저장 = sessionStorage.getItem('ff-tab');
    if (저장 && document.getElementById(저장)) 탭열기(저장);
  } catch (e) {}

  // ── 오늘의 소식 키워드 ────────────────────────────────────────────────
  document.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('.nchip') : null;
    if (!b) return;
    var 묶음 = b.closest('.news');
    var 켤까 = b.getAttribute('aria-pressed') !== 'true';
    묶음.querySelectorAll('.nchip').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); });
    묶음.querySelectorAll('.nbox').forEach(function (x) { x.hidden = true; });
    if (켤까) {
      b.setAttribute('aria-pressed', 'true');
      var 상자 = 묶음.querySelector('.nbox[data-n="' + b.dataset.n.replace(/"/g, '\\"') + '"]');
      if (상자) 상자.hidden = false;
    }
  });

  // ── 확인해볼 것 펼치기 ────────────────────────────────────────────────
  document.addEventListener('click', function (e) {
    var h = e.target.closest ? e.target.closest('.flag-head') : null;
    if (!h) return;
    var 카드 = h.parentElement, 몸 = 카드.querySelector('.flag-body');
    if (!몸) return;
    몸.hidden = !몸.hidden;
    카드.classList.toggle('open', !몸.hidden);
  });

  // ── 유형 펼치기 (자산) ────────────────────────────────────────────────
  document.addEventListener('click', function (e) {
    var r = e.target.closest ? e.target.closest('.row[data-acc]') : null;
    if (!r) return;
    var 몸 = r.nextElementSibling;
    if (!몸 || !몸.classList.contains('acc-body')) return;
    var 펼침 = 몸.hidden;

    // 유형(부동산·금융자산·현금)은 한 번에 하나만 펼친다.
    // 여러 개가 열려 있으면 어느 도넛을 보여줄지 알 수 없고 목록도 길어진다.
    if (펼침 && r.dataset.donut !== undefined) {
      var 안 = r.closest('.card');
      if (안) 안.querySelectorAll('.row[data-acc][data-donut].open').forEach(function (o) {
        o.classList.remove('open');
        var m = o.nextElementSibling;
        if (m && m.classList.contains('acc-body')) m.hidden = true;
      });
    }

    몸.hidden = !펼침;
    r.classList.toggle('open', 펼침);
    var 카드 = r.closest('.card');
    if (!카드) return;
    카드.classList.toggle('focus', !!카드.querySelector('.row[data-acc].open'));
    var 열린 = 카드.querySelector('.row[data-acc][data-donut].open');
    카드.querySelectorAll('.subdonut').forEach(function (d) {
      d.hidden = !(열린 && d.dataset.for === 열린.dataset.donut);
    });
  });

  // ── 사람 고르기 (보험) ────────────────────────────────────────────────
  document.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('.sub-btn') : null;
    if (!b) return;
    var 묶음 = b.closest('[data-subgroup]');
    묶음.querySelectorAll('.sub-btn').forEach(function (x) {
      x.setAttribute('aria-selected', String(x === b));
    });
    묶음.querySelectorAll('.subpanel').forEach(function (p) {
      p.hidden = p.id !== b.dataset.sub;
    });
  });

  // ── 더 보기 / 다른 탭으로 가기 ────────────────────────────────────────
  document.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('.more-btn') : null;
    if (!b) return;
    if (b.dataset.goto) { 탭열기(b.dataset.goto); return; }
    var 더 = b.previousElementSibling;
    if (!더 || !더.classList.contains('more')) return;
    더.hidden = !더.hidden;
    b.textContent = 더.hidden ? b.dataset.label : '접기';
    if (더.hidden && b.dataset.label) b.textContent = b.dataset.label;
  });
  document.querySelectorAll('.more-btn').forEach(function (b) {
    if (!b.dataset.goto) b.dataset.label = b.textContent;
  });

  // ── 2단계 이후: 묶음을 누르면 그 안이 또 나뉜다 ──────────────────────
  document.addEventListener('click', function (e) {
    var 줄 = e.target.closest ? e.target.closest('.grp-row') : null;
    if (!줄) return;
    var grp = 줄.parentElement, 안 = grp.querySelector('.grp-items');
    if (grp.classList.contains('open')) {
      grp.classList.remove('open'); 안.hidden = true; 안.innerHTML = '';
      return;
    }
    var s = STORE[grp.dataset.id];
    if (s && !안.innerHTML) 안.innerHTML = 묶음목록(s.rows, s.chain, s.depth);
    grp.classList.add('open'); 안.hidden = false;
  });
})();
"""


# ============================================================================
def html만들기(A, 거래들, 입력파일, 자산, 보험, 가족들, 종목, 조언, 뉴스, 재무):
    파일수 = len({t["원본파일"].split(":")[0] for t in 거래들})
    중복 = [t for t in 거래들 if t["중복의심"] == "Y"]
    중복금액 = sum(abs(t["금액"]) for t in 중복) // 2

    고정비들, 관측개월 = 고정비찾기(A)
    중복구독 = 중복구독찾기(고정비들)
    고정비월합 = sum(f["월금액"] for f in 고정비들)
    고정비연합 = sum(f["연환산"] for f in 고정비들)   # 목록 합계와 어긋나지 않게 같은 값을 쓴다
    이번, 지난, 변화 = 전월대비(A)

    색맵 = {}
    i = 0
    for p in A["수혜자들"] + A["사람들"]:
        if p in 색맵:
            continue
        색맵[p] = 공통색 if p == "가족공통" else 구성원색[i % len(구성원색)]
        i += p != "가족공통"
    생성 = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    월지출 = A["총지출"] // max(1, len(A["달들"]))
    점검 = 보험점검(보험, 가족들, 고정비들, 월지출) if 보험["증권"] else []
    경고수 = sum(1 for s in 점검 if s["급"] == "warn")

    중복안내 = ""
    if 중복:
        중복안내 = f"""<div class="note"><div class="bar"></div>
  <p><strong>같은 거래가 두 번 잡힌 것으로 보이는 게 {len(중복)//2}쌍 있어요</strong> (약 {돈(중복금액)}).
  가계부 앱과 카드사 파일에 같은 결제가 함께 들어 있을 때 생깁니다.
  자동으로 지우지 않았으니 그만큼 부풀어 있을 수 있다는 점을 감안해 주세요.</p>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<meta name="theme-color" content="#0F1620">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="우리집 가계">
<meta name="format-detection" content="telephone=no">
<link rel="manifest" href="manifest.json">
<link rel="apple-touch-icon" href="icon-192.png">
<link rel="icon" type="image/png" href="icon-192.png">
<title>우리집 가계 점검</title>
<style>{CSS}</style>
</head>
<body>
<div class="app">

  <div class="top">
    <h1>우리집 가계</h1>
    <div class="period">파일 {파일수}개 · 거래 {len(거래들)}건 · {esc(생성)} 기준</div>
  </div>

  <nav class="tabs" role="tablist">
    <button class="tab-btn" type="button" role="tab" aria-selected="true"  data-tab="p-wealth">자산·보험{f'<span class="n">{경고수}</span>' if 경고수 else ''}</button>
    <button class="tab-btn" type="button" role="tab" aria-selected="false" data-tab="p-spend">수입·지출</button>
    <button class="tab-btn" type="button" role="tab" aria-selected="false" data-tab="p-summary">이번 달</button>
  </nav>

  <section class="panel" id="p-summary" role="tabpanel" hidden>
    <p class="tab-lead"><b>이번 달 우리집은 어떤가.</b>
    {esc(이번 or "-")} 기준으로 추렸습니다. 전체 흐름은 <b>수입·지출</b>,
    지금 가진 것은 <b>자산·보험</b> 탭에 있어요.</p>
    {히어로(A, 이번, 지난)}
    {통계카드(A, 자산, 고정비월합, 고정비연합, len(중복)//2 + len(중복구독) + 경고수)}
    {중복안내}

    {f'''<h2>AI가 본 우리집 <span class="tag">{esc(조언.get("모델", "Gemini"))}</span></h2>
    <p class="lead">집계한 숫자를 읽고 쓴 요약입니다. 눌러서 설명을 볼 수 있어요.</p>
    {구역_AI(조언)}''' if 조언 else ""}

    {f'''<h2>먼저 확인해볼 것</h2>
    <p class="lead">가장 눈에 띄는 것만 추렸습니다. 나머지는 자산·보험 탭에 있어요.</p>
    {구역_점검([s for s in 점검 if s["급"] == "warn"][:3])}
    <button class="more-btn" type="button" data-goto="p-wealth"
      style="background:var(--surface);border-radius:var(--r-md);box-shadow:var(--sh);border:none;margin-top:11px">
      확인할 것 {len(점검)}가지 전부 보기 →</button>''' if 점검 else ""}

    <h2>이번 달 어디에 썼나</h2>
    <p class="lead">{esc(이번 or "-")} 한 달만 본 것입니다.
    전체 기간과 지난달 비교는 <b>수입·지출</b> 탭에 있어요.</p>
    {요약_이번달(A, 이번)}
    <button class="more-btn" type="button" data-goto="p-spend"
      style="background:var(--surface);border-radius:var(--r-md);box-shadow:var(--sh);border:none;margin-top:11px">
      전체 {len(A["달들"])}개월 흐름 보기 →</button>
  </section>

  <section class="panel" id="p-spend" role="tabpanel" hidden>
  <p class="tab-lead"><b>{len(A["달들"])}개월 동안 돈이 어떻게 드나들었나.</b>
  들어온 돈과 나간 돈을 같은 기준으로 놓고 봅니다.</p>

  <h2>번 돈과 쓴 돈</h2>
  <p class="lead">지출만 보면 많이 썼는지 알 수 없습니다.
  <b>번 돈과 나란히</b> 놓아야 감당할 만한 소비였는지가 보여요.</p>
  {구역_수입(A, 색맵)}

  <h2>월별 추이</h2>
  <p class="lead">막대 한 칸이 한 달이고, 색은 <b>누구 몫이었는지</b>를 나타냅니다.</p>
  {차트_월별(A, 색맵, 이번)}

  <h2>누구를 위해 썼나</h2>
  <p class="lead">돈을 낸 사람이 아니라 <b>그 돈이 쓰인 사람</b> 기준입니다.
  아이 학원비가 엄마 카드에서 나가도 아이 몫으로 셉니다.</p>
  {목록_수혜자(A, 색맵)}

  <h2 style="font-size:15px;margin-top:28px">누구 카드에서 나갔나</h2>
  <p class="lead">위와 숫자가 다른 것이 정상입니다. 한 사람이 가족 몫을 몰아서 결제하기 때문이에요.</p>
  {목록_결제자(A)}

  <h2>어디에 썼나</h2>
  <p class="lead">카테고리별 지출을 큰 것부터 정렬했습니다.</p>
  {구역_카테고리(A)}

  <h2>매달 빠져나가는 고정비</h2>
  <p class="lead">매달 빠짐없이 · 비슷한 금액 · 비슷한 날짜에 결제된 것만 골랐습니다.</p>
  {목록_고정비(고정비들, 관측개월, 중복구독)}

  <h2>지난달과 달라진 것</h2>
  <p class="lead">{esc(지난 or "-")} 와 {esc(이번 or "-")} 를 카테고리별로 비교했습니다.</p>
  {목록_전월대비(이번, 지난, 변화)}

  <h2>해마다 견주기</h2>
  <p class="lead">연 총액만 보면 진행 중인 해가 무조건 적게 나옵니다.
  <b>같은 달까지 잘라서</b> 견줘야 작년보다 많이 쓰고 있는지 알 수 있어요.</p>
  {연도비교(A)}
  </section>

  <section class="panel" id="p-wealth" role="tabpanel">
  <p class="tab-lead"><b>지금 이 시점에 가진 것과, 그것을 지키는 보장.</b>
  드나든 돈이 아니라 <b>남아 있는 잔고</b> 기준입니다.</p>

  {f'''<h2>자산 현황</h2>
  <p class="lead">총 {돈(자산["총자산"])} · 직접 적어 넣은 자산 {len(자산["항목"])}건 기준입니다.</p>
  {구역_자산(자산, 종목, 뉴스, 재무)}''' if 자산["항목"] else ""}

  {f'''<h2>보험 점검</h2>
  <p class="lead">가족이 어떤 보장을 얼마나 가지고 있는지, 누가 비어 있는지 한 표에 모았습니다.</p>
  {구역_보험(보험, 가족들)}''' if 보험["증권"] else ""}

  {f'''<h2>확인해볼 것 {len(점검)}가지</h2>
  <p class="lead">사실만 짚고, 상담할 때 그대로 물어볼 수 있는 문장을 함께 적었습니다.
  이 도구는 어떤 보험을 들거나 해지하라고 권하지 않습니다.</p>
  {구역_점검(점검)}''' if 점검 else ""}
  </section>

  <div class="footer">
    <span class="warn">이 파일에는 실제 거래 내역이 들어 있습니다.</span>
    메신저나 메일로 공유하지 마세요.<br><br>
    이 도구는 숫자를 모아 보여주는 정리 도구이며, 투자나 보험 가입·해지를 권유하지 않습니다.
    판단은 본인이 하시고, 필요하면 자격을 갖춘 전문가와 상담하세요.<br>
    원본: {esc(입력파일)}
  </div>

</div>

<script type="application/json" id="tx-data">{상세데이터(거래들, A["달들"])}</script>
<script type="application/json" id="color-data">{json.dumps(색맵, ensure_ascii=False)}</script>
<script type="application/json" id="month-data">{json.dumps({"cur": 이번, "prev": 지난}, ensure_ascii=False)}</script>
<script>{JS}</script>
</body>
</html>"""


# ============================================================================
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="거래표를 HTML 대시보드로 만듭니다.")
    ap.add_argument("--input", default="out/거래통합.csv")
    ap.add_argument("--output", default="out/우리집_점검.html")
    ap.add_argument("--ai", default="out/ai_조언.json",
                    help="scripts/advise.py 가 만든 분석 결과 (없으면 그 구역은 빠짐)")
    ap.add_argument("--data", default="data/sample",
                    help="자산.csv · 보험.csv · 가족.csv 가 들어 있는 폴더 (기본: data/sample)")
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

    자료 = Path(args.data)
    자산 = 자산집계(표읽기(자료 / "자산.csv"))
    보험 = 보험집계(표읽기(자료 / "보험.csv"))
    종목 = 종목집계(표읽기(자료 / "보유종목.csv"))

    재무 = None
    재무파일 = 자료 / "종목재무.json"
    if 재무파일.exists():
        try:
            재무 = json.loads(재무파일.read_text(encoding="utf-8"))
        except Exception:
            재무 = None

    뉴스 = None
    뉴스파일 = 자료 / "뉴스.json"
    if 뉴스파일.exists():
        try:
            뉴스 = json.loads(뉴스파일.read_text(encoding="utf-8"))
        except Exception:
            뉴스 = None

    조언 = None
    조언파일 = Path(args.ai)
    if 조언파일.exists():
        try:
            조언 = json.loads(조언파일.read_text(encoding="utf-8"))
        except Exception:
            조언 = None
    가족행 = 표읽기(자료 / "가족.csv")
    가족들 = [(r.get("사람") or "").strip() for r in 가족행 if (r.get("사람") or "").strip()] \
        or A["사람들"]

    출력 = Path(args.output)
    출력.parent.mkdir(parents=True, exist_ok=True)
    출력.write_text(html만들기(A, 거래들, 입력.name, 자산, 보험, 가족들, 종목, 조언, 뉴스, 재무), encoding="utf-8")
    앱으로만들기(출력.parent)

    print(f"기간 {A['달들'][0]} ~ {A['달들'][-1]} / 거래 {len(거래들)}건")
    print(f"가구 총지출 {A['총지출']:,}원 / 구성원 {len(A['사람들'])}명")
    합 = sum(A["사람별"].values())
    print(f"검산: 구성원 합계 {합:,}원 {'=' if 합 == A['총지출'] else '≠'} 가구 총지출 {A['총지출']:,}원")

    고정비들, _ = 고정비찾기(A)
    print(f"\n고정비 {len(고정비들)}건 / 월 {sum(f['월금액'] for f in 고정비들):,}원 "
          f"/ 1년 {sum(f['연환산'] for f in 고정비들):,}원")
    for f in 고정비들:
        print(f"  {f['가맹점']:<22} {f['사람']:<12} 월 {f['월금액']:>9,}원  [{f['확신']}]")
    for 이름, fs in 중복구독찾기(고정비들).items():
        print(f"  ! 중복 구독: {이름} — {', '.join(f['사람'] for f in fs)}")

    if 자산["항목"]:
        print(f"\n자산 {돈(자산['총자산'])}" + (f" / 부채 {돈(자산['부채'])} / 순자산 {돈(자산['순자산'])}"
                                          if 자산["부채"] else ""))
        for k, v in sorted(자산["분류별"].items(), key=lambda kv: -kv[1]):
            print(f"  {k:<8} {v:>15,}원  ({v/자산['총자산']*100:.1f}%)")

    if 보험["증권"]:
        점검 = 보험점검(보험, 가족들, 고정비들, A["총지출"] // max(1, len(A["달들"])))
        print(f"\n보험 증권 {len(보험['증권'])}건 / 확인해볼 것 {len(점검)}가지")
        for s in 점검:
            표 = "!" if s["급"] == "warn" else "·"
            print(f"  {표} {s['제목']}")

    print(f"\n저장: {출력}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# 서울 신호 횡단보도 접근성 점검 대시보드
# 팀 한걸음 (20913 윤혜정)
#
# 데이터
#   seoul_crosswalk.csv      : 전국횡단보도표준데이터(공공데이터포털) 중 서울특별시 행
#                              서울에서는 동작구만 시설 정보를 등록함 (1,057곳, 데이터기준일자 2026-08-26)
#   seoul_tgis_crosswalk.csv : 서울시 교차로 및 횡단보도 시설·위치정보(서울 열린데이터광장, 25개 자치구 21,776곳)
#                              보행등 유무와 위치만 있고 음향신호기·점자블록 정보는 없음
#   crossing_sim.html        : 횡단 체험 화면(3인칭·1인칭)의 그림과 소리를 그리는 파일
#
# 코드는 세 부분으로 나뉜다.
#   1. 데이터 불러오기 : CSV를 읽고, 표기를 통일하고, 분석에 필요한 열을 새로 만든다.
#   2. 사이드바 만들기 : 분석 화면, 동, 보행속도 기준, 접근성 모드를 고른다.
#   3. 화면 그리기     : 고른 조건에 맞춰 그래프, 표, 체험 화면을 그린다.
#
# 핵심 원칙 : '없음'과 '모름'을 섞지 않는다.
#   설치(Y) / 미설치(N) = 없음, 결손개수(0~3)에 셈 / 정보 없음 = 모름, 결손으로 세지 않음

import json
import math
import os
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="서울 신호 횡단보도 접근성 점검", page_icon="🚦", layout="wide")

STD_FILE, TGIS_FILE, SIM_FILE = "seoul_crosswalk.csv", "seoul_tgis_crosswalk.csv", "crossing_sim.html"
FACILITIES = {"음향신호기": "음향신호기설치여부", "점자블록": "점자블록유무", "보도턱낮춤": "보도턱낮춤여부"}
STATE_ORDER = ["설치", "미설치", "정보 없음"]
STATUS_ORDER = ["완비(3개 모두 설치)", "결손 1개 확인", "결손 2개 확인", "결손 3개 확인",
                "판단 보류(미설치 없음, 정보 없음 있음)"]
NAVY, ORANGE, BLUE, GREY, RED, GREEN = "#1F3A5F", "#E8743B", "#2F6DB5", "#B9C0CA", "#C8423B", "#1E9E6A"
STATUS_COLORS = dict(zip(STATUS_ORDER, [BLUE, "#F2A65A", ORANGE, "#A4161A", "#8D96A3"]))
YES = {"Y", "YES", "유", "있음", "설치", "O", "1", "TRUE"}
NO = {"N", "NO", "무", "없음", "미설치", "X", "0", "FALSE"}
SEOUL_GU = ["강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구", "노원구", "도봉구",
            "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구", "성북구", "송파구", "양천구", "영등포구",
            "용산구", "은평구", "종로구", "중구", "중랑구"]
SMALL_N = 10
SPEEDS = {"0.8m당 1초 (교통약자 기준)": 0.8, "1m당 1초 (일반)": 1.0, "0.7m당 1초 (보호구역)": 0.7}

# 그래프 공통 모양
pio.templates["hangeoreum"] = go.layout.Template(layout=dict(
    font=dict(family="'IBM Plex Sans KR', 'Noto Sans KR', sans-serif", size=14, color="#1B2430"),
    title=dict(font=dict(size=18, color="#14213D", weight=700), x=0, xanchor="left"),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    colorway=[BLUE, ORANGE, NAVY, "#7A8FA6", GREEN],
    xaxis=dict(gridcolor="#E6E9EE", zerolinecolor="#D5DAE1", linecolor="#D5DAE1"),
    yaxis=dict(gridcolor="#E6E9EE", zerolinecolor="#D5DAE1", linecolor="#D5DAE1"),
    legend=dict(bgcolor="rgba(0,0,0,0)", title=dict(font=dict(size=13))),
    margin=dict(l=10, r=10, t=56, b=10), hoverlabel=dict(font=dict(family="'IBM Plex Sans KR', sans-serif"))))
pio.templates.default = "plotly_white+hangeoreum"


# ─────────────────────────────────────────────────────────────
# 1. 데이터 불러오기
# ─────────────────────────────────────────────────────────────
def read_csv_any(path):
    """공공데이터 CSV는 CP949와 UTF-8이 섞여 있으므로 차례로 시도한다."""
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"{path} 파일의 인코딩을 읽을 수 없습니다.")


def to_state(value):
    """칸 하나를 '설치' / '미설치' / '정보 없음' 가운데 하나로 바꾼다."""
    if pd.isna(value):
        return "정보 없음"
    v = str(value).strip().upper()
    return "설치" if v in YES else ("미설치" if v in NO else "정보 없음")


def to_number(series):
    return pd.to_numeric(series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")


def gu_name(value):
    if pd.isna(value):
        return None
    return next((t for t in str(value).split() if t in SEOUL_GU), None)


@st.cache_data
def load_std(path):
    df = read_csv_any(path)
    df.columns = [c.strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].str.strip().replace({"": pd.NA, "-": pd.NA})
    log = {"서울 행 수": len(df)}
    df = df[df["시도명"].fillna("").str.contains("서울")].copy()
    df["자치구"] = df["시군구명"].map(gu_name)
    df = df.drop_duplicates("횡단보도관리번호")
    log["중복 제거 후"] = len(df)
    df["동"] = df["소재지지번주소"].str.split().str[2].fillna("주소 없음")          # 지번주소의 법정동
    df["주소"] = df["소재지도로명주소"].fillna(df["소재지지번주소"])
    df["보행신호등"] = df["보행자신호등유무"].map(to_state)
    all_rows = df.copy()
    df = df[df["보행신호등"] == "설치"].copy()
    log["분석 대상(보행자신호등이 있는 횡단보도)"] = len(df)

    names = list(FACILITIES)
    for name, col in FACILITIES.items():
        df[name] = df[col].map(to_state)
    df["설치수"] = (df[names] == "설치").sum(axis=1)
    df["미설치수"] = (df[names] == "미설치").sum(axis=1)
    df["정보없음수"] = (df[names] == "정보 없음").sum(axis=1)
    df["결손개수"] = df["미설치수"]                                              # 확인된 결손만 센다
    df["시설상태"] = df.apply(lambda r: STATUS_ORDER[0] if r["설치수"] == 3 else
                          (f"결손 {r['미설치수']}개 확인" if r["미설치수"] > 0 else STATUS_ORDER[4]), axis=1)

    for c in ["녹색신호시간", "횡단보도연장", "차로수", "위도", "경도"]:
        df[c] = to_number(df[c])
    g, L = df["녹색신호시간"], df["횡단보도연장"]
    df["신호시간상태"] = "분석 가능"
    df.loc[g.isna() | L.isna(), "신호시간상태"] = "정보 없음"
    df.loc[(g.notna() & ((g <= 0) | (g > 180))) | (L.notna() & ((L <= 0) | (L > 100))), "신호시간상태"] = "이상값"
    log["녹색신호시간 정보 없음"] = int((df["신호시간상태"] == "정보 없음").sum())
    log["녹색신호시간 이상값"] = int((df["신호시간상태"] == "이상값").sum())
    df["차로수구간"] = pd.cut(df["차로수"], [0, 2, 4, 6, 100],
                          labels=["2차로 이하", "3~4차로", "5~6차로", "7차로 이상"]).astype(str).replace("nan", "정보 없음")
    df["지도표시"] = df["위도"].between(37.41, 37.72) & df["경도"].between(126.73, 127.28)
    return df, all_rows, log


@st.cache_data
def load_tgis(path):
    t = read_csv_any(path)
    t["보행등"] = t["보행등유무"].map(to_state)
    t["위도"], t["경도"] = to_number(t["위도"]), to_number(t["경도"])
    return t


def add_green_time_columns(df, speed):
    """기준녹색시간 = 보행진입시간 7초 + 길이 ÷ 보행속도. 판정은 반올림 전 값으로 한다."""
    out = df.copy()
    need = 7 + out["횡단보도연장"] / speed
    out["기준녹색시간"] = need.round(1)
    out["부족시간"] = (need - out["녹색신호시간"]).clip(lower=0).round(1)
    ok = out["신호시간상태"] == "분석 가능"
    out["기준미달"] = pd.NA
    out.loc[ok, "기준미달"] = out.loc[ok, "녹색신호시간"] < need[ok]
    out.loc[~ok, "부족시간"] = pd.NA
    return out


def priority_sort(d):
    """우선순위 : 확인된 결손개수 → 부족시간 → 차로수 (모두 큰 순)"""
    return d.sort_values(["결손개수", "부족시간", "차로수"], ascending=False, na_position="last")


def distance_m(lat1, lon1, lat2, lon2):
    """두 위경도 사이 거리(m), 하버사인 공식"""
    r = 6371000
    p1, p2 = math.radians(lat1), lat2.apply(math.radians)
    dphi, dl = p2 - p1, (lon2 - lon1).apply(math.radians)
    a = (dphi / 2).apply(math.sin) ** 2 + math.cos(p1) * p2.apply(math.cos) * (dl / 2).apply(math.sin) ** 2
    return 2 * r * a.apply(lambda x: math.asin(math.sqrt(x)))


for f in (STD_FILE, TGIS_FILE, SIM_FILE):
    if not os.path.exists(f):
        st.error(f"필요한 파일 {f} 이(가) 저장소에 없습니다.")
        st.stop()

std, std_all, prep_log = load_std(STD_FILE)
tgis = load_tgis(TGIS_FILE)
basis_date = std_all["데이터기준일자"].dropna().max()
std_gu = sorted(std_all["자치구"].dropna().unique())
GU_LABEL = "·".join(std_gu)


# ─────────────────────────────────────────────────────────────
# 2. 사이드바 만들기
# ─────────────────────────────────────────────────────────────
PAGES = {
    "분석": ["개요", "서울 기록 현황", "음향신호기 설치율", "녹색신호시간", "시설 종합과 우선 개선"],
    "체험": ["현장 로드뷰 점검", "횡단 체험", "내 주변 반경 점검", "개선 시나리오와 공개 요청서"],
    "자료": ["데이터 점검"],
}
st.sidebar.markdown("<div class='side-brand'>서울 신호 횡단보도<br>접근성 점검</div>", unsafe_allow_html=True)
def keep_group():
    """이미 선택된 탭을 다시 눌러도 선택이 풀리지 않게 한다."""
    if st.session_state.get("grp") is None:
        st.session_state["grp"] = st.session_state.get("grp_last", "분석")
    st.session_state["grp_last"] = st.session_state["grp"]


if hasattr(st.sidebar, "segmented_control"):
    group = st.sidebar.segmented_control("메뉴", list(PAGES), default="분석", key="grp", on_change=keep_group,
                                         label_visibility="collapsed", width="stretch") or "분석"
else:
    group = st.sidebar.radio("메뉴", list(PAGES), horizontal=True, label_visibility="collapsed")
page = st.sidebar.radio(f"{group} 화면", PAGES[group], label_visibility="collapsed")

st.sidebar.markdown("<div class='side-h'>점검 조건</div>", unsafe_allow_html=True)
dong_options = std["동"].value_counts().index.tolist()
selected_dong = st.sidebar.multiselect(f"법정동 ({GU_LABEL})", dong_options, default=[], placeholder="전체")
speed_label = st.sidebar.selectbox("보행속도 기준", list(SPEEDS))
speed = SPEEDS[speed_label]
min_missing = st.sidebar.slider("확인된 결손개수 최소값", 0, 3, 1, help="우선 개선 목록과 지도에 표시할 기준입니다.")
include_unknown = st.sidebar.checkbox("정보 없음 항목이 있는 횡단보도 포함", value=False)

st.sidebar.markdown("<div class='side-h'>접근성</div>", unsafe_allow_html=True)
high_contrast = st.sidebar.toggle("고대비·큰 글씨", value=False)
voice = st.sidebar.toggle("음성 안내 (페이지 전체 읽기)", value=True, help="각 페이지 맨 위의 읽기 버튼으로 화면의 모든 글을 음성으로 읽어 드립니다. 그래프는 분석 결과 요약 문장으로 안내합니다.")
st.sidebar.caption("결손개수는 ‘미설치’로 기록된 항목만 집계합니다. 비어 있는 항목은 ‘정보 없음’으로 구분합니다.")

df = std[std["동"].isin(selected_dong)] if selected_dong else std
df = add_green_time_columns(df, speed)
area = f"{GU_LABEL} " + (", ".join(selected_dong) if selected_dong else "전체")
speed_short = speed_label.split(" (")[0]


# ─────────────────────────────────────────────────────────────
# 3. 화면 그리기
# ─────────────────────────────────────────────────────────────
BASE_CSS = """
<style>
@import url('https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans-kr@5/400.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans-kr@5/500.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans-kr@5/600.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans-kr@5/700.css');
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select, label { font-family: 'IBM Plex Sans KR', 'Noto Sans KR', sans-serif !important; }
.block-container { padding-top: 3.2rem; max-width: 1240px; }
[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid #E3E7ED; }
.side-brand { font-size: 1.15rem; font-weight: 700; color: #1F3A5F; margin: .2rem 0 .8rem; }
.side-h { font-size: .78rem; font-weight: 700; color: #8A94A3; letter-spacing: .08em; margin: 1.2rem 0 .3rem; }
.hero { background: #ECEEF1; border: 1px solid #DDE1E6; color: #1B2430; border-radius: 18px; padding: 26px 30px; margin-bottom: 18px; }
.hero .eyebrow { font-size: .82rem; letter-spacing: .08em; color: #5B6675; font-weight: 700; }
.hero h1 { font-size: 1.9rem; font-weight: 700; margin: .35rem 0 .4rem; color: #14213D; line-height: 1.3; }
.hero p { margin: 0; color: #4B5563; font-size: .97rem; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 4px 0 18px; }
.kpi { background: #fff; border: 1px solid #E3E7ED; border-radius: 14px; padding: 16px 18px; }
.kpi .k { font-size: .88rem; color: #4B5563; font-weight: 600; }
.kpi .v { font-size: 1.95rem; font-weight: 700; color: #1F3A5F; line-height: 1.25; font-variant-numeric: tabular-nums; }
.kpi .s { font-size: .8rem; color: #8A94A3; }
.kpi.alert .v { color: #C8423B; }
.summary { background: #FFFFFF; border: 1px solid #E3E7ED; border-left: 5px solid #E8743B; border-radius: 12px; padding: 14px 18px; margin: 6px 0 14px; }
.summary .h { font-size: .8rem; font-weight: 700; color: #E8743B; letter-spacing: .06em; margin-bottom: 4px; }
.summary .b { font-size: 1.02rem; line-height: 1.75; color: #1B2430; }
.note { font-size: .86rem; color: #5B6675; line-height: 1.6; }
.sec { font-size: 1.22rem; font-weight: 700; color: #1B2430; margin: 18px 0 6px; }
.card { background:#fff; border:1px solid #E3E7ED; border-radius:14px; padding:16px 18px; }
.tag { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.8rem; font-weight:700; margin-right:6px; }
.tag.ok { background:#E8F1FB; color:#1F4F8A; } .tag.bad { background:#FCE9E2; color:#A23B14; } .tag.unk { background:#EEF0F3; color:#5B6675; }
.grade { font-size: 3rem; font-weight: 900; line-height: 1; }
h1, h2, h3, .sec, .hero h1 { letter-spacing: -0.01em; }
.stApp p, .stApp li { line-height: 1.7; }
[data-testid="stWidgetLabel"] p { font-weight: 600 !important; color: #1B2430 !important; font-size: .95rem !important; }
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p { font-size: .9rem !important; }
[data-testid="stSidebar"] div[role="radiogroup"] label { padding: 6px 8px; border-radius: 8px; }
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) { background: #EEF3F9; }
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p { font-weight: 700; color: #1F3A5F; }
[data-testid="stSidebar"] [data-testid="stButtonGroup"] button p { font-weight: 700; }
.hero .eyebrow { display:inline-block; background: #CDD2D9; border: 1px solid #BFC5CD; color: #2F3A48; padding: 3px 12px; border-radius: 999px; }
ul.check { list-style: none; padding: 0; margin: 4px 0 10px; }
ul.check li { display: flex; flex-direction: column; gap: 2px; padding: 10px 0 10px 30px; border-bottom: 1px solid #EDF0F4; position: relative; }
ul.check li.mk::before { content: "✓"; position: absolute; left: 4px; top: 10px; font-weight: 700; color: #1F3A5F; }
ul.check li.nomk { padding-left: 4px; }
ul.check li b { font-weight: 700; color: #14213D; font-size: 1rem; }
ul.check li span { color: #4B5563; font-size: .93rem; }
table.spec { width: 100%; border-collapse: collapse; margin: 10px 0 4px; font-size: .9rem; }
table.spec td { padding: 6px 8px; border-bottom: 1px solid #EDF0F4; }
table.spec td:nth-child(odd) { color: #6B7480; width: 18%; font-weight: 600; }
[data-testid="stDataFrame"] { border: 1px solid #E3E7ED; border-radius: 10px; }
div[data-testid="stRadio"] label p { font-size: .95rem; }
</style>
"""
HC_CSS = """
<style>
.stApp { background: #FFFFFF !important; }
html, body, .stApp, .stMarkdown p, label, li, td, th { font-size: 1.12rem !important; color: #000 !important; }
.hero { background: #FFF !important; border: 2px solid #000 !important; } .hero h1, .hero p { color: #000 !important; }
.kpi, .summary, .card { border: 2px solid #000 !important; }
.kpi .v { color: #000 !important; } .note { color: #000 !important; }
.summary { border-left: 8px solid #000 !important; }
</style>
"""
st.markdown(BASE_CSS + (HC_CSS if high_contrast else ""), unsafe_allow_html=True)

spoken = []                                                   # 음성 안내로 읽을 문장 모음


def hero(eyebrow, title, desc):
    st.markdown(f"<div class='hero'><div class='eyebrow'>{eyebrow}</div><h1>{title}</h1><p>{desc}</p></div>",
                unsafe_allow_html=True)


def kpis(items):
    """items : [(제목, 값, 설명, 강조여부)]"""
    html = "".join(f"<div class='kpi{' alert' if a else ''}'><div class='k'>{k}</div><div class='v'>{v}</div>"
                   f"<div class='s'>{s}</div></div>" for k, v, s, a in items)
    st.markdown(f"<div class='kpis'>{html}</div>", unsafe_allow_html=True)


def summary(text):
    """그래프마다 붙이는 분석 결과 요약 한 문단"""
    spoken.append(re.sub("<[^>]+>", "", text))
    st.markdown(f"<div class='summary'><div class='h'>분석 결과 요약</div><div class='b'>{text}</div></div>",
                unsafe_allow_html=True)


def checklist(items, marks=True):
    """(제목, 설명) 목록을 체크 표시 목록으로 그린다."""
    rows = "".join(f"<li class='{'mk' if marks else 'nomk'}'><b>{t}</b><span>{d}</span></li>" for t, d in items)
    st.markdown(f"<ul class='check'>{rows}</ul>", unsafe_allow_html=True)


def note(text):
    st.markdown(f"<div class='note'>{text}</div>", unsafe_allow_html=True)


def section(text):
    st.markdown(f"<div class='sec'>{text}</div>", unsafe_allow_html=True)


def rates_by(data, key, name):
    c = data.groupby([key, name]).size().unstack(fill_value=0).reindex(columns=STATE_ORDER, fill_value=0)
    c["전체"] = c.sum(axis=1)
    c["설치율(%)"] = (c["설치"] / (c["설치"] + c["미설치"]) * 100).round(1)
    c["정보 없음 비율(%)"] = (c["정보 없음"] / c["전체"] * 100).round(1)
    return c


def rate(series):
    known = series.isin(["설치", "미설치"]).sum()
    return (series == "설치").sum() / known * 100 if known else float("nan")


BASEMAP_TILES = [("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "© OpenStreetMap contributors")]   # 키 없이 쓰는 공개 타일


SPEED_GUIDE = """
**1. 신호 설계 기준 (한국)**

| 구분 | 기준 | 32m 횡단보도의 녹색시간 |
|---|---|---|
| 일반 | 1m당 1초 (1.0m/s) | 7 + 32 = 39초 |
| 노인, 어린이, 장애인이 많은 곳 | 0.8m당 1초 (0.8m/s) | 7 + 40 = 47초 |
| 노인·어린이 보호구역 | 최대 0.7m/s | 약 53초 |

출처 : 서울시 교통분야 누리집(2018), 파이낸셜뉴스(2026.6.28). 7초는 보행 진입 시간입니다.

**2. 이용자별 평균 보행속도 (미국 연방도로청 교육 자료, 2006)**

| 이용자 | 평균 속도 |
|---|---|
| 일반 성인 | 약 1.2m/s |
| 휠체어 이용자 | 약 1.08m/s |
| 노인 | 약 0.85m/s |
| 지팡이·목발 이용자 | 약 0.80m/s |
| 보행보조기(워커) 이용자 | 약 0.63m/s |

출처 : FHWA, Lesson 8 Pedestrian Characteristics(FHWA-HRT-05-100). 미국 평균값을 m/s로 바꾼 것이며 한국 실측과 다를 수 있습니다.
노쇠가 진행된 노인은 0.8m/s 이하로 느려질 수 있다는 연구도 있습니다(코메디닷컴 2026.2.6, JAMA 2011 연구 인용).

**3. 시각장애인과 청각장애인**

- 전맹과 저시력 : 걷는 속도보다 **출발 지연**이 더 큰 문제입니다. 신호가 바뀐 것을 눈으로 확인할 수 없으면 주변 소리로 짐작해야 하므로 녹색 시간의 앞부분을 놓치기 쉽습니다. 음향신호기는 이 지연을 줄여 줍니다. 1인칭 전맹 모드에서 직접 겪어 볼 수 있습니다.
- 흰지팡이로 바닥과 장애물을 확인하며 걸으면 평소보다 느려질 수 있습니다. 다만 시각장애인의 횡단 속도에 대한 국내 공식 수치는 찾지 못해, 이 앱은 숫자를 단정하지 않습니다.
- 청각장애인 : 걷는 속도는 큰 차이가 없을 수 있지만, 다가오는 차 소리나 경적을 듣기 어렵습니다. 남은 시간 표시처럼 눈으로 보는 신호가 중요합니다.

**4. 이 체험에서 고르는 방법**

0.8m/s는 지팡이·목발 이용자와 노인의 평균에 가깝고, 보행보조기 이용자(약 0.63m/s)는 0.7m/s 기준으로도 부족할 수 있습니다. ‘직접 입력’으로 0.6m/s 안팎을 넣어 비교해 보십시오.
"""


def map_figure(data, color, color_map, zoom, height, hover):
    kw = dict(lat="위도", lon="경도", color=color, zoom=zoom, height=height, hover_name="주소" if "주소" in data else None,
              hover_data=hover, color_discrete_map=color_map)
    fig = (px.scatter_map(data, **kw) if hasattr(px, "scatter_map") else px.scatter_mapbox(data, **kw))
    # 배경 지도 : API 키가 필요 없는 OpenStreetMap 이미지 타일, 점이 잘 보이도록 연하게
    layers = [dict(below="traces", sourcetype="raster", source=[url], sourceattribution=attr, opacity=0.55)
              for url, attr in BASEMAP_TILES]
    if hasattr(px, "scatter_map"):
        fig.update_layout(map_style="white-bg", map_layers=layers)
    else:
        fig.update_layout(mapbox_style="white-bg", mapbox_layers=layers)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), legend=dict(orientation="h", y=1.02, x=0))
    return fig


def candidates(d):
    c = d[d["결손개수"] >= min_missing]
    if not include_unknown:
        c = c[c["정보없음수"] == 0]
    c = priority_sort(c).copy()
    c.insert(0, "순위", range(1, len(c) + 1))
    return c


# ── 분석 · 개요 ──────────────────────────────────────────────
# ── 음성 안내 (E) : 페이지 맨 위에서 화면의 모든 글을 읽는다 (그래프·시뮬레이터 제외) ──
READER = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "page_reader.html"), encoding="utf-8").read()
if voice:
    components.html(READER.replace("__FALLBACK__", json.dumps(f"{page} 페이지입니다. 이 브라우저에서는 화면 글을 가져올 수 없습니다.", ensure_ascii=False)), height=64)

if page == "개요":
    hero("2026 데이터분석 연구발표회 | 팀 한걸음",
         "서울 신호 횡단보도 접근성 점검",
         "시각장애인을 중심으로, 노인·휠체어 이용자 등 보행이 불편한 모든 이용자가 신호 횡단보도를 안전하게 건널 수 있는지 "
         f"공공데이터(데이터기준일자 {basis_date})로 점검하고 우선 개선 지점을 찾습니다.")
    sig_seoul = int((tgis["보행등"] == "설치").sum())
    no_rec = int(((tgis["보행등"] == "설치") & (~tgis["자치구"].isin(std_gu))).sum())
    gt = df[df["신호시간상태"] == "분석 가능"]
    kpis([("서울 보행등 횡단보도", f"{sig_seoul:,}곳", "서울시 교차로 및 횡단보도 시설·위치정보", False),
          ("시설 기록 미공개", f"{no_rec / sig_seoul * 100:.1f}%", f"시설 정보 공개 자치구 {len(std_gu)} / 25", True),
          (f"{GU_LABEL} 음향신호기 설치율", f"{rate(df['음향신호기']):.1f}%", f"신호 횡단보도 {len(df):,}곳 기준", False),
          ("녹색신호시간 기준 미달", f"{gt['기준미달'].astype(bool).mean() * 100:.1f}%" if len(gt) else "-", speed_short, True)])
    summary(f"서울 25개 자치구 가운데 음향신호기·점자블록 기록을 공공데이터로 공개한 자치구는 {len(std_gu)}곳({GU_LABEL})입니다. "
            "나머지 자치구의 횡단보도는 시설이 없는 것이 아니라 설치 여부를 확인할 수 없는 상태이므로, 이 앱은 두 경우를 구분하여 표시합니다.")
    c1, c2 = st.columns([1.2, 1])
    with c1:
        sc = df["시설상태"].value_counts().reindex(STATUS_ORDER, fill_value=0)
        fig = px.bar(x=sc.values, y=sc.index, orientation="h", text=sc.values, color=sc.index,
                     color_discrete_map=STATUS_COLORS, labels={"x": "횡단보도 수(곳)", "y": ""},
                     title=f"{area} 신호 횡단보도 시설 상태")
        fig.update_layout(showlegend=False, height=340, xaxis_range=[0, max(sc.max() * 1.18, 1)])
        fig.update_yaxes(categoryorder="array", categoryarray=STATUS_ORDER[::-1])
        st.plotly_chart(fig, width="stretch")
    with c2:
        section("누구를 위한 점검인가")
        checklist([("음향신호기·점자블록", "시각장애인, 저시력인이 신호와 횡단보도 위치를 알 수 있게 합니다."),
                   ("보도턱낮춤", "휠체어·보행보조기 이용자, 유아차 동반 보행자, 노인이 턱 없이 진입하게 합니다."),
                   ("녹색신호시간", "노인, 장애인, 어린이 등 걸음이 느린 보행자가 신호 안에 건너게 합니다.")])
        section("이 앱으로 할 수 있는 일")
        checklist([("분석", "서울 기록 현황, 음향신호기 설치율, 녹색신호시간, 시설 종합과 우선 개선 목록"),
                   ("현장 로드뷰 점검", "결손 횡단보도의 실제 거리 모습 확인"),
                   ("횡단 체험", "3인칭 또는 1인칭으로 신호 안에 건널 수 있는지 체험"),
                   ("내 주변 반경 점검", "교차로 기준 반경 내 횡단보도의 안전 등급 확인"),
                   ("개선 시나리오와 공개 요청서", "개선 효과 계산과 요청서 작성")])
        note("이 앱의 수치는 시설 대장 기록을 바탕으로 하며, 실제 작동 여부·음량·파손 상태는 반영하지 않습니다.")

# ── 분석 · 서울 기록 현황 ────────────────────────────────────
elif page == "서울 기록 현황":
    hero("분석 01 | 서울 25개 자치구", "시설 기록이 공개된 범위",
         "서울시 자료의 보행등 횡단보도를 기준으로, 음향신호기·점자블록 설치 여부를 공공데이터로 확인할 수 있는 범위를 살펴봅니다.")
    sig = tgis[tgis["보행등"] == "설치"].groupby("자치구").size().rename("보행등 횡단보도")
    reg = std_all.groupby("자치구").size().rename("표준데이터 등록")
    comp = pd.concat([sig, reg], axis=1).reindex(SEOUL_GU).fillna(0).astype(int)
    comp["시설 정보"] = comp["표준데이터 등록"].map(lambda n: "공개" if n > 0 else "기록 없음")
    total, no_rec = comp["보행등 횡단보도"].sum(), comp.loc[comp["시설 정보"] == "기록 없음", "보행등 횡단보도"].sum()
    kpis([("보행등 횡단보도", f"{total:,}곳", "서울 25개 자치구", False),
          ("시설 기록 미공개", f"{no_rec:,}곳", f"전체의 {no_rec / total * 100:.1f}%", True),
          ("시설 정보 공개 자치구", f"{len(std_gu)}곳", GU_LABEL, False),
          ("기록 없음 자치구", f"{25 - len(std_gu)}곳", "설치율 계산에서 제외", True)])
    summary(f"서울의 보행등 횡단보도 {total:,}곳 가운데 {no_rec:,}곳({no_rec / total * 100:.1f}%)은 음향신호기·점자블록 설치 여부를 "
            "공공데이터로 확인할 수 없습니다. 기록이 없는 곳을 ‘미설치’로 계산하면 실제와 다른 결론이 나오므로, 이 화면에서는 회색으로 구분합니다.")
    comp = comp.sort_values("보행등 횡단보도")
    fig = px.bar(comp.reset_index(), x="보행등 횡단보도", y="자치구", color="시설 정보", orientation="h",
                 color_discrete_map={"공개": BLUE, "기록 없음": GREY}, labels={"보행등 횡단보도": "보행등 횡단보도 수(곳)"},
                 title="자치구별 보행등 횡단보도 수와 시설 기록 공개 여부")
    fig.update_layout(height=700, xaxis_range=[0, None], legend=dict(orientation="h", y=-0.08, x=0, title=None))
    st.plotly_chart(fig, width="stretch")
    section("서울 보행등 횡단보도 지도")
    m = tgis[tgis["보행등"] == "설치"].copy()
    m["시설 정보"] = m["자치구"].map(lambda g: "공개" if g in std_gu else "기록 없음")
    m["주소"] = m["자치구"] + " " + m["교차로명"].fillna("")
    st.plotly_chart(map_figure(m, "시설 정보", {"공개": BLUE, "기록 없음": GREY}, 10, 560, {"위도": False, "경도": False}),
                    width="stretch")
    note("회색 점은 시설이 없는 곳이 아니라 기록이 공개되지 않아 판단할 수 없는 곳(결측)입니다. "
         "서울시 자료의 X·Y 좌표(EPSG:5186)를 위도·경도로 변환하여 표시하였습니다.")

# ── 분석 · 음향신호기 설치율 ─────────────────────────────────────
elif page == "음향신호기 설치율":
    hero(f"분석 02 | {GU_LABEL}", "법정동별 음향신호기 설치율", "보행자신호등이 있는 횡단보도를 기준으로 음향신호기 설치율을 비교합니다.")
    r = rates_by(df, "동", "음향신호기")
    r["표본"] = r["전체"].map(lambda n: f"{SMALL_N}곳 미만(해석 주의)" if n < SMALL_N else "충분")
    r = r.sort_values("설치율(%)")
    big = r[r["전체"] >= SMALL_N].dropna(subset=["설치율(%)"])
    vc = df["음향신호기"].value_counts()
    kpis([("음향신호기 설치율", f"{rate(df['음향신호기']):.1f}%", area, False),
          ("설치", f"{vc.get('설치', 0):,}곳", "", False), ("미설치", f"{vc.get('미설치', 0):,}곳", "", True),
          ("동별 최대 격차", f"{big['설치율(%)'].max() - big['설치율(%)'].min():.1f}%p" if len(big) >= 2 else "-",
           f"신호 횡단보도 {SMALL_N}곳 이상인 동", False)])
    if len(big) >= 2:
        hi, lo = big["설치율(%)"].idxmax(), big["설치율(%)"].idxmin()
        summary(f"신호 횡단보도가 {SMALL_N}곳 이상인 동 가운데 음향신호기 설치율이 가장 높은 곳은 {hi}({big.loc[hi, '설치율(%)']}%), "
                f"가장 낮은 곳은 {lo}({big.loc[lo, '설치율(%)']}%)이며, 차이는 {big.loc[hi, '설치율(%)'] - big.loc[lo, '설치율(%)']:.1f}%p입니다.")
    fig = px.bar(r.reset_index(), x="설치율(%)", y="동", orientation="h", text="설치율(%)", color="표본",
                 color_discrete_map={"충분": BLUE, f"{SMALL_N}곳 미만(해석 주의)": "#A9C2DF"},
                 hover_data=["설치", "미설치", "정보 없음", "전체"], title="법정동별 음향신호기 설치율(%)",
                 category_orders={"동": list(r.index[::-1])})
    fig.add_vline(x=rate(df["음향신호기"]), line_dash="dot", line_color=NAVY,
                  annotation_text=f"전체 {rate(df['음향신호기']):.1f}%", annotation_position="top")
    fig.update_layout(xaxis_range=[0, 108], height=540, legend=dict(orientation="h", y=-0.12, x=0, title=None))
    st.plotly_chart(fig, width="stretch")
    note(f"흩어진 정도·극값 : 신호 횡단보도가 {SMALL_N}곳 미만인 동(연한 막대)은 한두 곳의 차이로 비율이 크게 변하므로 순위 해석에서 제외하였습니다. "
         "봉천동·방배동처럼 이웃 자치구의 동 이름이 나타나는 곳은 경계 도로의 횡단보도입니다.")
    with st.expander("동별 집계표 보기"):
        st.dataframe(r, width="stretch")

# ── 분석 · 녹색신호시간 ───────────────────────────────────
elif page == "녹색신호시간":
    hero(f"분석 03 | {GU_LABEL}", "녹색신호시간은 충분한가",
         f"기준녹색시간 = 보행진입시간 7초 + 횡단보도 길이 ÷ 보행속도. 현재 기준 : {speed_short}")
    gt = df[df["신호시간상태"] == "분석 가능"].copy()
    ex = df["신호시간상태"].value_counts()
    if len(gt) == 0:
        st.warning("녹색신호시간과 길이가 모두 기록된 횡단보도가 없습니다.")
        st.stop()
    below = gt["기준미달"].astype(bool)
    short = gt.loc[below, "부족시간"]
    kpis([("기준 미달", f"{below.mean() * 100:.1f}%", f"{below.sum():,} / {len(gt):,}곳", True),
          ("부족시간 중앙값", f"{short.median():.1f}초" if len(short) else "-", "기준 미달 횡단보도", False),
          ("부족시간 최댓값", f"{short.max():.1f}초" if len(short) else "-", "", True),
          ("계산 제외", f"{ex.get('정보 없음', 0) + ex.get('이상값', 0):,}곳", "정보 없음·이상값", False)])
    summary(f"분석 가능한 {len(gt):,}곳 가운데 {below.sum():,}곳({below.mean() * 100:.1f}%)의 녹색신호시간이 기준({speed_short})보다 짧습니다. "
            + (f"부족시간의 중앙값은 {short.median():.1f}초, 최댓값은 {short.max():.1f}초입니다." if len(short) else ""))
    gt["판정"] = below.map({True: "기준 미달", False: "기준 충족"})
    fig = px.scatter(gt, x="횡단보도연장", y="녹색신호시간", color="판정", opacity=0.75,
                     color_discrete_map={"기준 미달": ORANGE, "기준 충족": BLUE}, hover_data=["동", "주소", "차로수", "부족시간"],
                     labels={"횡단보도연장": "횡단보도 길이(m)", "녹색신호시간": "녹색신호시간(초)"},
                     title="횡단보도 길이와 녹색신호시간")
    xmax = gt["횡단보도연장"].max()
    fig.add_trace(go.Scatter(x=[0, xmax], y=[7, 7 + xmax / speed], mode="lines", name=f"기준선 (7초 + 길이 ÷ {speed})",
                             line=dict(color=NAVY, dash="dash", width=2)))
    fig.update_traces(marker=dict(size=9, line=dict(width=0.5, color="#fff")), selector=dict(mode="markers"))
    fig.update_layout(height=500, yaxis_range=[0, None], xaxis_range=[0, None], legend=dict(orientation="h", y=-0.16, x=0, title=None))
    st.plotly_chart(fig, width="stretch")
    order = ["2차로 이하", "3~4차로", "5~6차로", "7차로 이상"]
    lane = gt.groupby("차로수구간").agg(곳=("판정", "size"), 미달비율=("기준미달", lambda s: round(s.astype(bool).mean() * 100, 1))).reindex(order).dropna()
    c1, c2 = st.columns(2)
    with c1:
        f2 = px.bar(lane.reset_index(), x="차로수구간", y="미달비율", text="미달비율", hover_data=["곳"],
                    labels={"차로수구간": "차로수 구간", "미달비율": "기준 미달 비율(%)"}, title="차로수 구간별 기준 미달 비율(%)")
        f2.update_traces(marker_color=ORANGE)
        f2.update_layout(yaxis_range=[0, 100], height=380)
        st.plotly_chart(f2, width="stretch")
    with c2:
        if below.any():
            f3 = px.box(gt[below], x="차로수구간", y="부족시간", category_orders={"차로수구간": order}, points="all",
                        labels={"부족시간": "부족시간(초)", "차로수구간": "차로수 구간"}, title="기준 미달 횡단보도의 부족시간(초)")
            f3.update_traces(marker_color=ORANGE, line_color=NAVY)
            f3.update_layout(height=380)
            st.plotly_chart(f3, width="stretch")
    note("상관과 인과 : 넓은 도로에서 기준 미달이 많더라도 차로 수를 원인으로 단정하지 않습니다. 넓은 도로는 횡단보도가 길어 기준녹색시간 자체가 늘어나기 때문입니다. "
         "녹색신호시간에 녹색 점멸 시간이 포함되는지에 따라 비율이 달라질 수 있습니다.")

# ── 분석 · 시설 종합과 우선 개선 ─────────────────────────
elif page == "시설 종합과 우선 개선":
    hero(f"분석 04 | {GU_LABEL}", "세 가지 시설과 우선 개선 목록", "음향신호기·점자블록·보도턱낮춤을 모두 갖춘 횡단보도의 비율과 개선이 필요한 지점을 정리합니다.")
    full = df["시설상태"].eq(STATUS_ORDER[0]).mean() * 100
    kpis([(n, f"{rate(df[n]):.1f}%", f"미설치 {int((df[n] == '미설치').sum())}곳", n == "음향신호기") for n in FACILITIES]
         + [("세 가지 모두 갖춤", f"{full:.1f}%", f"{int(df['시설상태'].eq(STATUS_ORDER[0]).sum())} / {len(df)}곳", False)])
    weakest = min(FACILITIES, key=lambda n: rate(df[n]))
    summary(f"{area} 신호 횡단보도 가운데 세 가지 시설을 모두 갖춘 곳은 {full:.1f}%입니다. 설치율이 가장 낮은 시설은 "
            f"{weakest}({rate(df[weakest]):.1f}%)이며, 확인된 결손의 대부분을 차지합니다.")
    heat = pd.concat({n: rates_by(df, "동", n)["설치율(%)"] for n in FACILITIES}, axis=1)
    heat = heat.loc[df["동"].value_counts().index.intersection(heat.index)]
    h = px.imshow(heat, text_auto=".1f", aspect="auto", color_continuous_scale=["#FCE9E2", "#F7F8FA", "#2F6DB5"],
                  zmin=50, zmax=100, labels={"color": "설치율(%)"}, title="법정동 × 시설별 설치율(%)")
    h.update_layout(height=480)
    st.plotly_chart(h, width="stretch")
    section("우선 개선 횡단보도 목록")
    note("정렬 기준 : 확인된 결손개수가 많은 순 → 부족시간이 긴 순 → 차로수가 많은 순")
    top = candidates(df)
    cols = ["순위", "동", "주소", "횡단보도관리번호", "음향신호기", "점자블록", "보도턱낮춤", "결손개수", "차로수",
            "횡단보도연장", "녹색신호시간", "기준녹색시간", "부족시간", "위도", "경도"]
    st.dataframe(top[cols].head(30), width="stretch", hide_index=True)
    c1, c2 = st.columns(2)
    c1.download_button("우선 개선 목록 내려받기 (CSV)", top[cols].to_csv(index=False).encode("utf-8-sig"),
                       file_name="우선개선목록.csv", mime="text/csv", width="stretch")
    lines = [f"{r.순위}위. {r.주소}. 음향신호기 {r.음향신호기}, 점자블록 {r.점자블록}, 보도턱낮춤 {r.보도턱낮춤}."
             + (f" 녹색신호시간 {r.부족시간:.0f}초 부족." if pd.notna(r.부족시간) and r.부족시간 > 0 else "") for r in top.itertuples()]
    c2.download_button("화면낭독기용 텍스트 목록 내려받기", "\n".join(lines).encode("utf-8"),
                       file_name="우선개선목록_텍스트.txt", mime="text/plain", width="stretch")

# ── 체험 · 현장 로드뷰 점검 (A) ───────────────────────
elif page == "현장 로드뷰 점검":
    hero("체험 A | 현장 확인", "현장 로드뷰 점검",
         "결손이 확인된 횡단보도를 지도에서 확인하고, 카카오맵 로드뷰로 실제 거리 모습을 둘러보며 기록과 현장을 대조합니다.")
    top = candidates(df)
    m = top[top["지도표시"]]
    if len(m) == 0:
        st.warning("조건에 맞는 횡단보도가 없습니다. 사이드바에서 결손개수 최소값을 낮추어 주십시오.")
        st.stop()
    st.plotly_chart(map_figure(m, "시설상태", STATUS_COLORS, 13, 460,
                               {"음향신호기": True, "점자블록": True, "보도턱낮춤": True, "위도": False, "경도": False}),
                    width="stretch")
    section("점검할 횡단보도 선택")
    opts = {f"{r.순위}위   {r.주소}   ({r.시설상태})": r.Index for r in m.itertuples()}
    pick = m.loc[opts[st.selectbox("횡단보도", list(opts), label_visibility="collapsed")]]
    c1, c2 = st.columns([1.1, 1])
    with c1:
        tags = "".join(f"<span class='tag {'ok' if pick[n] == '설치' else ('bad' if pick[n] == '미설치' else 'unk')}'>"
                       f"{'✓' if pick[n] == '설치' else ('✕' if pick[n] == '미설치' else '?')} {n} {pick[n]}</span>"
                       for n in FACILITIES)
        green = f"{pick['녹색신호시간']:.0f}초 (기준 {pick['기준녹색시간']:.1f}초)" if pd.notna(pick["녹색신호시간"]) else "정보 없음"
        st.markdown(f"<div class='card'><div style='font-weight:800;font-size:1.05rem'>{pick['주소']}</div>"
                    f"<table class='spec'><tr><td>관리번호</td><td>{pick['횡단보도관리번호']}</td><td>법정동</td><td>{pick['동']}</td></tr>"
                    f"<tr><td>차로수</td><td>{int(pick['차로수']) if pd.notna(pick['차로수']) else '-'}차로</td><td>길이</td><td>{pick['횡단보도연장']:.1f}m</td></tr>"
                    f"<tr><td>녹색신호</td><td colspan='3'>{green}</td></tr></table><div style='margin-top:10px'>{tags}</div></div>",
                    unsafe_allow_html=True)
        lat, lon = pick["위도"], pick["경도"]
        b1, b2 = st.columns(2)
        b1.link_button("카카오맵 로드뷰로 현장 보기", f"https://map.kakao.com/link/roadview/{lat},{lon}", width="stretch", type="primary")
        b2.link_button("카카오맵 지도에서 보기", f"https://map.kakao.com/link/map/횡단보도,{lat},{lon}", width="stretch")
        key = st.secrets.get("KAKAO_JS_KEY", "") if hasattr(st, "secrets") and os.path.exists(".streamlit/secrets.toml") else ""
        if key:
            components.html(f"""<div id="rv" style="width:100%;height:360px;border-radius:12px"></div>
<script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={key}"></script>
<script>var rv=new kakao.maps.Roadview(document.getElementById('rv'));var c=new kakao.maps.RoadviewClient();
var p=new kakao.maps.LatLng({lat},{lon});c.getNearestPanoId(p,50,function(id){{if(id)rv.setPanoId(id,p);}});</script>""", height=370)
        note("로드뷰 사진은 공공데이터가 아니라 카카오맵이 촬영한 화면으로, 촬영 시점이 데이터 기준일과 다를 수 있습니다. "
             "분석 수치에는 사용하지 않으며 현장 확인을 돕는 용도로만 제공합니다.")
    with c2:
        section("현장 점검 기록")
        with st.form("field_check", clear_on_submit=True):
            a = st.radio("음향신호기(보행 신호등 기둥의 버튼·스피커)", ["보임", "보이지 않음", "판단 어려움"], horizontal=True)
            b = st.radio("점자블록(횡단보도 앞 노란 블록)", ["보임", "보이지 않음", "판단 어려움"], horizontal=True)
            c = st.radio("보도턱낮춤(턱 없이 이어진 보도)", ["보임", "보이지 않음", "판단 어려움"], horizontal=True)
            memo = st.text_input("메모", placeholder="예 : 로드뷰 촬영 시점 2024년, 버튼 위치 확인 어려움")
            if st.form_submit_button("점검 결과 저장", width="stretch"):
                st.session_state.setdefault("checks", []).append(
                    {"관리번호": pick["횡단보도관리번호"], "주소": pick["주소"], "기록_음향신호기": pick["음향신호기"], "현장_음향신호기": a,
                     "기록_점자블록": pick["점자블록"], "현장_점자블록": b, "기록_보도턱낮춤": pick["보도턱낮춤"], "현장_보도턱낮춤": c, "메모": memo})
        checks = pd.DataFrame(st.session_state.get("checks", []))
        if len(checks):
            st.dataframe(checks, width="stretch", hide_index=True)
            st.download_button("점검 기록 내려받기 (CSV)", checks.to_csv(index=False).encode("utf-8-sig"),
                               file_name="현장점검기록.csv", mime="text/csv", width="stretch")
        note("점검 기록은 이 브라우저 화면에만 임시로 저장됩니다. 창을 닫기 전에 내려받아 주십시오.")

# ── 체험 · 횡단 체험 (B) ──────────────────────────────
elif page == "횡단 체험":
    hero("체험 B | 시뮬레이션", "횡단 체험 : 신호 안에 건널 수 있을까",
         "실제 횡단보도의 길이와 녹색신호시간으로 건너는 과정을 재현합니다. 3인칭으로 지켜보거나, 1인칭으로 직접 건너 볼 수 있습니다.")
    gt = df[df["신호시간상태"] == "분석 가능"].sort_values("부족시간", ascending=False)
    if len(gt) == 0:
        st.warning("선택한 동에는 녹색신호시간과 길이가 모두 기록된 횡단보도가 없습니다. 사이드바에서 동을 바꾸어 주십시오.")
        st.stop()
    opts = {f"{r.주소}   (길이 {r.횡단보도연장:.1f}m, 녹색 {r.녹색신호시간:.0f}초, 음향신호기 {r.음향신호기})": r.Index for r in gt.itertuples()}
    c1, c2 = st.columns([1.4, 1])
    with c1:
        pick = gt.loc[opts[st.selectbox("체험할 횡단보도 (부족시간이 긴 순)", list(opts))]]
    with c2:
        view = st.radio("시점", ["3인칭 : 위에서 지켜보기", "1인칭 : 직접 건너기"], horizontal=True)
    c3, c4, c5 = st.columns(3)
    with c3:
        walker = st.selectbox("보행속도", ["0.8m/s (노약자·장애인이 많은 곳의 설계 기준)", "1.0m/s (일반 설계 기준)",
                                       "0.7m/s (보호구역 설계 기준)", "직접 입력"])
        v = st.slider("보행속도(m/s)", 0.3, 1.5, 0.6, 0.05) if walker == "직접 입력" else float(walker.split("m/s")[0])
        with st.expander("이용자별 보행속도 알아보기"):
            st.markdown(SPEED_GUIDE)
    with c4:
        if view.startswith("1인칭"):
            vision = st.radio("시야", ["정상", "저시력(흐림)", "전맹(화면 가림)"], horizontal=False)
        else:
            vision = "정상"
            st.markdown("**시야**")
            st.caption("시야 선택은 1인칭에서만 쓸 수 있습니다. 3인칭은 위에서 지켜보는 화면입니다.")
    with c5:
        manual = st.radio("출발 방식", ["녹색 신호와 동시에 자동 출발", "직접 판단하여 출발"], index=1 if vision.startswith("전맹") else 0) != "녹색 신호와 동시에 자동 출발"
        sound_mode = st.radio("음향신호기", ["데이터 기록대로", "있다고 가정", "없다고 가정"])
    sound = {"데이터 기록대로": pick["음향신호기"] == "설치", "있다고 가정": True, "없다고 가정": False}[sound_mode]
    params = {"L": float(pick["횡단보도연장"]), "G": float(pick["녹색신호시간"]), "v": v, "sound": bool(sound),
              "view": "first" if view.startswith("1인칭") else "third",
              "vision": {"정상": "normal", "저시력(흐림)": "low", "전맹(화면 가림)": "blind"}[vision],
              "manual": bool(manual), "lanes": int(pick["차로수"]) if pd.notna(pick["차로수"]) else 2, "label": str(pick["주소"])}
    html = open(SIM_FILE, encoding="utf-8").read()
    html = re.sub(r"/\*PARAMS\*/.*?/\*END\*/", lambda _: json.dumps(params, ensure_ascii=False), html, flags=re.S)
    components.html(html, height=720, scrolling=False)
    cover = params["v"] * params["G"]
    left = max(0.0, params["L"] - cover)
    summary(f"이 횡단보도는 길이 {params['L']:.1f}m, 녹색신호 {params['G']:.0f}초입니다. 보행속도 {v:.2f}m/s로 녹색 신호와 동시에 출발하면 "
            + (f"신호가 바뀔 때 {left:.1f}m가 남습니다." if left > 0 else f"{params['G'] - params['L'] / v:.1f}초의 여유를 두고 건널 수 있습니다.")
            + (" 음향신호기가 없으면 시각장애인은 녹색 신호가 켜진 시점을 알기 어려워 출발이 늦어질 수 있습니다." if not sound else ""))
    note("보행속도 0.7·0.8·1.0m/s는 보행신호 설계 기준(경찰청 「교통신호기 설치·관리 매뉴얼」, 서울시 교통 안내)에서 가져온 값이며, "
         "특정 개인의 실제 보행속도를 뜻하지 않습니다. 1인칭에서 소리가 나지 않으면 체험 화면 안을 한 번 누른 뒤 다시 시작하여 주십시오.")

# (보행속도 안내 글은 파일 위쪽 SPEED_GUIDE에 있음)
# ── 체험 · 내 주변 반경 점검 (C) ─────────────────────
elif page == "내 주변 반경 점검":
    hero("체험 C | 생활권 점검", "내 주변 반경 점검", "교차로를 고르거나 지도에서 횡단보도를 누르면, 그 지점을 중심으로 반경 안의 횡단보도 상태와 안전 등급을 보여 드립니다.")
    cross = tgis[(tgis["자치구"].isin(std_gu)) & tgis["교차로명"].notna()].groupby("교차로명")[["위도", "경도"]].mean()
    c1, c2 = st.columns([1.5, 1])
    with c1:
        center_name = st.selectbox("기준 교차로", cross.index.tolist(), index=cross.index.tolist().index("숭실대입구역") if "숭실대입구역" in cross.index else 0)
    with c2:
        radius = st.slider("반경(m)", 100, 600, 300, 50)
    lat0, lon0 = cross.loc[center_name, "위도"], cross.loc[center_name, "경도"]
    map_key = f"radius_map_{st.session_state.get('map_ver', 0)}"
    try:                                                   # 지도에서 누른 점이 있으면 그 점을 중심으로 한다
        pts = st.session_state[map_key]["selection"]["points"]
    except (KeyError, TypeError):
        pts = []
    pts = [p for p in pts if "lat" in p and "lon" in p]
    if pts:
        lat0, lon0 = pts[0]["lat"], pts[0]["lon"]
        center_name = "지도에서 선택한 지점"
    d = df[df["지도표시"]].copy()
    d["거리"] = distance_m(lat0, lon0, d["위도"], d["경도"])
    inside = d[d["거리"] <= radius].copy()
    inside["판정"] = inside.apply(lambda r: "판단 보류" if r["정보없음수"] > 0 or r["신호시간상태"] != "분석 가능" else
                              ("안전 조건 충족" if r["결손개수"] == 0 and not r["기준미달"] else "개선 필요"), axis=1)
    known = inside[inside["판정"] != "판단 보류"]
    ok_rate = (known["판정"] == "안전 조건 충족").mean() * 100 if len(known) else float("nan")
    grade = "-" if math.isnan(ok_rate) else ("A" if ok_rate >= 90 else "B" if ok_rate >= 75 else "C" if ok_rate >= 50 else "D")
    gcolor = {"A": BLUE, "B": "#4F8F5B", "C": ORANGE, "D": RED}.get(grade, GREY)
    c1, c2 = st.columns([1, 2.2])
    with c1:
        st.markdown(f"<div class='card' style='text-align:center'><div class='note'>{center_name} 반경 {radius}m</div>"
                    f"<div class='grade' style='color:{gcolor}'>{grade}</div><div class='note'>안전 조건 충족 "
                    f"{'-' if math.isnan(ok_rate) else f'{ok_rate:.0f}%'}</div></div>", unsafe_allow_html=True)
        st.markdown("")
        kpis([("신호 횡단보도", f"{len(inside)}곳", "", False), ("개선 필요", f"{int((inside['판정'] == '개선 필요').sum())}곳", "", True)])
        note("안전 조건 충족 = 세 가지 시설을 모두 갖추고 녹색신호시간이 현재 기준을 충족하는 횡단보도. "
             "등급(이 앱이 정한 기준) : A 90% 이상, B 75% 이상, C 50% 이상, D 50% 미만. 판단 보류는 등급 계산에서 제외합니다.")
    with c2:
        dd = d.copy()
        dd["표시"] = "반경 밖"
        dd.loc[inside.index, "표시"] = inside["판정"]
        fig = map_figure(dd, "표시", {"안전 조건 충족": BLUE, "개선 필요": ORANGE, "판단 보류": "#8D96A3", "반경 밖": "#D7DCE3"},
                         14, 480, {"음향신호기": True, "점자블록": True, "보도턱낮춤": True, "위도": False, "경도": False})
        ang = [i * 2 * math.pi / 72 for i in range(73)]
        circ_lat = [lat0 + radius / 111320 * math.cos(a) for a in ang]
        circ_lon = [lon0 + radius / (111320 * math.cos(math.radians(lat0))) * math.sin(a) for a in ang]
        trace = go.Scattermap if hasattr(go, "Scattermap") else go.Scattermapbox
        fig.add_trace(trace(lat=circ_lat, lon=circ_lon, mode="lines", line=dict(color=NAVY, width=2), name=f"반경 {radius}m", hoverinfo="skip"))
        if hasattr(go, "Scattermap"):
            fig.update_layout(map_center=dict(lat=lat0, lon=lon0))
        else:
            fig.update_layout(mapbox_center=dict(lat=lat0, lon=lon0))
        st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode="points", key=map_key)
        if pts and st.button("지도에서 고른 지점 해제 (기준 교차로로 돌아가기)"):
            st.session_state["map_ver"] = st.session_state.get("map_ver", 0) + 1
            st.rerun()
    if len(inside):
        summary(f"{center_name} 반경 {radius}m 안의 신호 횡단보도는 {len(inside)}곳이며, 이 가운데 개선이 필요한 곳은 "
                f"{int((inside['판정'] == '개선 필요').sum())}곳입니다. 안전 등급은 {grade}입니다.")
        need = inside[inside["판정"] == "개선 필요"].sort_values("거리")
        if len(need):
            st.dataframe(need[["주소", "거리", "음향신호기", "점자블록", "보도턱낮춤", "녹색신호시간", "부족시간"]]
                         .assign(거리=lambda x: x["거리"].round(0).astype(int)), width="stretch", hide_index=True)
    else:
        summary(f"{center_name} 반경 {radius}m 안에는 시설 기록이 있는 신호 횡단보도가 없습니다. 반경을 넓혀 주십시오.")

# ── 체험 · 개선 시나리오와 공개 요청서 (D+F) ──────────
elif page == "개선 시나리오와 공개 요청서":
    hero("체험 D | 정책 제안", "개선 시나리오와 공개 요청서",
         "우선순위대로 개선했을 때 지표가 얼마나 달라지는지 계산하고, 그 결과를 담은 요청서를 자치구별로 작성합니다.")
    section("1. 음향신호기 추가 설치 시나리오")
    base = df.copy()
    missing_sound = priority_sort(base[base["음향신호기"] == "미설치"])
    n_max = len(missing_sound)
    n_add = st.slider("우선순위대로 추가 설치할 음향신호기 수(대)", 0, max(n_max, 1), min(20, n_max))

    def after_install(n):
        b = base.copy()
        b.loc[missing_sound.index[:n], "음향신호기"] = "설치"
        full_n = ((b["음향신호기"] == "설치") & (b["점자블록"] == "설치") & (b["보도턱낮춤"] == "설치")).mean() * 100
        return rate(b["음향신호기"]), full_n
    curve = pd.DataFrame([(n, *after_install(n)) for n in range(0, n_max + 1)], columns=["추가 설치(대)", "음향신호기 설치율", "세 가지 모두 갖춤"])
    s_now, f_now = after_install(n_add)
    c1, c2 = st.columns([1, 1.6])
    with c1:
        kpis([("음향신호기 설치율", f"{s_now:.1f}%", f"현재 {rate(base['음향신호기']):.1f}%", False),
              ("세 가지 모두 갖춤", f"{f_now:.1f}%", f"현재 {curve.iloc[0, 2]:.1f}%", False)])
    with c2:
        fig = px.line(curve, x="추가 설치(대)", y=["음향신호기 설치율", "세 가지 모두 갖춤"], labels={"value": "비율(%)", "variable": ""},
                      title="추가 설치 대수에 따른 변화")
        fig.add_vline(x=n_add, line_dash="dot", line_color=NAVY)
        fig.update_layout(height=340, yaxis_range=[0, 100], legend=dict(orientation="h", y=-0.25, x=0, title=None))
        st.plotly_chart(fig, width="stretch")
    section("2. 녹색신호시간 연장 시나리오")
    ext = st.slider("기준 미달 횡단보도의 녹색신호시간 연장(초)", 0, 20, 5)
    gt = base[base["신호시간상태"] == "분석 가능"]
    need = 7 + gt["횡단보도연장"] / speed
    ext_curve = pd.DataFrame({"연장(초)": range(0, 21), "기준 미달 비율": [((gt["녹색신호시간"] + e) < need).mean() * 100 for e in range(0, 21)]})
    c1, c2 = st.columns([1, 1.6])
    with c1:
        kpis([("기준 미달 비율", f"{ext_curve.iloc[ext, 1]:.1f}%", f"현재 {ext_curve.iloc[0, 1]:.1f}% ({speed_short})", True)])
    with c2:
        fig = px.line(ext_curve, x="연장(초)", y="기준 미달 비율", markers=True, labels={"기준 미달 비율": "기준 미달 비율(%)"},
                      title="녹색신호시간 연장에 따른 기준 미달 비율")
        fig.update_traces(line_color=ORANGE)
        fig.add_vline(x=ext, line_dash="dot", line_color=NAVY)
        fig.update_layout(height=320, yaxis_range=[0, None])
        st.plotly_chart(fig, width="stretch")
    summary(f"우선순위가 높은 횡단보도부터 음향신호기 {n_add}대를 추가 설치하면 음향신호기 설치율은 {rate(base['음향신호기']):.1f}%에서 "
            f"{s_now:.1f}%로, 세 가지 시설을 모두 갖춘 비율은 {curve.iloc[0, 2]:.1f}%에서 {f_now:.1f}%로 높아집니다. "
            f"녹색신호시간을 {ext}초 연장하면 기준 미달 비율은 {ext_curve.iloc[0, 1]:.1f}%에서 {ext_curve.iloc[ext, 1]:.1f}%로 낮아집니다.")
    note("시나리오는 데이터상의 지표 변화만 계산한 것이며, 설치 비용·공사 가능 여부·차량 신호 운영에 미치는 영향은 반영하지 않습니다.")

    section("3. 공개 요청서 작성")
    c1, c2, c3 = st.columns(3)
    gu = c1.selectbox("대상 자치구", SEOUL_GU, index=SEOUL_GU.index(std_gu[0]) if std_gu else 0)
    to = c2.selectbox("수신", ["서울특별시의회 교통위원회", f"서울특별시 {gu}청", "서울특별시 교통운영과", "한국시각장애인연합회 서울특별시지부"])
    writer = c3.text_input("작성자", placeholder="성명")
    sig_gu = int(((tgis["자치구"] == gu) & (tgis["보행등"] == "설치")).sum())
    body = [f"수신 : {to}", f"제목 : {gu} 신호 횡단보도 시각·보행 장애인 보행시설 {'개선' if gu in std_gu else '기록 공개'} 요청", ""]
    if gu in std_gu:
        top = candidates(base)
        body += [f"1. 전국횡단보도표준데이터(데이터기준일자 {basis_date})를 분석한 결과, {gu} 보행자신호등이 있는 횡단보도 {len(base):,}곳의 "
                 f"음향신호기 설치율은 {rate(base['음향신호기']):.1f}%이며, 음향신호기·점자블록·보도턱낮춤을 모두 갖춘 곳은 {curve.iloc[0, 2]:.1f}%입니다.",
                 f"2. 시설 결손이 확인된 횡단보도는 {len(top):,}곳입니다. 우선순위가 높은 곳부터 음향신호기 {n_add}대를 설치하면 "
                 f"세 가지 시설을 모두 갖춘 비율이 {f_now:.1f}%로 높아집니다.",
                 f"3. 녹색신호시간이 보행약자 기준({speed_short})보다 짧은 횡단보도는 {ext_curve.iloc[0, 1]:.1f}%이며, {ext}초를 연장하면 "
                 f"{ext_curve.iloc[ext, 1]:.1f}%로 낮아집니다.",
                 "4. 이에 다음 사항을 요청드립니다.",
                 "  가. 결손이 확인된 횡단보도(붙임 목록)의 음향신호기·점자블록 설치 계획 공개",
                 "  나. 기준에 미달하는 횡단보도의 녹색신호시간 연장 검토",
                 "붙임 : 우선 개선 횡단보도 목록 1부."]
    else:
        body += [f"1. 서울시 교차로 및 횡단보도 시설·위치정보에 따르면 {gu}의 보행등이 있는 횡단보도는 {sig_gu:,}곳입니다.",
                 f"2. 그러나 전국횡단보도표준데이터(데이터기준일자 {basis_date})에는 {gu}의 횡단보도 시설 정보가 등록되어 있지 않아, "
                 "음향신호기·점자블록·보도턱낮춤의 설치 여부를 공공데이터로 확인할 수 없습니다.",
                 f"3. 서울 25개 자치구 가운데 해당 정보를 공개한 자치구는 {GU_LABEL} {len(std_gu)}곳입니다.",
                 "4. 이에 다음 사항을 요청드립니다.",
                 f"  가. {gu} 신호 횡단보도의 음향신호기·점자블록·보도턱낮춤 설치 정보를 전국횡단보도표준데이터에 등록·공개",
                 "  나. 기록 공개 후 미설치 지점에 대한 설치 계획 수립"]
    body += ["", f"웹앱 : (배포 주소)", f"작성자 : {writer or '(성명)'}"]
    letter = "\n".join(body)
    st.text_area("요청서 미리보기", letter, height=360)
    c1, c2 = st.columns(2)
    c1.download_button("요청서 내려받기 (TXT)", letter.encode("utf-8"), file_name=f"{gu}_보행시설_요청서.txt", mime="text/plain", width="stretch")
    if gu in std_gu:
        att = candidates(base)
        c2.download_button("붙임 : 우선 개선 목록 (CSV)", att.to_csv(index=False).encode("utf-8-sig"), file_name=f"{gu}_우선개선목록.csv",
                           mime="text/csv", width="stretch")
    note("요청서는 국민신문고, 서울시 응답소, 서울시의회 누리집의 시민 제안 창구에 그대로 붙여 넣어 제출할 수 있습니다. "
         "작성자 이름은 서버에 저장되지 않습니다.")

# ── 자료 · 데이터 점검 ──────────────────────────────────────
elif page == "데이터 점검":
    hero("자료 | 투명성", "데이터 점검 : ‘없음’과 ‘모름’", "전처리 과정과 두 자료의 대조 결과를 공개합니다.")
    checklist([("✓ 설치(Y)", "시설이 있다고 기록된 항목입니다. 설치율의 분자가 됩니다."),
               ("✕ 미설치(N) = 없음", "시설이 없다고 기록된 항목입니다. 결손개수(0~3)에 포함합니다."),
               ("? 정보 없음 = 모름", "항목이 비어 있거나 자치구가 기록을 등록하지 않은 경우입니다. 결손으로 집계하지 않습니다."),
               ("계산 원칙", f"기록이 없는 {25 - len(std_gu)}개 자치구를 ‘미설치’로 계산하면 서울 전체의 설치율이 실제와 무관하게 낮아지므로, "
                "시설 지표는 기록을 공개한 자치구 안에서만 계산합니다.")], marks=False)
    c1, c2 = st.columns(2)
    with c1:
        section("전처리 기록")
        st.dataframe(pd.Series(prep_log, name="행 수").to_frame(), width="stretch")
    with c2:
        section("시설 항목의 세 상태")
        st.dataframe(pd.DataFrame({n: df[n].value_counts().reindex(STATE_ORDER, fill_value=0) for n in FACILITIES}), width="stretch")
    section("두 자료 대조 : 같은 횡단보도관리번호의 보행신호등 기록")
    j = std_all.merge(tgis[["횡단보도관리번호", "보행등"]], on="횡단보도관리번호", how="left")
    j["서울시 자료"] = j["보행등"].fillna("서울시 자료에 없음")
    st.dataframe(pd.crosstab(j["보행신호등"].rename("표준데이터"), j["서울시 자료"]), width="stretch")
    mism = j[(j["보행등"].notna()) & (j["보행신호등"] != j["보행등"])]
    summary(f"두 자료에 모두 있는 {int(j['보행등'].notna().sum()):,}곳 가운데 {len(mism):,}곳은 보행신호등 유무가 서로 다르게 기록되어 있습니다. "
            "어느 기록이 맞는지는 현장 확인이 필요하며, 이 앱은 시설 정보가 있는 표준데이터를 기준으로 분석합니다.")
    st.dataframe(mism[["횡단보도관리번호", "주소", "보행자신호등유무", "보행등"]].rename(
        columns={"보행자신호등유무": "표준데이터", "보행등": "서울시 자료"}), width="stretch", hide_index=True)

st.markdown("<hr style='margin-top:28px;border:none;border-top:1px solid #E3E7ED'>", unsafe_allow_html=True)
note("데이터 출처 : 전국횡단보도표준데이터(공공데이터포털), 서울시 교차로 및 횡단보도 시설·위치정보(서울 열린데이터광장). "
     "시설 대장 기록이며 실제 작동 여부·음량·파손 상태는 반영하지 않습니다. 제작 : 팀 한걸음(20913 윤혜정)")

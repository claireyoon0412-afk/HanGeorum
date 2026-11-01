# 원본 데이터를 웹앱용 CSV로 바꾸는 전처리 스크립트 (한 번만 실행)
#
# 1) 전국횡단보도표준데이터.csv (공공데이터포털, CP949)
#    → 시도명이 '서울특별시'인 행만 남겨 seoul_crosswalk.csv (UTF-8)로 저장
# 2) 서울시 교차로 및 횡단보도 시설·위치정보_20260824.xlsx (서울 열린데이터광장)
#    → X·Y 좌표(EPSG:5186, 중부원점 TM)를 위도·경도(WGS84)로 바꿔 seoul_tgis_crosswalk.csv로 저장
#    좌표계는 두 자료에 함께 있는 횡단보도관리번호로 맞춰 확인했다.
#    (EPSG:5186으로 바꾼 위치와 표준데이터 위도·경도의 거리 중앙값 약 27m)
#
# 로컬에서만 실행 (pandas, openpyxl, pyproj 필요. 웹앱 배포에는 필요 없음)
# 실행 : python prepare_data.py 전국횡단보도표준데이터.csv "서울시 교차로 및 횡단보도 시설·위치정보_20260824.xlsx"

import sys

import pandas as pd
from pyproj import Transformer

std_path, tgis_path = sys.argv[1], sys.argv[2]

for enc in ("utf-8-sig", "cp949"):
    try:
        std = pd.read_csv(std_path, dtype=str, encoding=enc)
        break
    except UnicodeDecodeError:
        continue
seoul = std[std["시도명"].fillna("").str.contains("서울")]
seoul.to_csv("seoul_crosswalk.csv", index=False, encoding="utf-8-sig")
print("표준데이터 전체", len(std), "행 → 서울", len(seoul), "행")

tgis = pd.read_excel(tgis_path, dtype=str)
to_wgs84 = Transformer.from_crs(5186, 4326, always_xy=True)
lon, lat = to_wgs84.transform(tgis["X좌표"].astype(float).values, tgis["Y좌표"].astype(float).values)
tgis["위도"], tgis["경도"] = lat.round(7), lon.round(7)
tgis.to_csv("seoul_tgis_crosswalk.csv", index=False, encoding="utf-8-sig")
print("서울시 자료", len(tgis), "행 저장")

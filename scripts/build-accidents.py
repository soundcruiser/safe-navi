#!/usr/bin/env python3
"""
警察庁交通事故統計オープンデータ（本票CSV）を教習エリア内でクリップし、
交差点クラスタへ集計して data/toyota-chuo/accidents.json を生成する。

使い方:
  python3 scripts/build-accidents.py
  python3 scripts/build-accidents.py --years 2021,2022,2023
  python3 scripts/build-accidents.py --csv path/to/honhyo_2024.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "toyota-chuo" / "accidents.json"
PACK = ROOT / "data" / "toyota-chuo" / "school-pack.json"
CODES = ROOT / "data" / "npa-codes.json"

DEFAULT_CSV_URL = (
    "https://www.npa.go.jp/publications/statistics/koutsuu/opendata/2023/honhyo_2023.csv"
)
GRID = 0.00045  # おおよそ50m

HOUR_BANDS = [
    (7, 9, "morning_rush", "朝の通学・通勤時間帯"),
    (15, 17, "school_out", "下校・夕方の歩行者が増えやすい時間帯"),
    (18, 22, "evening", "夕方〜夜間（照明・視認に注意）"),
    (22, 24, "late_night", "夜間（交差点・横断歩道の確認をゆっくり）"),
    (0, 5, "late_night", "深夜帯"),
]


def load_bounds():
    with open(PACK, encoding="utf-8") as f:
        pack = json.load(f)
    b = pack["bounds"]
    return b, pack.get("center", {})


def load_codes():
    with open(CODES, encoding="utf-8") as f:
        return json.load(f)


def label(map_dict: dict, code: str) -> str:
    c = (code or "").strip()
    if not c:
        return ""
    return map_dict.get(c, map_dict.get(c.zfill(2), f"コード{c}"))


def accident_category(type_code: str) -> str:
    c = (type_code or "").strip().zfill(2)
    if not c.isdigit():
        return "その他"
    n = int(c)
    if 1 <= n <= 20:
        return "人対車両"
    if 21 <= n <= 40:
        return "車両相互"
    if 41 <= n <= 60:
        return "車両単独"
    if n == 61:
        return "列車"
    return label(load_codes().get("accidentType", {}), c) or "その他"


def dms_to_deg(s: str, is_lng: bool = False) -> float | None:
    if not s or not str(s).strip():
        return None
    s = str(s).strip()
    if s in ("9999", "0000"):
        return None
    if re.match(r"^-?\d+(\.\d+)?$", s) and len(s) <= 10:
        # 警察庁本票: 緯度9桁・経度10桁（度分秒+ミリ秒）
        if len(s) >= 8 and int(s) > 1000:
            s = s.zfill(10 if is_lng else 9)
            d_len = 3 if is_lng else 2
            d = int(s[:d_len])
            mi = int(s[d_len : d_len + 2])
            sec = int(s[d_len + 2 :]) / 1000
            return d + mi / 60 + sec / 3600
        return float(s)
    m = re.match(r"(\d+)[°度](\d+)[′'](\d+(?:\.\d+)?)", s)
    if m:
        d, mi, sec = m.groups()
        sign = -1 if s.startswith("-") else 1
        return sign * (int(d) + int(mi) / 60 + float(sec) / 3600)
    return None


def find_col(headers: list[str], *candidates: str) -> str | None:
    norm = {h.strip(): h for h in headers}
    for c in candidates:
        if c in norm:
            return norm[c]
    for h in headers:
        hs = h.strip()
        for c in candidates:
            if c in hs:
                return hs
    return None


def parse_row(row: dict, lat_col: str, lng_col: str, bounds: dict, codes: dict) -> dict | None:
    lat = dms_to_deg(row.get(lat_col, ""), False)
    lng = dms_to_deg(row.get(lng_col, ""), True)
    if lat is None or lng is None:
        return None
    if not (bounds["minLat"] <= lat <= bounds["maxLat"] and bounds["minLng"] <= lng <= bounds["maxLng"]):
        return None

    content_col = find_col(list(row.keys()), "事故内容", "事故の内容")
    content = row.get(content_col or "", "").strip()
    severity = "unknown"
    if content in ("1", "01", "死亡"):
        severity = "fatal"
    elif content in ("2", "02", "負傷"):
        severity = "injury"

    hour_col = find_col(list(row.keys()), "発生日時　　時", "発生日時  時", "発生時刻　　時")
    hour = None
    if hour_col and row.get(hour_col, "").strip().isdigit():
        hour = int(row[hour_col].strip())

    type_col = find_col(list(row.keys()), "事故類型")
    type_code = row.get(type_col or "", "").strip().zfill(2) if type_col else ""
    type_label = label(codes.get("accidentType", {}), type_code)
    category = accident_category(type_code)

    road_col = find_col(list(row.keys()), "道路形状")
    road_code = row.get(road_col or "", "").strip().zfill(2) if road_col else ""
    road_label = label(codes.get("roadShape", {}), road_code)

    pa_col = find_col(list(row.keys()), "当事者種別（当事者A）", "当事者種別")
    pb_col = find_col(list(row.keys()), "当事者種別（当事者B）")
    party_a = label(codes.get("partyType", {}), row.get(pa_col or "", "").strip().zfill(2))
    party_b = label(codes.get("partyType", {}), row.get(pb_col or "", "").strip().zfill(2)) if pb_col else ""

    return {
        "lat": lat, "lng": lng, "severity": severity, "hour": hour,
        "typeCode": type_code, "typeLabel": type_label, "category": category,
        "roadCode": road_code, "roadLabel": road_label,
        "partyA": party_a, "partyB": party_b,
    }


def grid_key(lat: float, lng: float) -> str:
    return f"{round(lat / GRID) * GRID:.5f},{round(lng / GRID) * GRID:.5f}"


def band_for_hour(h: int | None) -> str | None:
    if h is None:
        return None
    for lo, hi, key, _ in HOUR_BANDS:
        if lo <= hi:
            if lo <= h < hi:
                return key
        elif h >= lo or h < hi:
            return key
    return None


def build_hints(cluster: dict, year_from: str, year_to: str) -> list[str]:
    hints = []
    total = cluster["total"]
    if total == 0:
        return hints
    period = year_from if year_from == year_to else f"{year_from}〜{year_to}"
    hints.append(f"この付近（約50m圏内）では {period} 年に交通事故が {total} 件記録されています（教習エリア内の集計）。")
    if cluster["fatal"] > 0:
        hints.append(f"うち死亡事故が {cluster['fatal']} 件あります。十分な減速と左右・進路の確認を。")
    if cluster["injury"] > 0 and cluster["injury"] >= max(2, total // 2):
        hints.append(f"負傷事故が {cluster['injury']} 件と多めです。交差点手前では早めに減速しましょう。")

    top_band = max(cluster["hourBands"].items(), key=lambda x: x[1], default=(None, 0))
    if top_band[1] >= 2:
        label = next((lbl for lo, hi, k, lbl in HOUR_BANDS if k == top_band[0]), top_band[0])
        hints.append(f"発生が多い時間帯: {label}（{top_band[1]} 件）。")

    if cluster.get("partyPed", 0) >= 2:
        hints.append("歩行者関連の記録が複数あります。横断歩道・路側では必ず歩行者優先で。")
    if cluster.get("partyBike", 0) >= 2:
        hints.append("自転車関連の記録があります。車線の右端と自転車に注意。")

    types = cluster.get("typeCounts") or {}
    if types:
        top = sorted(types.items(), key=lambda x: -x[1])[:3]
        hints.append("事故の種類: " + "、".join(f"{k} {v}件" for k, v in top) + "。")
    roads = cluster.get("roadCounts") or {}
    if roads:
        top = sorted(roads.items(), key=lambda x: -x[1])[:2]
        hints.append("道路の状況: " + "、".join(f"{k} {v}件" for k, v in top) + "。")
    parties = cluster.get("partyCounts") or {}
    if parties:
        top = sorted(parties.items(), key=lambda x: -x[1])[:3]
        hints.append("関係する当事者: " + "、".join(f"{k} {v}件" for k, v in top) + "。")

    hints.append("※過去の統計であり、現在の危険度を保証するものではありません。")
    return hints


def top_counts(counter: dict, n: int = 4) -> dict:
    return dict(sorted(counter.items(), key=lambda x: -x[1])[:n])


def summarize_cluster(c: dict) -> str:
    parts = []
    if c.get("typeCounts"):
        k = next(iter(sorted(c["typeCounts"].items(), key=lambda x: -x[1])))
        parts.append(k[0])
    if c.get("roadCounts"):
        k = next(iter(sorted(c["roadCounts"].items(), key=lambda x: -x[1])))
        parts.append(k[0])
    if c.get("partyCounts"):
        k = next(iter(sorted(c["partyCounts"].items(), key=lambda x: -x[1])))
        parts.append(f"当事者:{k[0]}")
    return " · ".join(parts) if parts else "交通事故記録あり"


def aggregate(points: list[dict], year_from: str, year_to: str) -> list[dict]:
    buckets: dict[str, dict] = {}
    for p in points:
        key = grid_key(p["lat"], p["lng"])
        if key not in buckets:
            gx, gy = key.split(",")
            buckets[key] = {
                "id": f"c_{gx.replace('.', '')}_{gy.replace('.', '')}",
                "lat": float(gx),
                "lng": float(gy),
                "total": 0,
                "fatal": 0,
                "injury": 0,
                "hourBands": defaultdict(int),
                "partyPed": 0,
                "partyBike": 0,
                "typeCounts": defaultdict(int),
                "roadCounts": defaultdict(int),
                "partyCounts": defaultdict(int),
            }
        c = buckets[key]
        c["total"] += 1
        if p["severity"] == "fatal":
            c["fatal"] += 1
        elif p["severity"] == "injury":
            c["injury"] += 1
        b = band_for_hour(p["hour"])
        if b:
            c["hourBands"][b] += 1
        cat = p.get("category") or "その他"
        c["typeCounts"][cat] += 1
        if p.get("roadLabel"):
            c["roadCounts"][p["roadLabel"]] += 1
        for party in (p.get("partyA"), p.get("partyB")):
            if party:
                c["partyCounts"][party] += 1
                if party == "歩行者":
                    c["partyPed"] += 1
                if party in ("自転車", "原付", "二輪"):
                    c["partyBike"] += 1

    clusters = []
    for c in buckets.values():
        c["hourBands"] = dict(c["hourBands"])
        c["typeCounts"] = top_counts(dict(c["typeCounts"]))
        c["roadCounts"] = top_counts(dict(c["roadCounts"]))
        c["partyCounts"] = top_counts(dict(c["partyCounts"]))
        c["summary"] = summarize_cluster(c)
        c["hints"] = build_hints(c, year_from, year_to)
        c["radiusM"] = 50
        clusters.append(c)
    clusters.sort(key=lambda x: -x["total"])
    return clusters


def download_csv(url: str, dest: Path) -> Path:
    print(f"Downloading {url} ...")
    urllib.request.urlretrieve(url, dest)
    return dest


def read_csv(path: Path, bounds: dict, codes: dict) -> list[dict]:
    points = []
    with open(path, encoding="shift_jis", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        lat_col = find_col(headers, "地点　緯度（北緯）_10進数", "地点_緯度（北緯）_10進数", "地点　緯度（北緯）")
        lng_col = find_col(headers, "地点　経度（東経）_10進数", "地点_経度（東経）_10進数", "地点　経度（東経）")
        if not lat_col or not lng_col:
            raise RuntimeError(f"緯度経度列が見つかりません: {headers[:8]}...")
        for row in reader:
            p = parse_row(row, lat_col, lng_col, bounds, codes)
            if p:
                points.append(p)
    return points




def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, help="単一年の本票CSV（--yearsより優先）")
    parser.add_argument("--year", default="2023", help="単一年モード（--csv未指定時）")
    parser.add_argument("--years", default="2021,2022,2023", help="複数年をカンマ区切りで集計")
    args = parser.parse_args()

    bounds, center = load_bounds()
    codes = load_codes()
    years: list[str] = []

    if args.csv:
        points = read_csv(args.csv, bounds, codes)
        years = [args.year]
    else:
        years = [y.strip() for y in args.years.split(",") if y.strip()]
        if len(years) == 1 and args.year not in years:
            years = [args.year]
        points = []
        for year in years:
            try:
                cache = ROOT / "scripts" / f"honhyo_{year}.csv"
                if not cache.exists():
                    url = f"https://www.npa.go.jp/publications/statistics/koutsuu/opendata/{year}/honhyo_{year}.csv"
                    download_csv(url, cache)
                points.extend(read_csv(cache, bounds, codes))
            except Exception as e:
                print(f"Skip {year}: {e}", file=sys.stderr)

    if not points:
        print("No accident points; writing empty dataset.", file=sys.stderr)
        years = years or [args.year]

    year_from = min(years)
    year_to = max(years)
    clusters = aggregate(points, year_from, year_to)
    meta = {
        "source": "警察庁交通事故統計オープンデータ（本票）",
        "sourceUrl": "https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html",
        "year": year_to,
        "yearFrom": year_from,
        "yearTo": year_to,
        "years": years,
        "bounds": bounds,
        "center": center,
        "clusterCount": len(clusters),
        "totalAccidents": len(points),
        "generatedAt": __import__("datetime").date.today().isoformat(),
        "clusters": clusters,
        "disclaimer": "過去の統計データです。現在の危険度を保証しません。個別事故の詳細は表示しません。",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(clusters)} clusters ({len(points)} points, {year_from}-{year_to}) -> {OUT}")


if __name__ == "__main__":
    main()

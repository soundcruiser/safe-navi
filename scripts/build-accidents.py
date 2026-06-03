#!/usr/bin/env python3
"""
警察庁交通事故統計オープンデータ（本票CSV）を教習エリア内でクリップし、
交差点クラスタへ集計して data/toyota-chuo/accidents.json を生成する。

使い方:
  python3 scripts/build-accidents.py
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


def parse_row(row: dict, lat_col: str, lng_col: str, bounds: dict) -> dict | None:
    lat = dms_to_deg(row.get(lat_col, ""), False)
    lng = dms_to_deg(row.get(lng_col, ""), True)
    if lat is None or lng is None:
        return None
    if not (bounds["minLat"] <= lat <= bounds["maxLat"] and bounds["minLng"] <= lng <= bounds["maxLng"]):
        return None

    content_col = find_col(list(row.keys()), "事故内容", "事故の内容")
    content = row.get(content_col or "", "").strip()
    severity = "unknown"
    if content in ("1", "死亡"):
        severity = "fatal"
    elif content in ("2", "負傷"):
        severity = "injury"

    hour_col = find_col(list(row.keys()), "発生日時　　時", "発生日時  時", "発生時刻　　時")
    hour = None
    if hour_col and row.get(hour_col, "").strip().isdigit():
        hour = int(row[hour_col].strip())

    party_col = find_col(list(row.keys()), "当事者種別", "当事者種別（当事者1）")
    party = row.get(party_col or "", "").strip()

    return {"lat": lat, "lng": lng, "severity": severity, "hour": hour, "party": party}


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


def build_hints(cluster: dict) -> list[str]:
    hints = []
    total = cluster["total"]
    if total == 0:
        return hints
    hints.append(f"この付近（約50m圏内）では集計期間中に交通事故が {total} 件記録されています。")
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

    hints.append("※過去の統計であり、現在の危険度を保証するものではありません。")
    return hints


def aggregate(points: list[dict]) -> list[dict]:
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
        party = p.get("party") or ""
        if party in ("3", "4", "歩行者"):
            c["partyPed"] += 1
        if party in ("5", "6", "自転車"):
            c["partyBike"] += 1

    clusters = []
    for c in buckets.values():
        c["hourBands"] = dict(c["hourBands"])
        c["hints"] = build_hints(c)
        c["radiusM"] = 50
        clusters.append(c)
    clusters.sort(key=lambda x: -x["total"])
    return clusters


def download_csv(url: str, dest: Path) -> Path:
    print(f"Downloading {url} ...")
    urllib.request.urlretrieve(url, dest)
    return dest


def read_csv(path: Path, bounds: dict) -> list[dict]:
    points = []
    with open(path, encoding="shift_jis", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        lat_col = find_col(headers, "地点　緯度（北緯）_10進数", "地点_緯度（北緯）_10進数", "地点　緯度（北緯）")
        lng_col = find_col(headers, "地点　経度（東経）_10進数", "地点_経度（東経）_10進数", "地点　経度（東経）")
        if not lat_col or not lng_col:
            raise RuntimeError(f"緯度経度列が見つかりません: {headers[:8]}...")
        for row in reader:
            p = parse_row(row, lat_col, lng_col, bounds)
            if p:
                points.append(p)
    return points


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, help="本票CSVのローカルパス")
    parser.add_argument("--year", default="2023", help="ダウンロードする年")
    args = parser.parse_args()

    bounds, center = load_bounds()
    cache = ROOT / "scripts" / f"honhyo_{args.year}.csv"

    if args.csv:
        csv_path = args.csv
    elif cache.exists():
        csv_path = cache
    else:
        url = f"https://www.npa.go.jp/publications/statistics/koutsuu/opendata/{args.year}/honhyo_{args.year}.csv"
        try:
            csv_path = download_csv(url, cache)
        except Exception as e:
            print(f"Download failed: {e}", file=sys.stderr)
            print("Generating minimal placeholder from bounds center.", file=sys.stderr)
            clusters = []
            OUT.parent.mkdir(parents=True, exist_ok=True)
            meta = {
                "source": "警察庁交通事故統計オープンデータ（未取得）",
                "year": args.year,
                "bounds": bounds,
                "center": center,
                "clusterCount": 0,
                "totalAccidents": 0,
                "generatedAt": __import__("datetime").date.today().isoformat(),
                "clusters": [],
                "disclaimer": "過去の統計データです。現在の危険度を保証しません。",
            }
            OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return

    print(f"Reading {csv_path} ...")
    points = read_csv(csv_path, bounds)
    clusters = aggregate(points)
    meta = {
        "source": "警察庁交通事故統計オープンデータ（本票）",
        "sourceUrl": "https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html",
        "year": args.year,
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
    print(f"Wrote {len(clusters)} clusters ({len(points)} points) -> {OUT}")


if __name__ == "__main__":
    main()

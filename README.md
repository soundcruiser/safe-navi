# SAFENAVI（教習版）

トヨタ中央自動車学校周辺向けの **出発前ルート予習** ツールです。曲がりの目印と、警察庁オープンデータに基づく交差点付近の事故傾向を確認し、運転中は Google マップでナビします。

## 教室での使い方（3ステップ）

1. **定番ルート** を選ぶか、出発地・目的地を入力して「ルートを調べる」
2. 左の **曲がりリスト** または **順番に確認** で、目印と事故注意を確認
3. 運転時は **Googleマップで本番ナビ**（判断はナビに任せる）

## ローカル起動

```bash
cd safe-navi
python3 -m http.server 8765
```

ブラウザで http://localhost:8765/safe-navi.html を開く（`file://` では動きません）。

## 公開URL（GitHub Pages）

`master` ブランチへ push 後、Actions でデプロイされます。

- https://soundcruiser.github.io/safe-navi/
- 他校パック（将来）: `?school=toyota-chuo`

## データ更新（事故統計）

```bash
python3 scripts/build-accidents.py --year 2023
# またはローカルCSVを指定
python3 scripts/build-accidents.py --csv scripts/honhyo_2023.csv
```

出力: `data/toyota-chuo/accidents.json`  
元データ: [警察庁 交通事故統計オープンデータ](https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html)

## 教習所パックの編集

`data/toyota-chuo/school-pack.json`

- `presets`: 定番ルート
- `landmarks`: 座標キー `"lat,lng"`（小数4桁）ごとの目印
- `intersectionNotes`: 事故クラスタ `id` への指導員コメント
- `destinationHints`: 到着前の一言

## 免責

表示される事故情報は **過去の統計** です。現在の危険度を保証するものではありません。個別事故の詳細は表示しません。

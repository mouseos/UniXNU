# read-batch比較の解析

`scripts/analyze-read-batch.py` はa04br3側のcollectorが保存した各初回boot、
flash記録、baseline/batchペアmanifestを読み、機器に接続せずJSONを出力する。
次の例では、captureディレクトリはplanファイルからの相対パスでも指定できる。

```json
{
  "pairs": [
    {
      "pid": 1,
      "report": 1,
      "order": "baseline-first",
      "order_evidence": "両flash記録と時刻の参照",
      "baseline": {
        "capture": "baseline-capture",
        "capture_sha256": "各capture.jsonのSHA-256",
        "conditions": {
          "uart_integrity": {"verified": true, "evidence": "完全性を判断した記録への参照"},
          "timing_quiescent": {"verified": true, "evidence": "report時の未完了処理がないと判断した根拠"},
          "crash_free": {"verified": true, "evidence": "ログと外部観測に基づく根拠"},
          "storage_provider": {"verified": true, "evidence": "計時providerの動作根拠"},
          "following_reset": {"expected_reason": 4, "evidence": "後続リセットの実施記録"},
          "cache": {"state": "warm", "evidence": "キャッシュ条件の根拠"}
        }
      },
      "batch": {
        "capture": "batch-capture",
        "capture_sha256": "各capture.jsonのSHA-256",
        "conditions": {
          "uart_integrity": {"verified": true, "evidence": "完全性を判断した記録への参照"},
          "timing_quiescent": {"verified": true, "evidence": "report時の未完了処理がないと判断した根拠"},
          "crash_free": {"verified": true, "evidence": "ログと外部観測に基づく根拠"},
          "storage_provider": {"verified": true, "evidence": "計時providerの動作根拠"},
          "following_reset": {"expected_reason": 4, "evidence": "後続リセットの実施記録"},
          "cache": {"state": "warm", "evidence": "キャッシュ条件の根拠"}
        }
      }
    }
  ]
}
```

```sh
python3 scripts/analyze-read-batch.py --plan /path/to/plan.json --manifest /path/to/pair.json
```

例中の条件は入力形式を示すもので、実際の状態を保証しない。根拠がない条件は
省略するか `verified: false`、cacheは `unknown` とする。各captureのflash記録、
ログハッシュと最初・次bootの境界、panicとBOOT_REASONを照合し、固定sourceと
boot hashをmanifestに照合する。次preloaderがまだない初回bootは未閉鎖として
比較対象外。PID 1以外は条件に `expected_comm` を指定する。後続bootのpanicや
BOOT_REASONは初回とは別に出す。

RSTはq=1または2の指定PID・unique IDごとに6行全てを要求し、不正・欠損・
重複や曖昧なroot timing begin/endを除外する。baseline `bat=0`、batch
`bat=pc>0`、署名・準備エラーと再利用が0、要求バイト `rb=pb>0`、ペアの
`rb`・`pb`・`pc`・署名回数一致、cache条件一致を保守的な要件とする。
`pc` はno-opやエラーを含むので `bat!=pc` は必ずしもbatch故障ではないが、
この比較では全件選択を確認できないため除外する。`rb` は要求bytesであり、
媒体から実際に読んだbytesではない。

異なるbootを使い、順序を交互にした3組以上の条件付き適格ペアについて
`RST prep` の `pn` のbatch/baseline比の中央値と最大を計算する。中央値0.95
以下かつ最大1.10以下は事前閾値への一致を示すだけで、統計的な効果や因果を
証明しない。3組未満は `meets_predeclared_threshold: null` で判定不能。
全結果の `conclusion` は `conditional_exploratory_only` とする。

RSTは累積・非原子的な限られたsnapshotで、未完了処理の一部が混ざり得る。
UART完全性、report時の静穏、cache状態、順序は外部の記録を必要とし、解析器が
証明するのではない。RSTに含まれないcoalescing待機や物理I/Oを推測しない。
`pn` は集計wall timeで、排他的なCPU時間でもない。ADTのrandom-seedも両bootで
異なる。これらの限界と、plan・manifestのSHA-256を出力に含める。

入力planの `capture_sha256` は事前に固定したcapture.jsonのSHA-256とし、
collectorのcheckpoint、flash成功申告と完了offset、boot-argsの完全一致を確認する。
これらは実際に書かれたイメージの暗号学的証明ではなく、外部記録を前提とする。
flash完了後かつ初回preloader前のpanic/EL3は帰属不明として除外する。初回の
panicと次回のpanicは分離し、次回BOOT_REASON=9はwatchdog候補として除外する。
予定されたwatchdogであっても自動的には区別できない。後続起動の理由と実施記録が
なければ適格としない。panic検索は候補検出で完全なクラッシュ検出ではない。

root timingのread/verifyの8項目が欠落した場合は除外し、出力に値を保存する。
provider動作の外部根拠も必要で、ゼロ値は計測できた証明ではない。read_nsなどは
その区間の集計であり個々の待機時間を分離できない。待機時間は未計測であり、
ゼロとして扱わない。prepのhitは署名準備のcoalescing再利用であり、ファイルシステム
キャッシュのhitではない。

初回および後続bootの起動理由が複数で矛盾する場合、後続bootにもpanic/EL3候補が
ある場合は、初回の異常とは分けて表示し、ペアを除外する。collectorが境界未観測の
生ログを保存した場合、解析器は初回bootがない旨で停止する。明らかな改ざん・
ファイル不一致など入力の破損時も解析全体を停止し、出力された比を信用しない。

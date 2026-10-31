# Suno-Beat

（ゲーム画面上の仮タイトルは「STEM.BEAT」）
Sunoで作った曲を、パート分離して自動で譜面にし、ブラウザで遊べる音楽ゲームにするプロジェクト。
スマホ（横持ち）とPCで遊べる。画面の奥から譜面が迫ってくる4レーン方式。

## 仕組み

1. **曲を取ってくる**：Suno MCPでWAVをダウンロード（ダウンロード枠を1つ使う）
2. **パート分離**：Demucs（`htdemucs`の4パート版）でドラム／ベース／その他／ボーカルに分ける
3. **譜面生成**：`pipeline/chart.py`
   - ビートを推定し、実際のドラムの立ち上がりに合わせてずれを補正（実測でほぼ6ms以内）
   - ドラムを低音と中音の比率でキック／スネアに分け、高音でハイハットを拾う
   - ギターは「音の鳴り始め」と「コードが変わった瞬間」の両方から拾う
   - 難易度ごとの目標密度（EASY 1.8 / NORMAL 3.5 / HARD 5.5 ノーツ毎秒）に自動で合わせる
4. **遊ぶ**：`web/`（元のミックスをそのまま再生し、タップすると効果音が鳴る）

レーン：KICK / SNARE / HAT / GUITAR（PCのキーはD F J K）。ボーカルはレーンにしない方針。

## フォルダ

| 場所 | 中身 |
|---|---|
| `web/` | ゲーム本体（今は1曲分：index.html, chart.json, mix.mp3） |
| `songs/<slug>/` | 曲ごとの譜面と音源 |
| `pipeline/` | 分離と譜面生成のスクリプト |
| `tests/play_test.js` | Playwrightで縦持ち・横持ち・PCを自動プレイして確認するテスト |

## 曲を追加する

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r pipeline/requirements.txt
pipeline/build_song.sh path/to/song.wav my-song "My Song"
```

## 次にやること

- 曲選択画面（今は1曲固定）
- 譜面を手で直せるエディタ
- iPhone実機での遅延調整
- 公開先をVercelに
- いずれ：声ネタを「押した時だけ鳴る」専用レーンに

## 収録曲

- Too Loud to Die（184.6 BPM, Suno v6）

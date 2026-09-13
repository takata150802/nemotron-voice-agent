# CPU ローカル音声対話エージェント

[NVIDIA Nemotron Voice Agent](https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent) の Pipecat pipeline とブラウザクライアントを再利用する CPU-only fork です。Ubuntu サーバ上の NeMo-Speech.cpp、llama.cpp、VOICEVOX ENGINE を接続し、Windows の Chrome / Edge から WebRTC で日本語音声対話を行います。

内部推論サービスはループバックに限定します。CPU 構成にクラウド API キーは不要です。モデルとソフトウェアの事前取得にはインターネットを使用できます。

```text
Windows Chrome / Edge (マイク・スピーカー)
                 ↕ WebRTC
Ubuntu: Nemotron Voice Agent / Pipecat
  ├─ ASR: NeMo-Speech.cpp / Nemotron 3.5 ASR Streaming 0.6B
  ├─ LLM: llama.cpp / gpt-oss-20b Q4_K_M
  └─ TTS: VOICEVOX ENGINE / 日本語 / CPU
```

[CPU ローカル構成ガイド](docs/how-to/cpu-local.md) に、ビルド、モデル取得、設定、起動、Windows 接続、マイク権限、ファイアウォール、性能測定、およびトラブルシューティングを記載しています。[実装前の調査記録](docs/cpu-research.md) に API と置換方針を記載しています。

この作業環境では `.env`、モデル、CPU バイナリ、および client build を準備済みです。下記の起動コマンドから使用できます。検証サービスは終了しています。新しい環境では次の順で準備してください。既存の `.env` は上書きせず、CPU 設定を確認して統合してください。

```bash
test -f .env || cp .env.example .env
bash scripts/setup_python.sh
npm --prefix client ci
npm --prefix client run build
bash scripts/setup_nemo_speech.sh
bash scripts/setup_llama.sh
```

モデルパスと VOICEVOX ENGINE の起動パスを `.env` に設定した後、別々のターミナルから起動します。

```bash
bash scripts/run_nemo_speech.sh
bash scripts/run_llama.sh
bash scripts/run_tts.sh
```

最後にサービスを確認してエージェントを起動します。

```bash
bash scripts/check_services.sh
bash scripts/run_voice_agent.sh
```

対象と同じ i7-10700KF で CPU build、実モデルの日本語 ASR、Q4_K_M LLM、VOICEVOX、および Chromium 151 の双方向 WebRTC を確認しました。日本語の入力と応答を取得し、外部 route をブロックしたブラウザ smoke で page error はありません。既存 latency observer の値は、この sample で 6.490 s です。

VOICEVOX は文単位の WAV 合成です。Pipecat の sentence aggregation により LLM 全文を待たずに合成しますが、モデルから waveform を逐次取得する方式ではありません。Windows の実マイク、LAN 接続、音響品質、および長時間の割り込み動作は追加検証が必要です。[詳しい検証結果と probe 手順](docs/how-to/cpu-local.md) を参照してください。

元の cloud / workstation / DGX Spark / Jetson Thor 構成は維持しています。これらの upstream 向け手順は [元の README](README.upstream.md) と [既存ドキュメント](docs/01-getting-started.md) を参照してください。CPU 構成では元の NIM / GPU 手順を実行しません。

upstream の全 git 履歴を継承しています。fork 元は [d93ce3ed](https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent/commit/d93ce3ed7a635fac3cf39f7f88888c809298cb8d) で、固定 tag `upstream-base` が指します。CPU 実装の差分は `git diff upstream-base..HEAD` で確認できます。[Upstream 追従手順](docs/how-to/cpu-local.md#upstream-追従) を参照してください。

# CPU ローカル構成ガイド

Docker 配布と更新の手順は、[CPU Docker デプロイ](cpu-docker.md) を参照してください。

## アーキテクチャと変更方針

この fork は Ubuntu 24.04.1 LTS、x86_64、Intel Core i7-10700KF を対象にします。GPU と CUDA は推論に使用しません。Windows はブラウザだけを使用します。

既存の Nemotron Voice Agent を fork する理由は、WebRTC transport、マイク入力、スピーカー出力、会話履歴、voice activity detection (VAD)、割り込み、セッション管理、および metrics を再利用するためです。独自の WebSocket 会話 framework は追加しません。

CPU の変更は backend adapter、CPU 設定、および起動スクリプトに限定します。generic pipeline の CPU 分岐で STT と TTS を差し替え、large language model (LLM) は既存の OpenAI-compatible service を使います。元の GPU / cloud deployment profile は維持します。[調査記録](../cpu-research.md) に参照した upstream revision と API を記載しています。

内部接続は以下の構成です。

| サービス | 役割 | 接続先 |
| --- | --- | --- |
| NeMo-Speech.cpp | Nemotron 3.5 ASR Streaming 0.6B | `ws://127.0.0.1:8081/v1/realtime` |
| llama.cpp | gpt-oss-20b Q4_K_M | `http://127.0.0.1:8080/v1` |
| VOICEVOX ENGINE | CPU 日本語 TTS | `http://127.0.0.1:50021` |
| Voice Agent | ブラウザ配信と WebRTC signaling | Ubuntu の TCP `7860` |

Windows から ASR、LLM、および TTS のポートに直接接続する必要はありません。

## ソフトウェアの準備

すべてのコマンドをリポジトリルートで実行します。C/C++ build toolchain、CMake、Ninja、Git、curl、Python、および Node.js を用意してください。Python 3.12 または 3.13 と Node.js 20.19 以上（または 22.12 以上）を使用してください。古い Node.js では Vite の engine 警告が出ます。Python のバージョンと依存関係は `pyproject.toml` と `uv.lock`、クライアントの依存関係は `client/package.json` と lockfile を参照します。

Python セットアップは既存の lockfile で runtime を準備し、ブラウザも build します。cloud / GPU profile の互換依存は保持しますが、CPU 起動では使用しません。

```bash
bash scripts/setup_python.sh
npm --prefix client ci
npm --prefix client run lint
npm --prefix client run build
```

セットアップは `scripts/setup_tokenizer.py` で、checksum を確認した NLTK `punkt_tab` を `.models/nltk` に事前取得します。起動時は asset がないと Pipecat import 前に停止します。Silero VAD は同梱ローカルモデルを使用します。初回起動時の cache miss による download がないことを、オフライン起動で確認します。GPU 向け `.env` がある場合は、そのまま CPU 起動に使わないでください。新しい環境だけで以下を実行します。

```bash
cp .env.example .env
```

既存の `.env` は保存し、必要な CPU キーを `.env.example` から統合してください。upstream 向け例は `.env.upstream.example` です。

## NeMo-Speech.cpp の CPU Build

公式 `cpu-server` preset を使用します。スクリプトは調査済み revision を取得して CPU server を build します。`NEMO_SOURCE_DIR` と `NEMO_REVISION` で配置と revision を変更できます。

```bash
bash scripts/setup_nemo_speech.sh
```

公式 build の主要な手順は以下です。スクリプトが取得した NeMo-Speech.cpp のディレクトリで実行する処理に対応します。

```bash
scripts/configure.sh cpu-server
cmake --build --preset cpu-server
```

CUDA preset、GPU runtime container、および Python NeMo / PyTorch ASR を使いません。NeMo server 起動時は `asr.backend.gpu=-1` を明示します。

## 日本語 ASR モデルの取得

公式 repo は [nvidia/nemotron-3.5-asr-streaming-0.6b](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) です。公式索引の GGUF は `nemotron-3.5-asr-streaming-0.6b.q8_0.gguf` です。Python checkpoint ではなく GGUF を使用します。

公式配布ファイルを、推論開始前に取得します。

```bash
mkdir -p .models
curl -L --fail --retry 3 -o .models/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf \
  https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b/resolve/main/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf
```

検証したファイルの SHA256 は `3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1` で、公式 Hugging Face LFS metadata と一致しました。配布ファイルは更新されるため、取得時の metadata も確認します。

build した `nemo-speech` の公式 pull コマンドも使用できます。ただし pinned source のモデル索引と配布側の checksum が異なる場合は、上記の直接取得と検証を使用してください。

```bash
/path/to/nemo-speech pull nemotron-3.5
```

`/path/to/nemo-speech` は build した実行ファイルのパスに置き換えます。pull が示したローカルファイルを確認し、`.env` の `NEMO_ASR_MODEL` に絶対パスを設定します。別ディレクトリに保存した GGUF も指定できます。推論起動にはモデル alias を使わず、ローカルファイルを使います。

`.env` の `NEMO_SPEECH_BIN` が実行ファイルを指定します。既定は `.build/NeMo-Speech.cpp/build/cpu-server/bin/nemo-speech` です。`NEMO_ASR_LANGUAGE=ja-JP` で日本語を指定します。

adapter は 16,000 Hz、mono、little-endian PCM16 を送信します。日本語 locale を設定し、automatic punctuation を有効にします。言語指定が対象モデル revision で受理されることと、日本語音声を認識できることを実モデルで確認してください。

次のスクリプトを起動し、そのターミナルを開いたままにします。

```bash
bash scripts/run_nemo_speech.sh
```

`/v1/realtime` は ASR-only server での互換 alias です。VoiceChat モデルを同じ server にロードすると protocol が変わります。ASR と VoiceChat を混在させないでください。

## llama.cpp の CPU Build とモデル配置

次のスクリプトで CPU build を準備します。`LLAMA_SOURCE_DIR` と `LLAMA_REVISION` で配置と revision を変更できます。

```bash
bash scripts/setup_llama.sh
```

CPU build では CUDA と GPU backend を無効にします。実行時も `--n-gpu-layers 0` を指定します。`llama-server` の正式な flags は [Server Documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) を参照します。

gpt-oss-20b の Q4_K_M GGUF を事前取得し、ローカルファイルを配置します。`.env` の `LLM_MODEL_PATH` に、実ファイルの絶対パスを指定してください。ファイル名だけで量子化方式を判断せず、配布元の metadata と GGUF のモデル情報を確認してください。MXFP4 や別の量子化モデルで置き換えて要件を満たした扱いにしません。

`LLAMA_BIN` の既定は `.build/llama.cpp/build/bin/llama-server` です。起動スクリプトは GGUF metadata の `general.architecture=gpt-oss`、`general.file_type=15`（Q4_K_M）、および `gpt-oss.block_count=24` を確認します。

元モデルは [OpenAI gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) です。第三者の Q4_K_M 変換ファイルを使う場合は、変換元、量子化方式、ライセンス、および checksum を確認します。元の checkpoint とローカル GGUF は同じファイル形式ではありません。今回の実モデル検証には [unsloth/gpt-oss-20b-GGUF](https://huggingface.co/unsloth/gpt-oss-20b-GGUF) の `gpt-oss-20b-Q4_K_M.gguf` を使用しました。事前取得の例です。

```bash
mkdir -p .models
curl -L --fail --retry 3 -o .models/gpt-oss-20b-Q4_K_M.gguf \
  https://huggingface.co/unsloth/gpt-oss-20b-GGUF/resolve/main/gpt-oss-20b-Q4_K_M.gguf
```

検証したファイルの SHA256 は `c27536640e410032865dc68781d80a08b98f8db5e93575919af8ccc0568aeb4f` です。

次のスクリプトでローカル server を起動します。

```bash
bash scripts/run_llama.sh
```

接続先は `http://127.0.0.1:8080/v1/chat/completions` です。既存 Pipecat service が `stream=true` を使います。SDK が要求する dummy key は adapter 内で設定します。API キーの環境設定は不要です。Pipecat 1.5.0 は渡された `http_client` を使用しないため、`LocalOpenAILLMService` が client 生成と cleanup だけを変更し、`trust_env=False` で外部 proxy を使わせません。streaming と response parser は既存実装のままです。

gpt-oss の Harmony template は llama.cpp が処理します。Jinja template と reasoning parser を使い、reasoning を `reasoning_content` に分離します。音声に渡すのは final assistant の `content` だけです。`--reasoning-format none` は reasoning を content に残すため使用しません。

## TTS の選定とセットアップ

VOICEVOX ENGINE は日本語音声と CPU 実行に対応し、ローカル HTTP API を提供します。[公式 ENGINE](https://github.com/VOICEVOX/voicevox_engine) の Linux CPU 対応配布物を、モデルと辞書を含めて事前取得してください。ENGINE の公開ライセンスと、使用する話者の利用規約を確認します。話者によってクレジットなどの条件が異なります。

公式 0.25.2 の Linux CPU x64 `.7z` または `.vvpp` 配布物を展開し、ENGINE の `run` 実行ファイルを `VOICEVOX_BIN` に絶対パスで指定します。`.vvpp` も 7z 形式として展開できます。起動スクリプトは `VV_USE_GPU=0` に設定し、GPU flag を渡しません。current master は `--no-use_gpu` を提供しますが、公式 0.25.2 CPU release は提供しません。スクリプトは `--help` を確認し、対応している binary にだけ `--no-use_gpu` を渡します。`TTS_THREADS` は正式な `--cpu_num_threads` に渡します。`TTS_VOICE_ID` はローカル `/speakers` に存在する ID を選びます。既定は `3` です。

次のスクリプトで ENGINE を起動します。

```bash
bash scripts/run_tts.sh
```

adapter は `/audio_query` と `/synthesis` を呼び、WAV を PCM frame に変換します。VOICEVOX は 1 文の WAV が完成してから返します。Pipecat が LLM token を文単位で集約するため、LLM 全文生成完了を待たずに TTS を始められます。ただし waveform をモデルから逐次取得する真の streaming TTS ではありません。短い日本語応答を使い、最初の文の合成時間を測定してください。

TTSService abstraction は維持しています。別の日本語 CPU backend を導入する場合も、この abstraction を使用してください。

## VAD、発話終了、および割り込み

CPU 構成は Pipecat の既存 Silero VAD を使用します。Smart Turn と NeMo endpointing を無効にし、発話終了の責務を VAD に集約します。VAD stop に対応して adapter が `input_audio_buffer.commit` を送り、ASR final を待って会話を進めます。

`NEMO_ASR_PREROLL_MS=800` は VAD start 前の音声を adapter が保持する時間です。設定可能範囲は 200〜2,000 ms です。短すぎると最初の音節が欠けるため、初期値は 800 ms とします。これは fork の adapter 設定で、公式 NeMo option ではありません。

partial transcript は表示や測定に使用し、未確定文字列で新しい LLM 応答を開始しません。barge-in と出力停止は既存 Pipecat pipeline が扱います。ネットワーク切断後は新しい ASR connection を作ります。失われた音声を重複再送して会話を続けた扱いにはしません。実モデルで、話している途中の短い沈黙、長い沈黙、連続発話、および応答中の割り込みを確認してください。

## サービス確認とエージェント起動

各スクリプトの責務は以下のとおりです。

| スクリプト | 責務 |
| --- | --- |
| `setup_python.sh` | CPU 用 Python runtime の準備 |
| `setup_nemo_speech.sh` | 公式 NeMo-Speech.cpp の取得と CPU server build |
| `setup_llama.sh` | 公式 llama.cpp の取得と CPU server build |
| `run_nemo_speech.sh` | ローカル ASR GGUF を CPU でロード |
| `run_llama.sh` | ローカル Q4_K_M GGUF を CPU でロード |
| `run_tts.sh` | ローカル VOICEVOX ENGINE を CPU で起動 |
| `check_services.sh` | 各 backend の readiness と設定を確認 |
| `run_voice_agent.sh` | readiness 確認後に既存サーバを起動 |

モデルは git に追加しません。起動前に以下を実行してください。

```bash
bash scripts/check_services.sh
bash scripts/run_voice_agent.sh
```

NeMo は `/health` と `/ready`、llama.cpp は `/health`、VOICEVOX は `/version` などの provider API で確認します。HTTP 応答があることだけでなく、モデルが ready であることを確認してください。モデルロード中は起動を待つか、報告されたエラーを解消します。

## Windows ブラウザからの接続

`VOICE_AGENT_HOST` の既定は `0.0.0.0`、`VOICE_AGENT_PORT` の既定は `7860` です。`VOICE_AGENT_TLS_CERT` と `VOICE_AGENT_TLS_KEY` に信頼された証明書と鍵を設定できます。

Windows の Chrome または Edge で `https://<UbuntuのLANアドレス>:7860/` を開きます。Windows 側に Python は不要です。既存 UI で generic assistant と WebRTC を選び、接続します。マイクへのアクセス許可を選び、入力機器と出力機器を確認します。

ブラウザの `getUserMedia` は secure context を必要とします。別 PC の `http://<LANアドレス>` は通常、マイクを使用できません。Windows が信頼する証明書を使用してください。既存サーバの TLS options は次のとおりです。

```bash
bash scripts/run_voice_agent.sh --host 0.0.0.0 --tls-cert /path/to/cert.pem --tls-key /path/to/key.pem
```

証明書の Subject Alternative Name に接続する DNS 名または IP アドレスを含めます。開発用の自己署名証明書を使う場合は、発行元証明書を Windows の信頼ストアに登録してください。サーバが生成した自己署名証明書は、別 PC で自動的に信頼されるわけではありません。

マイク許可を拒否した場合は、ブラウザのサイト設定から許可を変更して再接続します。最初の診断はヘッドセットで行うと、スピーカーからマイクへの回り込みを減らせます。

## ネットワークとファイアウォール

同一 LAN で、Windows から Ubuntu の TCP `7860` に到達できることを確認します。WebRTC media は HTTP とは別の UDP 接続です。SmallWebRTC の ICE が選ぶ Ubuntu の UDP ポートにも到達できる必要があります。TCP ポートだけの開放では signaling が成功しても音声が流れないことがあります。

CPU モードの `/api/ice-servers` は空配列を返し、host candidate だけを使用します。現在の CPU モードは STUN / TURN の設定を使用しません。同一 LAN で Windows と Ubuntu が直接到達できる構成を使ってください。

LAN の Windows IP を許可元として限定してください。ASR の `8081`、LLM の `8080`、TTS の `50021` は公開しません。HTTP reverse proxy だけで WebRTC UDP を中継することはできません。異なる subnet や NAT を越える TURN 対応は、この CPU モードでは未実装です。[既存 TURN ガイド](enable-turn-server.md) は upstream profile 向けです。CPU モードで公開 STUN / TURN service を設定しません。

## 性能測定と調整

8 thread を 3 サービスすべてに割り当てると CPU が競合します。`.env.example` の ASR、LLM、および TTS の独立した thread 設定を使い、2 / 4 / 8 の比較を行ってください。設定の対応は以下のとおりです。

| 環境変数 | 既定 | 対応先 |
| --- | --- | --- |
| `NEMO_ASR_THREADS` | 2 | fork patch が追加した ggml compute thread 制御 |
| `NEMO_HTTP_THREADS` | 4 | 公式 `--http.threads` worker pool |
| `LLAMA_THREADS` | 4 | 公式 `--threads` |
| `LLAMA_THREADS_BATCH` | 4 | 公式 `--threads-batch` |
| `LLAMA_CTX_SIZE` | 4096 | 公式 `--ctx-size` |
| `TTS_THREADS` | 2 | 公式 VOICEVOX `--cpu_num_threads` |

NeMo の公式 revision は ASR scheduler の compute thread を 4 に固定し、独立した compute-thread CLI を提供しません。`patches/nemo-cpu-threads.patch` が既存 ggml thread API を使い、scheduler と cached/direct の両経路に `NEMO_ASR_THREADS` を追加します。この変数は公式 NeMo option ではありません。patch を適用しない公式 binary では効果がありません。setup は patch の適用確認に失敗すると停止します。

主要 KPI は End of User Speech → First Assistant Audio です。既存 Pipecat の user/bot latency observer と metrics に加え、adapter の timing log を使います。測定する項目は以下のとおりです。

| 区間 | 測定項目 |
| --- | --- |
| ASR | 入力音声時間、最初の partial までの時間、commit → final、処理時間 / 音声時間 |
| LLM | time to first token、prompt 処理時間、生成時間、tokens/sec |
| TTS | time to first audio、文の合成時間、合成時間 / 生成音声時間 |
| 全経路 | 最後のユーザー音声 → 最初の assistant 音声 |

リアルタイム係数 (RTF) は処理時間を音声時間で割ります。ASR の wall time にはライブ音声の到着待ちが含まれるため、offline benchmark と直接比較しません。LLM の prompt / generation 内訳と tokens/sec は llama.cpp の server timing も確認します。ASR は `asr_partial_latency` と `asr_final`、TTS は `tts_synthesis` の JSON log を出力します。TTS の文単位合成では first-audio と synthesis 時間は同じ区間です。adapter が出力しない値は、測定済みとして扱いません。

1 回の成功だけで性能を判断せず、同じ日本語音声、同じ conversation history、および同じ warmup 条件を使用します。LLM の context と最大生成長を小さくし、最初の文を短くすると、CPU の会話応答を調整しやすくなります。対象 CPU の結果を取得するまでは latency の保証値を掲載しません。

## トラブルシューティング

症状ごとに以下を確認してください。

| 症状 | 確認と対応 |
| --- | --- |
| ASR が ready にならない | GGUF パス、read permission、モデル revision、`gpu=-1`、server のエラーログを確認 |
| ASR 接続後に protocol error | VoiceChat がロードされていないことと、音声前の session 設定を確認 |
| 認識が日本語にならない | locale、Nemotron 3.5 モデル、入力 mono PCM16 の sample rate を確認 |
| 発話後に final が来ない | VAD stop と commit のログ、server endpointing 無効化、WebSocket の error を確認 |
| LLM が応答しない | `/health`、モデルパス、RAM、Q4_K_M metadata、CPU build を確認 |
| reasoning が読み上げられる | gpt-oss template、`--reasoning-format deepseek`、content と reasoning の分離を確認 |
| TTS が応答しない | ENGINE の `/version`、speaker ID、辞書と音声モデル、CPU mode を確認 |
| TTS の開始が遅い | 最初の文の長さ、合成時間、thread 競合を確認 |
| UI は開くがマイクが使えない | HTTPS の信頼、サイトのマイク権限、Windows のマイク privacy 設定を確認 |
| 接続するが音声がない | ICE candidate、UDP firewall、Windows の出力機器、LAN 到達性を確認 |
| 初回に外部 download が発生 | VAD/frontend asset とモデルを事前取得し、cache を維持してオフライン再検証 |

## 実サービスの Probe と検証結果

ASR、LLM、および TTS を起動し、次のコマンドを実行します。指定がなければ VOICEVOX が日本語サンプルを生成します。readiness、ASR partial / final、LLM reasoning / final、TTS 合成、および既存 Pipecat audio pipeline を確認します。

```bash
PYTHONPATH=src .venv/bin/python scripts/probe_local.py --pipeline
```

既存の日本語録音を使う場合は、16,000 Hz、mono、PCM16 の WAV を指定してください。

```bash
PYTHONPATH=src .venv/bin/python scripts/probe_local.py --asr-wav recordings/japanese.wav --pipeline
```

ブラウザの回帰 probe は、別のテスト用 Python 環境に Playwright と Chromium を導入して使用します。voice agent も起動してください。WAV は fake microphone に渡すため、先頭に約 8 秒の無音を付けて接続完了を待たせます。物理マイクは使用しません。

```bash
python tests/browser/cpu_webrtc_smoke.py --wav .models/browser-input.wav
```

指定対象と同じ Intel Core i7-10700KF を `lscpu` で確認し、実モデルを使って以下を検証しました。これらは短い smoke sample の値です。benchmark の保証値や Windows の実マイク評価ではありません。

| 検証 | 結果 |
| --- | --- |
| NeMo / llama.cpp CPU build | 成功 |
| mock / repository tests | `pytest`: 279 passed、12 subtests passed。ruff / pre-commit 成功 |
| 既存クライアント lint / build | 成功 |
| ASR 日本語 sample | `こんにちは今日は良い天気ですね`、partial 22 回、最初の partial 0.403 s、unpaced RTF 0.420 |
| LLM | Q4_K_M / gpt-oss / 24 blocks を確認。cached prompt sample の TTFT 0.816 s、最初の final content 1.873 s、生成 11.4 tokens/s |
| TTS | 合成 1.96 s、生成音声 2.95 s、RTF 0.663 |
| Chromium 151 WebRTC | media 双方向成功、送信 36,185 bytes、受信 12,702 bytes、page error なし |
| 既存 user/bot latency observer | この WebRTC smoke で 6.490 s |

ブラウザ smoke はユーザーの `こんにちは今日は良い天気ですね` を認識し、assistant の `こんにちは、今日は本当に天気がいいですね。` を音声出力しました。外部 route をブロックした状態で検証しました。

初期調査で Pipecat client の既定 DailyMediaManager に外部 asset 取得と Sentry があることを確認したため、CPU モードは既存 export の `WavMediaManager` を選びます。`/api/deployment` の `cpu_only` metadata で切り替えます。既存 UI と SmallWebRTC transport は維持しています。

Windows Chrome / Edge の実マイク、LAN の firewall、音響品質、長時間会話、および全ケースの barge-in は未検証です。対象 Windows と Ubuntu で追加確認してください。上記の TTS と latency は warmup、文の長さ、context、および thread 競合で変化します。

## Upstream 追従

この fork は Nemotron Voice Agent の全 git 履歴を継承しています。fork 元は [commit d93ce3ed7a635fac3cf39f7f88888c809298cb8d](https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent/commit/d93ce3ed7a635fac3cf39f7f88888c809298cb8d) です。固定 tag `upstream-base` がこの commit を指し、その直後の commit に CPU 実装をまとめています。`.upstream.json` に元 repo、基点、および依存 OSS の revision を記録します。

fork 元から現在までの全変更を、追加 adapter を含めて確認します。

```bash
git diff --stat upstream-base..HEAD
git diff upstream-base..HEAD
```

`upstream-base` は fork 元の固定基点です。upstream 追従後も移動・付け替えを行いません。`upstream/main` は fetch により更新されるため、それとの差分は取得時点によって変わります。CPU fork の累積変更を同じ基点から比較する場合は `upstream-base` を使ってください。未コミット変更は上記の比較に含まれないため、`git status` と `git diff` も確認します。

通常の git merge で upstream に追従できます。作業内容を commit し、作業 tree を整理した後に実行してください。

```bash
git fetch upstream
git merge upstream/main
```

`upstream` remote は `https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent.git` を指します。新しい clone で remote が未設定の場合は、最初に追加します。

```bash
git remote add upstream https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent.git
```

merge conflict は CPU 分岐と upstream の変更を確認して解消します。既存 cloud / hardware 設定は削除しません。元の README、ライセンス、および upstream runtime の依存を保持し、CPU モードだけで cloud と GPU を無効にします。merge 後は Pipecat abstraction、NeMo protocol、llama.cpp flags、および CPU/cloud の両分岐を検証してください。依存バージョン変更では `skills/upgrade-pipecat/SKILL.md` の手順を実施します。

`scripts/upstream_diff.py` は補助比較として使用できます。`.upstream.json` に記録した基点と一致する別 checkout を渡すと、元の tree にある変更・削除ファイルを表示します。追加ファイルも含むレビューには、上記の git diff を使用してください。

```bash
.venv/bin/python scripts/upstream_diff.py /tmp/voice-upstream --patch
```

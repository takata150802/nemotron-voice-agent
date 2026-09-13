# CPU Docker デプロイ

## 配布構成

CPU 構成を 4 つの Docker image と deployment bundle に分けて配布します。デプロイ先ではソースの build や image の pull を行いません。モデルと TLS 証明書は別途配置します。ASR、LLM、および TTS は CPU で実行し、内部サービスは `127.0.0.1` に bind します。

image 名はバージョンと CPU architecture を含みます。

| Image | Dockerfile target | 役割 |
| --- | --- | --- |
| `cpu-voice-bot/app:VERSION-ARCH` | `app` | 既存 Pipecat、WebRTC、ブラウザ UI |
| `cpu-voice-bot/asr:VERSION-ARCH` | `asr` | NeMo-Speech.cpp CPU server |
| `cpu-voice-bot/llm:VERSION-ARCH` | `llm` | llama.cpp CPU server |
| `cpu-voice-bot/tts:VERSION-ARCH` | `tts` | VOICEVOX ENGINE CPU |

`ARCH` は `amd64` または `arm64` です。各 architecture の Linux host で native build してください。amd64 image を NVIDIA Grace の arm64 host に転送して動く扱いにはしません。Grace での build、実モデル、および音声会話の検証は未実施です。

Compose profile は `generic-assistant/cpu` です。既存 cloud / workstation / DGX Spark / Jetson Thor profile は保持します。CPU Docker 構成は `docker/docker-compose.cpu.yaml` を root Compose に include します。ほかの recipe profile と同時に起動しません。

## Build と保存

build 用 Linux host に Docker と必要なディスク容量を用意します。ソフトウェアと tokenizer の事前取得にはネットワークを使用します。モデルは image に含めません。

リポジトリルートでバージョンを指定します。

```bash
bash scripts/build_cpu_images.sh 1.0.0
```

`docker/Dockerfile.cpu` の 4 targets を native architecture で build します。CMake は `GGML_NATIVE=OFF`、`GGML_BACKEND_DL=ON`、および `GGML_CPU_ALL_VARIANTS=ON` を使い、build host 固有の CPU 命令だけに固定しない構成です。CUDA / GPU backend は使用しません。ただし architecture が一致するだけで、すべての CPU の性能を保証するものではありません。NeMo の pinned revision は CPU variants にそのまま対応しないため、`patches/nemo-cpu-variants.patch` で CMake の単一 CPU backend 依存と install guard、ggml backend の一度だけの全ロード、および device buffer type の取得を調整します。ASR-only server の未使用 TTS / NMT は build から外します。

スクリプトが表示した保存コマンドで 4 images を 1 つの archive に保存できます。amd64 の例です。

```bash
docker save -o cpu-voice-bot-1.0.0-amd64-images.tar \
  cpu-voice-bot/app:1.0.0-amd64 \
  cpu-voice-bot/asr:1.0.0-amd64 \
  cpu-voice-bot/llm:1.0.0-amd64 \
  cpu-voice-bot/tts:1.0.0-amd64
```

arm64 ではすべての tag と archive 名を `arm64` に合わせます。deployment bundle を作成します。

```bash
bash scripts/package_cpu_deploy.sh 1.0.0
```

bundle は `.build/cpu-deploy-1.0.0.tar.gz` に作成されます。bundle 内の `.env.cpu.example` には指定バージョンが自動反映されます。image archive と bundle archive をデプロイ先に転送してください。既存 `.env` は変更しません。

## デプロイ先の準備

デプロイ先は Linux Docker host です。Docker Compose plugin を用意し、image archive を load します。

```bash
docker load -i cpu-voice-bot-1.0.0-amd64-images.tar
```

deployment bundle を展開し、そのルートを作業ディレクトリにします。

```bash
mkdir -p cpu-deploy
tar -xzf cpu-deploy-1.0.0.tar.gz -C cpu-deploy
cd cpu-deploy
```

bundle の `.env.cpu.example` を `.env.cpu` にコピーし、配置したファイルに合わせて編集します。

```bash
test -f .env.cpu || cp .env.cpu.example .env.cpu
```

主要な設定は以下のとおりです。相対モデルパスで別ディレクトリを参照しないよう、モデルディレクトリと証明書パスには絶対パスを使います。

| 設定 | 内容 |
| --- | --- |
| `CPU_IMAGE_VERSION` | `1.0.0` などの配布バージョン |
| `CPU_MODELS_DIR` | host 上のモデルディレクトリの絶対パス |
| `NEMO_ASR_MODEL_FILE` | ディレクトリ内の Nemotron 3.5 ASR Q8 GGUF ファイル名 |
| `LLM_MODEL_FILE` | ディレクトリ内の gpt-oss-20b Q4_K_M GGUF ファイル名 |
| `VOICE_AGENT_TLS_CERT` | host 上の TLS 証明書の絶対パス |
| `VOICE_AGENT_TLS_KEY` | host 上の TLS private key の絶対パス |
| `VOICE_AGENT_HOST` | browser endpoint の bind address |
| `VOICE_AGENT_PORT` | browser endpoint の TCP port |
| `NEMO_SPEECH_URL` | loopback ASR WebSocket URL。既定 `ws://127.0.0.1:8081/v1/realtime` |
| `LLM_BASE_URL` | loopback LLM URL。既定 `http://127.0.0.1:8080/v1` |
| `TTS_BASE_URL` | loopback TTS URL。既定 `http://127.0.0.1:50021` |
| `NEMO_ASR_THREADS` | ASR compute thread。初期値 2 |
| `LLAMA_THREADS` | LLM generation thread。初期値 4 |
| `TTS_THREADS` | VOICEVOX CPU thread。初期値 2 |

`CPU_DEPLOY_ENV` で `.env.cpu` 以外の設定ファイルを指定できます。既存サービスと port が競合する場合は、3 つの内部 URL と `VOICE_AGENT_PORT` を変更します。全サービスの起動と health はこれらの URL に追従します。URL は数値 loopback address と明示 port を必要とします。

モデルの取得元、checksum、および量子化方式は [CPU ローカルガイド](cpu-local.md) を参照してください。モデルは build 時ではなく、デプロイ先に別途配置します。TLS private key を image や配布 archive に含めません。

VOICEVOX は公式 `voicevox/voicevox_engine:cpu-ubuntu22.04-0.25.2` を digest `sha256:148b7ade1e698893d8722b6bbd92c059f8796b4ab45449cf45e0601369e63455` で固定します。CPU wrapper が使う `python3` を追加します。対象 architecture の asset と利用する話者の条件を確認してください。VOICEVOX は文単位で WAV を合成するため、真の acoustic streaming ではありません。

## 起動と確認

bundle ルートで起動します。

```bash
bash scripts/deploy_cpu.sh up
```

起動前にモデル、TLS、host と Docker daemon の architecture、load 済み image、および設定を preflight で確認します。ネットワークなしの ASR container で loopback URL を検査し、`ssl.load_cert_chain` で証明書と鍵を実際に読み込みます。Compose は `--pull never --no-build --wait --wait-timeout 600` で、最大 600 秒 health を待ちます。4 つの CPU services だけを起動します。必要な image がない場合に、デプロイ先で自動取得した扱いにはしません。

状態、ログ、および停止には以下を使用します。

```bash
bash scripts/deploy_cpu.sh status
bash scripts/deploy_cpu.sh logs
bash scripts/deploy_cpu.sh stop
```

`logs` は直近 200 行を表示して follow します。`stop` は CPU containers を停止し、モデルと TTS data volume を保持します。root Compose の未使用 upstream include により `NVIDIA_API_KEY` 未設定の警告が出る場合がありますが、CPU profile に API キーは不要です。

モデルロードには時間がかかります。health が成功しない場合は logs を確認し、モデルパス、GGUF metadata、architecture、RAM、および TLS ファイルを修正してください。

## Windows 接続とネットワーク

Windows Chrome / Edge から `https://<LinuxサーバのLANアドレス>:<VOICE_AGENT_PORT>/` に接続します。Windows に Python は不要です。マイク許可を選び、入力機器とスピーカーを確認します。

Docker は Linux host network を使います。WebRTC の UDP media はサーバの host network に直接到達する必要があります。TCP の HTTPS port だけを許可しても、音声が流れない場合があります。Windows の LAN IP からの HTTPS と WebRTC UDP を許可し、内部 ASR / LLM / TTS ports は公開しません。

CPU モードは ICE host candidate だけを使用し、外部 STUN / TURN に接続しません。同一 LAN の直接接続を前提にします。NAT を越える CPU TURN 構成は未実装です。Windows が信頼する証明書を使用し、接続する DNS 名または IP アドレスを Subject Alternative Name に含めてください。[マイクと TLS の詳細](cpu-local.md#windows-ブラウザからの接続) を参照してください。

## 更新と Rollback

新しいバージョンの 4 images を別 tag で build・保存し、対象 host に転送して load します。旧 image を残しておくと rollback できます。`.env.cpu` の `CPU_IMAGE_VERSION` を新しいバージョンに変更し、再起動します。

```bash
bash scripts/deploy_cpu.sh stop
bash scripts/deploy_cpu.sh up
bash scripts/deploy_cpu.sh status
```

rollback は `CPU_IMAGE_VERSION` を旧バージョンに戻して同じ手順で行います。すべてのサービスを同じバージョンと architecture に揃えます。モデルと TLS ファイルは host に保持します。更新先が別のモデル metadata を要求する場合は、モデルの互換性も確認してください。

## 検証結果と範囲

x86_64 host で以下を検証しました。

| 検証 | 結果 |
| --- | --- |
| 4 images の native build | 成功。ASR 約 398 MB、LLM 約 416 MB、TTS 約 2.33 GB、app 約 1.5 GB |
| image 保存 / 転送用 archive の load | `.build/cpu-voice-bot-local-amd64.tar` 約 3.7 GB を保存し、`docker load` で 4 tags を確認 |
| bundle 単独 Compose config | CPU 4 services のみ、host network、build 不要、pull 禁止を確認 |
| 実モデル readiness と起動 | ASR / LLM / TTS / app の health、preflight TLS / loopback URL 検査、実 `up` 成功 |
| ASR streaming sample | partial 22 回、最初の partial 0.385 s、final 1.206 s、unpaced RTF 0.422 |
| 実 Pipecat pipeline | 日本語 ASR → LLM → VOICEVOX の first audio を確認 |
| Chromium WebRTC | inbound 73,439 bytes、outbound 83,558 bytes、日本語 user / bot transcript、page error なし |
| 外部通信を遮断した検証 | browser の外部 route block、app の `--network none` bootstrap import 成功 |
| GPU 依存確認 | app の GPU Python packages なし、ASR / LLM の `ldd` に CUDA 依存なし |
| repository tests | 284 passed、12 subtests passed |

検証用の 4 containers は検証完了後に停止しています。

上記は短い smoke sample の結果で、latency の保証値ではありません。既存 native CPU の測定条件は [CPU ローカルガイド](cpu-local.md#実サービスの-probe-と検証結果) を参照してください。Windows の実マイク、LAN firewall、音響品質、および長時間会話は別途検証してください。

`.github/workflows/cpu-docker.yml` は amd64 と arm64 の native runner で 4 images、network-none runtime import / help、および bundle config を検証します。image publish は行いません。この追加 CI workflow は今回まだ実行していません。arm64 および NVIDIA Grace の実機 build / 推論 / WebRTC は未検証です。

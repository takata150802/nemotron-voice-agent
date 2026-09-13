# CPU ローカル Fork の調査記録

## 調査対象

実装に先立ち、既存リポジトリと公式ソースを確認しました。調査時点の upstream revision は以下のとおりです。最新 main は変化するため、追従時は protocol と CLI を再確認してください。

| OSS | Revision | 確認したソース |
| --- | --- | --- |
| Nemotron Voice Agent | `d93ce3ed7a635fac3cf39f7f88888c809298cb8d` | `src/examples/generic/pipeline.py`、`src/examples/shared/pipeline_utils.py`、`src/server.py`、`client/package.json` |
| NeMo-Speech.cpp | `a5b6953c4a579a2bbd1c0913ad8a85c2a4d99953` | `docs/server.md`、`docs/api.md`、`docs/build.md`、`docs/asr/models.md`、`models/index.json`、server 実装 |
| llama.cpp | `56b9eb280a67796379d8625729fb03d72c70789d` | `tools/server/README.md`、gpt-oss chat template と parser |

## 既存構成と置換箇所

`src/examples/generic/pipeline.py` は `Pipeline`、`PipelineWorker`、`LLMContextAggregatorPair` を使用します。入力 transport、STT、user aggregator、LLM、TTS、出力 transport、および assistant aggregator を接続します。`src/server.py` が既存クライアントを配信し、SmallWebRTC の signaling とセッション管理を担当します。ブラウザには Pipecat client と SmallWebRTC transport が既にあります。

既存 generic pipeline は `NvidiaSTTService`、`NvidiaLLMService`、`NvidiaTTSService` を使用します。CPU 構成に限って backend の生成を差し替えます。cloud / workstation / DGX Spark / Jetson Thor の分岐は維持します。conversation state、sentence aggregation、audio streaming、barge-in、および pipeline metrics は Pipecat の機構を再利用します。

Pipecat の `STTService` は音声処理を async generator で受け取り、transcription frame を downstream に流します。WebSocket STT は音声送信と受信を分離し、partial と final を frame に変換する必要があります。`OpenAILLMService` は OpenAI-compatible server の streaming を扱えます。`TTSService` は集約したテキストを `run_tts` に渡し、音声 frame を生成します。新しい独自の会話 transport や streaming LLM parser は不要です。`LocalOpenAILLMService` は既存 service を継承し、client 生成と cleanup のみを変更します。Pipecat 1.5.0 が提供された `http_client` を無視するため、SDK client を `trust_env=False` で生成して loopback 推論が環境 proxy に流れないようにします。

## NeMo-Speech.cpp の Protocol

公式 [Server Documentation](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/server.md) と [API Reference](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/api.md) を確認しました。

ASR 専用 route は `/v1/audio/transcriptions/realtime` です。VoiceChat モデルがロードされていないとき、要求された `/v1/realtime` も ASR protocol の互換 alias として動作します。この fork は ASR だけをロードします。VoiceChat を同じプロセスに追加してはいけません。

接続後は `session.created` を受信し、音声送信前に `session.update` を送ります。設定には `sample_rate`、`language`、`automatic_punctuation` があります。音声は little-endian PCM16 binary frame です。`input_audio_buffer.commit` が発話を確定し、`conversation.item.input_audio_transcription.delta` と `.completed` が partial と final を返します。`response.cancel` または `input_audio_buffer.clear` は buffered audio を破棄します。これを OpenAI Realtime API と同一の protocol として扱いません。

CPU build preset は `cpu-server`、ASR の CPU 指定は `asr.backend.gpu=-1` です。HTTP worker の `--threads` と ASR backend の thread 数は別の設定です。公式 ASR scheduler は compute thread を 4 に固定しており、公式 compute-thread CLI はありません。`patches/nemo-cpu-threads.patch` は既存 ggml API を使い、cached/direct と scheduler の両経路に fork 専用環境変数 `NEMO_ASR_THREADS` を追加します。架空の公式 option として扱いません。GGUF の公式 repo は `nvidia/nemotron-3.5-asr-streaming-0.6b`、索引上のファイル名は `nemotron-3.5-asr-streaming-0.6b.q8_0.gguf` です。

## 発話終了の責務

CPU 構成は既存の Silero voice activity detection (VAD) で発話終了を判定します。Smart Turn と NeMo server endpointing は無効にします。VAD stop 後に adapter が commit を送り、NeMo の completed を確定文字列として downstream に渡します。これで 3 系統の発話終了判定が競合することを避けます。最終文字列が返る前に LLM が古い partial で応答しないことが重要です。

## LLM と Reasoning

公式 [llama.cpp Server Documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) に `llama-server`、`/v1/chat/completions`、gpt-oss template、および `--reasoning-format` が存在します。GPU を無効にした build と `--n-gpu-layers 0` を組み合わせます。ローカル GGUF を `--model` で読み込み、起動時 download を行う preset は使いません。

Harmony をブラウザや TTS で独自解析せず、llama.cpp の Jinja template と reasoning parser を使います。`--reasoning-format deepseek` は reasoning を `reasoning_content` に分離します。Pipecat の既存 OpenAI-compatible integration を使用し、ユーザー向け `content` のみを読み上げます。`none` は reasoning を content に残すため、この構成には使用しません。

## TTS の選定

日本語、CPU、ローカル HTTP API、および Ubuntu x86_64 での導入容易性から VOICEVOX ENGINE を選びます。公式 [VOICEVOX ENGINE](https://github.com/VOICEVOX/voicevox_engine) の `audio_query` と `synthesis` を使用します。CPU の thread 数は engine の `--cpu_num_threads` で設定できます。

VOICEVOX は 1 文の WAV を生成する方式です。モデルが waveform を逐次生成する真の acoustic streaming ではありません。Pipecat の sentence aggregation により、LLM 全文の生成を待たずに最初の文を合成し、PCM frame を transport に順次渡します。この制約を性能評価で考慮してください。

候補について確認した範囲と、採用上の制約は以下のとおりです。

| 候補 | 公式資料で確認した内容 | この fork での判断 |
| --- | --- | --- |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | 0.6B / 1.7B、日本語、streaming を公開。公式 quickstart は CUDA / FlashAttention を使用 | 対象 CPU の latency と CPU streaming 導入手順を確認できていないため標準にしない |
| [Kokoro](https://github.com/hexgrad/kokoro) | 日本語は `lang_code=j` と `misaki[ja]`。generator がテキスト区間ごとの音声を返す | 日本語 frontend、voice、offline asset、および対象 CPU の性能を未検証。交換候補として残す |
| [Piper](https://github.com/OHF-Voice/piper1-gpl) | local neural TTS、Python / C++ / HTTP interface を提供 | 対象日本語 voice の配布と品質を今回確認していないため標準にしない |
| [VOICEVOX ENGINE](https://github.com/VOICEVOX/voicevox_engine) | 日本語、CPU 明示指定、thread 設定、ローカル HTTP API | 最小の HTTP adapter で導入。文単位 WAV 合成の制約を明記 |

既存の NVIDIA Magpie / NIM 経路は CPU 構成から外します。候補の公開 streaming 対応を、対象 CPU での実測性能と混同しません。TTS abstraction は残しているため、実環境で検証した backend を後から追加できます。VOICEVOX ENGINE のライセンスと各音声の利用規約は別に確認してください。

## 検証の境界

公式ソース確認、CPU build、モデルなし mock protocol テスト、およびクライアント build は、実モデルの日本語認識や対象 CPU の性能とは異なる検証です。モデルを配置した対象 Ubuntu サーバと Windows ブラウザで、全経路、割り込み、再接続、および End of User Speech → First Assistant Audio を測定してください。対象 CPU と実モデルでの backend / Pipecat / Chromium WebRTC smoke は成功しました。[CPU ガイド](how-to/cpu-local.md) に sample の数値と制約を記載しています。Windows の実マイクと LAN は未検証です。

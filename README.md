# printer-registry-poc (Phase 0)

地域印刷機登録・照合システムの Phase 0 PoC。実機がないため、印刷機の NVRAM
書き込み/読み取りは `MockPrinterBackend`(JSONファイルで代替)でシミュレート
している。`PrinterBackend` インタフェースを実装するだけで、Phase 1 以降は
PJL-over-USB / SNMP / EWS API を使う実アダプタに差し替えられる。

## 検証している範囲

- 登録端末：トークン生成(UUID) → ECDSA署名 → 印刷機(モック)への書き込み → ローカル台帳への登録
- 照合端末：印刷機(モック)からトークン読み取り → 署名検証 → ローカル台帳照合 → 3値判定
  (`registered` / `not_registered` / `tamper_suspected`)
- ローカル操作ログのハッシュチェーン化(改ざん検知)

## セットアップ

### 通常(インターネット接続あり)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### オフライン環境(インターネット接続なし)

`wheelhouse/` ディレクトリに必要なパッケージ一式(cryptography, flask とその
依存パッケージ)を wheel ファイルとして同梱済み。USBメモリ等でこのリポジトリ
ごとオフライン環境にコピーし、以下のように `--no-index` でインストールする。

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --no-index --find-links=wheelhouse -r requirements.txt
```

**重要な前提条件**：`wheelhouse/` の wheel はこの開発環境
(Linux x86_64 / Python 3.12 / glibc 2.34以降)向けにビルドされたバイナリ。
オフライン環境のOS・アーキテクチャ・Pythonバージョンが異なる場合は使えない
ため、事前に `python3 --version` と `uname -m` を確認すること。異なる場合は、
インターネットに接続できる環境かつ対象環境と同じ条件(同じPythonバージョン
のマシン、または `pip download --platform ... --python-version ... --abi ...
--only-binary=:all:` でクロスプラットフォーム指定)で `wheelhouse/` を作り
直す必要がある。

```bash
# wheelhouse の作り直し方(オンライン環境で実行)
pip download -r requirements.txt -d wheelhouse --only-binary=:all:
```

## 使い方

```bash
# 1. 登録端末用の署名鍵を生成(初回のみ)
python -m printer_registry.cli init-keys

# 2. 印刷機を登録(モックデバイス usb:001 として)
python -m printer_registry.cli register --device-ref usb:001 --model "Canon X1" --location "本社3F"

# 3. 照合(登録済みと判定されるはず)
python -m printer_registry.cli verify --device-ref usb:001

# 4. 未登録デバイスを照合(not_registered になるはず)
python -m printer_registry.cli verify --device-ref usb:999

# 5. 改ざんをシミュレートしてから照合(tamper_suspected になるはず)
python -m printer_registry.cli tamper --device-ref usb:001
python -m printer_registry.cli verify --device-ref usb:001

# 6. 操作ログとハッシュチェーンの健全性を確認
python -m printer_registry.cli show-log
```

## Web UI(登録・照合端末の画面)

CLIと同じロジック(crypto/db/judge)を呼ぶだけの表示層。ローカルのブラウザ
からダッシュボード・登録・照合を操作できる。ネットワークに公開する用途
ではなく、端末自身の127.0.0.1での利用を想定。

```bash
python -m printer_registry.webui
# ブラウザで http://127.0.0.1:5000/ を開く
```

- `/` … 登録済み印刷機の一覧、直近ログ、ログのハッシュチェーン健全性
- `/register` … デバイス参照・機種・設置場所・バックエンド(mock/pjl-usb)を指定して登録
- `/verify` … デバイス参照とバックエンドを指定して照合し、3値判定を色分け表示

## テスト

```bash
python -m unittest tests/test_flow.py -v
```

## 実機アダプタ(PJL over USB)

`printer_registry/pjl_usb_backend.py` に、USBプリンタのデバイスファイル
(例: Linuxの `/dev/usb/lp0`)へ生のPJLコマンドを送受信する `PJLUSBBackend`
を実装済み。`@PJL DEFAULT <var>="<value>"` でNVRAMへの永続化、
`@PJL DINQUIRE <var>` で読み戻しを行う、汎用ベースラインの実装。

実機がまだ無いため、プロトコルのエンコード/デコード(`pjl_protocol.py`)は
ソケットペア上の擬似プリンタ(`tests/test_pjl_backend.py`)でバイト列レベル
まで検証済みだが、**実プリンタでの動作は未検証**。ベンダーによって
`@PJL DEFAULT` の代わりに `@PJL SET` が必要だったり、応答フォーマットが
異なったりするため、実機接続後にまずこの1点を確認する必要がある。

```bash
# 実機(/dev/usb/lp0)に対して実行する場合
python -m printer_registry.cli register --backend pjl-usb --device-ref /dev/usb/lp0 --model "Canon X1" --location "本社3F"
python -m printer_registry.cli verify --backend pjl-usb --device-ref /dev/usb/lp0
```

## 実運用に置き換える際の残りの変更点

- `printer_registry/crypto.py` … 秘密鍵の読み書きをTPM/USBセキュリティキー
  呼び出しに置き換える(秘密鍵をファイルとして扱わない)
- `printer_registry/db.py` … SQLite接続をSQLCipher(暗号化)に切り替える
- `pjl_usb_backend.py` … 実機検証後、ベンダーごとにコマンド体系の差分を
  吸収するサブクラス/プラグインに分岐させる

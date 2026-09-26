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

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
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

# Zaico在庫確認システム（クラウド版）

受注伝票PDFから品番と数量を自動抽出し、Zaico APIで在庫を一括確認するWebアプリケーション。

## ローカル実行

```bash
pip install -r requirements.txt
python zaico_app.py
```

ブラウザで http://localhost:5000 を開く

## クラウドデプロイ（Render.com）

1. GitHubリポジトリを作成
2. このフォルダの内容をpush
3. Render.comでWebサービスを作成
4. リポジトリを接続してデプロイ

## ファイル構成

```
zaico_final/
├── zaico_app.py          # メインアプリ
├── templates/
│   ├── index.html        # PDFアップロード画面
│   └── test.html         # 品番入力テスト画面
├── requirements.txt      # Python依存パッケージ
├── Procfile             # Render.com用起動設定
└── README_deploy.md     # デプロイ手順
```

## 技術スタック

- Backend: Python 3.12, Flask
- PDF処理: PyPDF2
- API連携: Zaico API
- デプロイ: Render.com (gunicorn)

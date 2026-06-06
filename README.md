# Twitch × LoL Rank Linker

Twitch アカウントと League of Legends のランクを連携させ、配信チャットにランクバッジを表示する Web アプリケーションです。

## 機能

- **Twitch OAuth 認証** — Twitch アカウントでのログイン（認可コードフロー）
- **LoL アカウント連携** — Riot ID を入力して Twitch ID とランク情報をリンク
- **連携結果表示** — 連携後にランクエンブレム・LP・勝率をカード形式で表示
- **OBS チャットオーバーレイ** — 背景透過のチャット表示（ランクバッジ付き）を OBS のブラウザソースとして使用可能

## スクリーンショット

| 認証・連携ページ | OBS オーバーレイ |
|---|---|
| Twitch ログイン → Riot ID 入力 → 連携完了後にランクカードを表示 | `http://localhost:8000/overlay?channel=チャンネル名` |

## セットアップ

### 必要なもの

- Python 3.10 以上
- Twitch Developer アカウント（[Twitch Developer Console](https://dev.twitch.tv/console)）
- Riot Games API キー（[Riot Developer Portal](https://developer.riotgames.com/)）

### インストール

```bash
# リポジトリをクローン
git clone https://github.com/YOUR_USERNAME/twitch-lol-rank-linker.git
cd twitch-lol-rank-linker

# 仮想環境を作成・有効化
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Mac/Linux

# 依存パッケージをインストール
pip install -r requirements.txt
```

### 環境変数の設定

プロジェクトルートに `.env` ファイルを作成し、以下の内容を記載してください。

```env
# Riot API Key
RIOT_API_KEY=RGAPI-your-api-key-here

# Twitch OAuth
TWITCH_CLIENT_ID=your_twitch_client_id
TWITCH_CLIENT_SECRET=your_twitch_client_secret
TWITCH_REDIRECT_URI=http://localhost:8000/auth/twitch/callback
```

#### Twitch アプリの設定

[Twitch Developer Console](https://dev.twitch.tv/console) でアプリを作成し、以下を設定してください。

- **OAuth リダイレクト URL**: `http://localhost:8000/auth/twitch/callback`

### サーバーの起動

```bash
uvicorn main:app --reload
```

ブラウザで [http://localhost:8000](http://localhost:8000) を開いてください。

## エンドポイント一覧

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/` | GET | 認証・連携ページ |
| `/overlay?channel={name}` | GET | OBS 向け透過チャットオーバーレイ |
| `/auth/twitch/login` | GET | Twitch OAuth ログイン開始 |
| `/auth/twitch/callback` | GET | Twitch OAuth コールバック |
| `/api/link` | POST | アカウント連携（Riot API 呼び出し・CSV 保存） |
| `/api/user/{twitch_id}` | GET | ユーザーの連携情報取得 |

## 技術スタック

- **バックエンド**: Python / FastAPI / httpx
- **フロントエンド**: HTML / CSS / JavaScript（Vanilla）
- **フォント・アイコン**: Google Fonts (Roboto) / Font Awesome 6
- **データ保存**: CSV ファイル（`links.csv`）

## セキュリティに関して

- `.env`（API キー）および `links.csv`（ユーザーデータ）は `.gitignore` によりリポジトリに含まれません。
- フロントエンドへのレスポンスには PUUID などの機密情報は含まれず、ランク・勝率情報のみが返されます。

## ライセンス

MIT License

---

> このプロジェクトは Riot Games の ["Legal Jibber Jabber"](https://www.riotgames.com/en/legal) ポリシーのもとで作成されており、Riot Games の公式サポートや承認は受けていません。

import os
from core.config import logger, BASE_DIR
from core.http_client import http_client


async def init_static_files():
    """FastAPI起動時にローカルの static/ フォルダを確認し、tmi.min.js を自動でDLしてキャッシュする"""
    static_dir = os.path.join(BASE_DIR, "static")
    os.makedirs(static_dir, exist_ok=True)
    tmi_path = os.path.join(static_dir, "tmi.min.js")
    
    # ファイルが存在しても、前回のダウンロード失敗によるゴミ（エラー文字列等）の可能性があれば再DLする
    should_download = True
    if os.path.exists(tmi_path):
        try:
            # 正常なブラウザ向けビルドは約36KBあるため、極端に小さい(1KB未満)場合は無効とみなす
            if os.path.getsize(tmi_path) > 1024:
                should_download = False
            else:
                logger.warning("既存の tmi.min.js が破損している可能性があるため（サイズ1KB未満）、再ダウンロードします。")
        except Exception as e:
            logger.error(f"tmi.min.js のサイズチェック中にエラーが発生しました: {e}")
            
    if should_download:
        logger.info("tmi.min.js を公式リポジトリからダウンロードします...")
        try:
            # tmi.js 1.8.5 相当のブラウザ用ビルド
            url = "https://raw.githubusercontent.com/tmijs/tmi.js/master/dist/tmi.min.js"
            response = await http_client.get(url, timeout=15.0)
            if response.status_code == 200 and len(response.text) > 1024:
                with open(tmi_path, "w", encoding="utf-8") as f:
                    f.write(response.text)
                logger.info("tmi.min.js のダウンロードが完了し、ローカルに保存されました。")
            else:
                status_code = response.status_code
                logger.error(f"tmi.min.js のダウンロードに失敗しました (Status={status_code}, Length={len(response.text) if response else 0})")
        except Exception as e:
            logger.error(f"tmi.min.js のダウンロード中にエラーが発生しました: {e}")

import ccxt
import time
import json
from datetime import datetime
import requests

# === Telegram Bot 設定 ===
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram 發送失敗: {e}")

# === Binance API 設定 ===
API_KEY = os.environ.get("BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET")
exchange = ccxt.binance({
    'rateLimit': 1200,
    'enableRateLimit': True,
    'apiKey': API_KEY,
    'secret': API_SECRET
})

# === 程式參數配置 ===
KLINE_TIMEFRAME = '5m'  # K 棒時間框架
VOLUME_THRESHOLD = 600  # 成交量增長閾值（百分比）
EXCLUDED_PAIRS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT", "USDC/USDT", "TUSD/USDT", "USDP/USDT"]  # 排除的交易對

# === 追蹤清單 (Set) ===
watchlist = set()
timestamps = {}
detected_count = 0

# === 獲取所有 USDT 現貨交易對 ===
def get_usdt_pairs():
    markets = exchange.load_markets()
    usdt_pairs = [
        symbol for symbol, market in markets.items()
        if symbol.endswith('/USDT') and  # 以 USDT 結尾
           market.get('spot', False) and  # 現貨市場
           market.get('active', True) and  # 交易對是活躍的
           "UP" not in symbol and "DOWN" not in symbol and  # 排除槓桿代幣
           symbol not in EXCLUDED_PAIRS  # 排除指定交易對
    ]
    return usdt_pairs

def fetch_ohlcv_with_timestamp(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=KLINE_TIMEFRAME, limit=12)
        if len(ohlcv) < 12:
            print(f"數據不足，跳過交易對: {symbol}")
            return None, None

        latest_kline = ohlcv[-1]
        latest_timestamp = latest_kline[0]  # 開盤時間戳
        return ohlcv, latest_timestamp
    except Exception as e:
        print(f"抓取 {symbol} 的 K 棒數據失敗: {e}")
        time.sleep(5)  # 等待 5 秒後重試
        return fetch_ohlcv_with_timestamp(symbol)

def calculate_volume_increase(ohlcv):
    volumes = [kline[5] for kline in ohlcv[:-1]]  # 排除最新一根
    latest_volume = ohlcv[-2][5]  # 倒數第 2 根的成交量
    average_volume = sum(volumes[-10:]) / len(volumes[-10:])  # 倒數第 3 到第 12 根的平均成交量

    if average_volume == 0:
        return 0  # 避免除以零

    increase_percentage = ((latest_volume - average_volume) / average_volume) * 100
    return increase_percentage

def track_watchlist():
    now = datetime.utcnow()
    for symbol in watchlist:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=2)
        if ohlcv:
            vol = ohlcv[-2][5]
            with open("volume_log.csv", "a") as f:
                f.write(f"{now},{symbol},{vol}\n")
    print(f"[{now}] 已追蹤 watchlist 中的幣並記錄成交量")

# === 主邏輯 ===
usdt_pairs = get_usdt_pairs()
last_tracked_hour = None

while True:
    current_time = int(time.time() * 1000)
    utc_now = datetime.utcnow()
    this_hour = utc_now.replace(minute=0, second=0, microsecond=0)
    detected_count = 0

    # 每小時整點追蹤一次 watchlist
    if last_tracked_hour != this_hour:
        track_watchlist()
        last_tracked_hour = this_hour

    # 掃描所有幣種
    for symbol in usdt_pairs:
        if symbol not in timestamps:
            ohlcv, latest_timestamp = fetch_ohlcv_with_timestamp(symbol)
            if not ohlcv:
                continue
            timestamps[symbol] = latest_timestamp

            increase = calculate_volume_increase(ohlcv)
            if increase >= VOLUME_THRESHOLD:
                msg = f"⚡ {symbol} 成交量增長 {increase:.2f}%！"
                print(msg)
                send_telegram_message(msg)
                watchlist.add(symbol)
                detected_count += 1

        else:
            if current_time >= timestamps[symbol] + exchange.parse_timeframe(KLINE_TIMEFRAME) * 1000:
                ohlcv, latest_timestamp = fetch_ohlcv_with_timestamp(symbol)
                if not ohlcv:
                    continue
                timestamps[symbol] = latest_timestamp

                increase = calculate_volume_increase(ohlcv)
                if increase >= VOLUME_THRESHOLD:
                    msg = f"⚡ {symbol} 成交量增長 {increase:.2f}%！"
                    print(msg)
                    send_telegram_message(msg)
                    watchlist.add(symbol)
                    detected_count += 1

    print(f"完成一輪掃描：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC，共處理 {len(usdt_pairs)} 個幣種，偵測到異常 {detected_count} 筆。")
    time.sleep(60)

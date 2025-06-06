import requests

class Exchange:
    def __init__(self, agent):
        self.agent = agent

    def get_price(self, pair):
        try:
            symbol_map = {
                "BTC/USDT": "bitcoin",
                "ETH/USDT": "ethereum"
            }
            symbol = symbol_map.get(pair)
            if not symbol:
                return None
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return resp.json().get(symbol, {}).get("usd")
        except Exception as e:
            self.agent.log(f"[COINGECKO][ERROR] {e}")
        return None
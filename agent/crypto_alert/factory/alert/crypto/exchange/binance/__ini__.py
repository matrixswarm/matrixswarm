import requests

class Exchange:
    def __init__(self, agent):
        self.agent = agent

    def get_price(self, pair):
        try:
            symbol = pair.replace("/", "")
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return float(resp.json().get("price"))
        except Exception as e:
            self.agent.log(f"[BINANCE][ERROR] {e}")
        return None
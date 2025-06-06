import requests

class Exchange:
    def __init__(self, agent):
        self.agent = agent

    def get_price(self, pair):
        try:
            base, quote = pair.split("/")
            url = f"https://api.coinbase.com/v2/prices/{base}-{quote}/spot"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return float(resp.json()["data"]["amount"])
        except Exception as e:
            self.agent.log(f"[COINBASE][ERROR] {e}")
        return None

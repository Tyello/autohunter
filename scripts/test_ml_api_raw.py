import requests
import json
import os

class MercadoLivreClient:
    BASE_URL = "https://api.mercadolibre.com"
    AUTH_URL = "https://auth.mercadolibre.com.br/authorization"
    TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
    TOKEN_FILE = "tokens.json"

    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.access_token = None
        self.refresh_token = None
        self.session = requests.Session()
        self._load_tokens()

    def _load_tokens(self):
        if os.path.exists(self.TOKEN_FILE):
            with open(self.TOKEN_FILE, "r") as f:
                tokens = json.load(f)
                self.access_token = tokens.get("access_token")
                self.refresh_token = tokens.get("refresh_token")
                if self.access_token:
                    self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})

    def _save_tokens(self, tokens):
        with open(self.TOKEN_FILE, "w") as f:
            json.dump(tokens, f)
        self.access_token = tokens["access_token"]
        self.refresh_token = tokens["refresh_token"]
        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})

    def get_auth_url(self):
        return f"{self.AUTH_URL}?response_type=code&client_id={self.client_id}&redirect_uri={self.redirect_uri}"

    def exchange_code_for_token(self, code):
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri
        }
        response = requests.post(self.TOKEN_URL, data=payload)
        response.raise_for_status()
        tokens = response.json()
        self._save_tokens(tokens)
        return tokens

    def refresh_access_token(self):
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token
        }
        response = requests.post(self.TOKEN_URL, data=payload)
        response.raise_for_status()
        tokens = response.json()
        self._save_tokens(tokens)
        return tokens

    def _request_with_auto_refresh(self, method, url, **kwargs):
        """
        Faz requisição e, se der 401, tenta renovar o token automaticamente.
        """
        response = self.session.request(method, url, **kwargs)
        if response.status_code == 401 and self.refresh_token:
            print("Token expirado. Renovando...")
            self.refresh_access_token()
            response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    def search(self, query):
        url = f"{self.BASE_URL}/sites/MLB/search?q={query}"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return response.json()

    def get_user_info(self):
        url = f"{self.BASE_URL}/users/me"
        response = self._request_with_auto_refresh("GET", url)
        return response.json()

    def get_orders(self):
        url = f"{self.BASE_URL}/orders/search"
        response = self._request_with_auto_refresh("GET", url)
        return response.json()


# -------------------------------
# Exemplo de uso
# -------------------------------
if __name__ == "__main__":
    CLIENT_ID = "2817685343478315"
    CLIENT_SECRET = "Sb0bf7omKxCZcYm4HJiMg2pvzixQwnV4"
    REDIRECT_URI = "http://127.0.0.1:8000/callback"

    client = MercadoLivreClient(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI)

    # Se não houver token salvo, peça autorização
    if not client.access_token:
        print("Acesse esta URL para autorizar:", client.get_auth_url())
        CODE = input("Cole aqui o 'code' recebido: ")
        client.exchange_code_for_token(CODE)

    # Busca pública
    resultados = client.search("Honda Civic SI")
    print("Total resultados:", len(resultados["results"]))
    for item in resultados["results"][:3]:
        print(f"{item['title']} - R${item['price']} - {item['permalink']}")

    # Endpoint privado (com renovação automática de token)
    usuario = client.get_user_info()
    print("Usuário autenticado:", usuario["nickname"])

    pedidos = client.get_orders()
    print("Pedidos encontrados:", len(pedidos.get("results", [])))

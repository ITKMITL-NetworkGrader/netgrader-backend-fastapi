import requests
import logging


class ApiClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def callback(self, endpoint: str, data: dict, headers: dict = None):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            response = requests.post(url, json=data, headers=headers or {"Content-Type": "application/json"}, timeout=self.timeout)
            response.raise_for_status()
            logging.info(f"Callback to {url} successful: {response.status_code}")
            return True
        except requests.RequestException as e:
            # Handle/log error as needed
            logging.error(f"API request failed: {e}")  
            return False
        
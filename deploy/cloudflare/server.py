"""Cloudflare Containers上でlambda_handlerを動かすHTTPサーバー。

旧HuggingFace Spaces版(deploy/huggingface/hf_server.py、traffic_accidentリポジトリ)
とほぼ同じ作りだが、ポートはCloudflare Containersの慣例に合わせてデフォルト8080に
している(src/index.tsのContainerサブクラスのdefaultPortと一致させること)。
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from lambda_handler import handler, score_handler

PORT = int(os.environ.get("PORT", 8080))

ROUTES = {
    "/ask": handler,
    "/score": score_handler,
}


class AskHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        # Cloudflare Containersのヘルスチェック用。/ask, /score以外へのGETはこれで応答する。
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))

    def do_POST(self):
        route_handler = ROUTES.get(self.path)
        if route_handler is None:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        result = route_handler({"body": body})

        self.send_response(result["statusCode"])
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(result["body"].encode("utf-8"))

    def log_message(self, fmt, *args):
        print(f"[server] {self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), AskHandler)
    print(f"つうがくナビ バックエンド起動: 0.0.0.0:{PORT}")
    server.serve_forever()

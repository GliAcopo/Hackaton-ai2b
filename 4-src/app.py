"""Server minimo: zero dipendenze, parte sempre.

A un hackathon `pip install` che fallisce alle 16:00 è una sconfitta.
Se vuoi FastAPI mettila dopo, quando il flusso già gira.

    python3 src/app.py     ->  http://localhost:8000
"""
from __future__ import annotations

import json
import sys
import traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm  # noqa: E402
from insight import classifica, scheda  # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):  # meno rumore nel terminale
        pass

    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return super().do_GET()
        params = parse_qs(url.query)
        try:
            if url.path == "/api/health":
                return self._json({"llm": llm.health()})
            if url.path == "/api/analisi":
                keyword = params.get("keyword", ["Equilibrio"])[0]
                n = int(params.get("n", ["3"])[0])
                lens, top = classifica(keyword, n)
                return self._json(
                    {
                        "keyword": keyword,
                        "lente": {"nome": lens.nome, "descrizione": lens.descrizione},
                        "comuni": [c.to_dict() for c in top],
                        "schede": [scheda(c, keyword, lens) for c in top],
                    }
                )
            return self._json({"errore": "endpoint sconosciuto"}, 404)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self._json({"errore": f"{type(exc).__name__}: {exc}"}, 500)


if __name__ == "__main__":
    print(llm.health())
    print("http://localhost:8000  (Ctrl-C per fermare)")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()

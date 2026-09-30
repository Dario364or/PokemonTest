import os, sys, time, re, random
import requests                      # solo para Telegram
from curl_cffi import requests as cr # para Carrefour (huella de Chrome)
from bs4 import BeautifulSoup

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
INTERVAL = float(os.environ.get("INTERVAL", 20))        # segundos por ronda completa
MAX_SECONDS = int(os.environ.get("MAX_SECONDS", 350 * 60))
REMINDER = 300                                          # repetir aviso cada 5 min si sigue disponible
MAX_PRICE = float(os.environ.get("MAX_PRICE", 0))       # 0 = sin límite

PRODUCTS = {
    "Mini latas (ES)": "https://www.carrefour.es/pokemon-30th-aniversario-mini-latas-6-anos-unboxing/VC4A-34535247/p",
    "Mini latas (EN)": "https://www.carrefour.es/pokemon-30th-aniversario-mini-latas-ingles-6-anos-unboxing/VC4A-34535252/p",
    "Figura colección (EN)": "https://www.carrefour.es/pokemon-30th-aniversario-figura-coleccion-ingles-6-anos-unboxing/VC4A-34535240/p",
    "Lote 6 sobres (EN)": "https://www.carrefour.es/pokemon-caja-lote-6-sobres-30th-aniversario-ingles-juego-de-mesa-6-anos-unboxing/VC4A-34530764/p",
    "Lote 6 sobres (ES)": "https://www.carrefour.es/pokemon-caja-lote-6-sobres-30th-aniversario-juego-de-mesa-6-anos-unboxing/VC4A-34530762/p",
    "Caja Premium Ditto (EN)": "https://www.carrefour.es/pokemon-caja-30th-aniversario-coleccion-premium-dito-ingles-6-anos/VC4A-34535239/p",
}
# Producto de control con stock: solo se usa en modo --test
TEST_PRODUCT = {
    "TEST caja con póster": "https://www.carrefour.es/pokemon-30th-aniversario-caja-coleccion-con-poster-6-anos-unboxing/VC4A-34535256/p",
}

NOT_AVAILABLE = ("agotado temporalmente", "agotado", "próximamente", "sin stock", "no disponible")

session = None


def new_session():
    """Sesión nueva que imita a Chrome (TLS + cabeceras) y guarda cookies de la portada."""
    global session
    session = cr.Session(impersonate="chrome")
    try:
        session.get("https://www.carrefour.es/", timeout=15)
    except Exception:
        pass


def telegram(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text},
            timeout=10,
        )
    except requests.RequestException as e:
        print("Error Telegram:", e, flush=True)


def check(item):
    name, url = item
    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return name, url, f"error:{r.status_code}", None, None

        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        low = text.lower()

        if any(k in low for k in NOT_AVAILABLE):
            return name, url, "no", None, None

        has_add = any(line.strip().lower() == "añadir" for line in text.split("\n"))
        if not has_add:
            return name, url, "desconocido", None, None

        seller = re.search(r"Vendido por\s*\n?\s*([^\n]+)", text)
        price = re.search(r"(\d{1,4}(?:\.\d{3})*,\d{2})\s*€", text)
        seller = seller.group(1).strip() if seller else "?"
        price_val = float(price.group(1).replace(".", "").replace(",", ".")) if price else None
        return name, url, "si", seller, price_val
    except Exception as e:
        return name, url, f"error:{type(e).__name__}", None, None


def main():
    new_session()

    if "--test" in sys.argv:
        items = list({**PRODUCTS, **TEST_PRODUCT}.items())
        results = []
        for item in items:
            res = check(item)
            print(res, flush=True)
            results.append(res)
            time.sleep(1)
        ok = sum(1 for r_ in results if not r_[2].startswith("error"))
        telegram(f"🧪 Test Carrefour: {ok}/{len(results)} páginas leídas correctamente.\n"
                 + "\n".join(f"{r_[0]}: {r_[2]}" for r_ in results))
        return

    telegram(f"🤖 Monitor iniciado (cada {INTERVAL:.0f}s por producto)")
    last_alert = {}
    bad_rounds = 0
    warned = False
    end = time.time() + MAX_SECONDS
    pause = INTERVAL / len(PRODUCTS)

    while time.time() < end:
        round_results = []
        for item in PRODUCTS.items():
            name, url, status, seller, price = check(item)
            round_results.append((name, status))

            if status == "si":
                if not (MAX_PRICE and price and price > MAX_PRICE):
                    if time.time() - last_alert.get(name, 0) > REMINDER:
                        p = f"{price:.2f} €" if price else "precio ?"
                        telegram(f"🟢 ¡DISPONIBLE!\n{name}\nVendedor: {seller} · {p}\n{url}")
                        last_alert[name] = time.time()
            elif status == "no":
                last_alert.pop(name, None)
            elif status == "desconocido":
                print(f"[?] Estado no reconocido: {name}", flush=True)

            time.sleep(pause * random.uniform(0.6, 1.4))

        print(time.strftime("%H:%M:%S"), dict(round_results), flush=True)

        if all(s.startswith("error") for _, s in round_results):
            bad_rounds += 1
            codes = sorted({s for _, s in round_results})
            if bad_rounds >= 3 and not warned:
                telegram(f"⚠️ Carrefour parece bloquear las peticiones ({', '.join(codes)}). "
                         f"Reduzco el ritmo y sigo intentándolo.")
                warned = True
            wait = min(300, 30 * bad_rounds)
            print(f"Bloqueo: esperando {wait}s", flush=True)
            time.sleep(wait)
            if bad_rounds % 3 == 0:
                new_session()
        else:
            if warned:
                telegram("✅ Conexión con Carrefour recuperada.")
            bad_rounds = 0
            warned = False


if __name__ == "__main__":
    main()
import os, sys, time, re
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
INTERVAL = 5                                    # segundos entre rondas
MAX_SECONDS = int(os.environ.get("MAX_SECONDS", 350 * 60))
REMINDER = 300                                  # repetir aviso cada 5 min mientras siga disponible
MAX_PRICE = float(os.environ.get("MAX_PRICE", 0))  # 0 = sin límite

PRODUCTS = {
    "Mini latas (ES)": "https://www.carrefour.es/pokemon-30th-aniversario-mini-latas-6-anos-unboxing/VC4A-34535247/p",
    "Mini latas (EN)": "https://www.carrefour.es/pokemon-30th-aniversario-mini-latas-ingles-6-anos-unboxing/VC4A-34535252/p",
    "Figura colección (EN)": "https://www.carrefour.es/pokemon-30th-aniversario-figura-coleccion-ingles-6-anos-unboxing/VC4A-34535240/p",
    "Lote 6 sobres (EN)": "https://www.carrefour.es/pokemon-caja-lote-6-sobres-30th-aniversario-ingles-juego-de-mesa-6-anos-unboxing/VC4A-34530764/p",
    "Lote 6 sobres (ES)": "https://www.carrefour.es/pokemon-caja-lote-6-sobres-30th-aniversario-juego-de-mesa-6-anos-unboxing/VC4A-34530762/p",
    "Caja Premium Ditto (EN)": "https://www.carrefour.es/pokemon-caja-30th-aniversario-coleccion-premium-dito-ingles-6-anos/VC4A-34535239/p",
    # Producto de control (con stock). Descomenta SOLO para probar con --test:
    # "TEST caja con póster": "https://www.carrefour.es/pokemon-30th-aniversario-caja-coleccion-con-poster-6-anos-unboxing/VC4A-34535256/p",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}
NOT_AVAILABLE = ("agotado temporalmente", "agotado", "próximamente", "sin stock", "no disponible")

session = requests.Session()
session.headers.update(HEADERS)


def telegram(text):
    try:
        session.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": False},
            timeout=10,
        )
    except requests.RequestException as e:
        print("Error Telegram:", e, flush=True)


def check(item):
    name, url = item
    try:
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return name, url, f"error:{r.status_code}", None, None

        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        low = text.lower()

        if any(k in low for k in NOT_AVAILABLE):
            return name, url, "no", None, None

        # Botón "Añadir" como línea propia (evita coincidencias tipo "añadir a favoritos")
        has_add = any(line.strip().lower() == "añadir" for line in text.split("\n"))
        if not has_add:
            return name, url, "desconocido", None, None

        seller = re.search(r"Vendido por\s*\n?\s*([^\n]+)", text)
        price = re.search(r"(\d{1,4}(?:\.\d{3})*,\d{2})\s*€", text)
        seller = seller.group(1).strip() if seller else "?"
        price_val = float(price.group(1).replace(".", "").replace(",", ".")) if price else None
        return name, url, "si", seller, price_val
    except requests.RequestException as e:
        return name, url, f"error:{type(e).__name__}", None, None


def main():
    if "--test" in sys.argv:
        telegram("✅ Bot de Carrefour funcionando")
        for res in map(check, PRODUCTS.items()):
            print(res)
        return

    telegram("🤖 Monitor iniciado")
    last_alert = {}            # nombre -> timestamp del último aviso
    errors = 0
    warned = False
    end = time.time() + MAX_SECONDS

    with ThreadPoolExecutor(max_workers=len(PRODUCTS)) as pool:
        while time.time() < end:
            start = time.time()
            results = list(pool.map(check, PRODUCTS.items()))

            n_err = sum(1 for r_ in results if r_[2].startswith("error"))
            errors = errors + 1 if n_err == len(results) else 0
            if errors >= 12 and not warned:
                telegram("⚠️ Carrefour parece estar bloqueando las peticiones.")
                warned = True
            if errors == 0:
                warned = False

            for name, url, status, seller, price in results:
                if status == "si":
                    if MAX_PRICE and price and price > MAX_PRICE:
                        continue    # reventa por encima de tu precio máximo
                    if time.time() - last_alert.get(name, 0) > REMINDER:
                        p = f"{price:.2f} €" if price else "precio ?"
                        telegram(f"🟢 ¡DISPONIBLE!\n{name}\nVendedor: {seller} · {p}\n{url}")
                        last_alert[name] = time.time()
                elif status == "no":
                    last_alert.pop(name, None)
                elif status == "desconocido":
                    print(f"[?] Estado no reconocido: {name}", flush=True)

            print(time.strftime("%H:%M:%S"),
                  {r_[0]: r_[2] for r_ in results}, flush=True)
            time.sleep(max(0, INTERVAL - (time.time() - start)))


if __name__ == "__main__":
    main()
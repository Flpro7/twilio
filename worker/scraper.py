"""Scraper de productos de gandys.com.py.

IMPORTANTE: los selectores CSS de abajo son un punto de partida y casi seguro
van a necesitar ajuste. Inspecciona el HTML real del sitio (DevTools > Elements)
y actualiza PRODUCT_LINK_SELECTOR / los selectores dentro de parse_product_page
antes de correr el ingest en serio. Si el sitio devuelve 403 o el contenido no
aparece en el HTML crudo (porque se arma con JavaScript), usa scrape_with_playwright
en su lugar (requiere `pip install playwright` + `playwright install chromium`).
"""

import logging
import time
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.config import settings

logger = logging.getLogger("gandys-bot.scraper")

HEADERS = {
    "User-Agent": settings.scrape_user_agent,
    "Accept-Language": "es-PY,es;q=0.9",
}

# TODO: ajustar segun la estructura real del sitio (categorias, listados, etc.)
CATEGORY_PATHS = ["/"]
PRODUCT_LINK_SELECTOR = "a.product-item, a[href*='/producto/']"
REQUEST_DELAY_SECONDS = 1.0


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    try:
        response = client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        response.raise_for_status()
        return response
    except httpx.HTTPError as exc:
        logger.warning("Error al pedir %s: %s", url, exc)
        return None


def discover_product_urls(client: httpx.Client) -> set[str]:
    urls: set[str] = set()
    for path in CATEGORY_PATHS:
        response = _get(client, urljoin(settings.scrape_base_url, path))
        if response is None:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        for link in soup.select(PRODUCT_LINK_SELECTOR):
            href = link.get("href")
            if href:
                urls.add(urljoin(settings.scrape_base_url, href))
        time.sleep(REQUEST_DELAY_SECONDS)
    return urls


def parse_product_page(client: httpx.Client, url: str) -> dict | None:
    response = _get(client, url)
    if response is None:
        return None
    soup = BeautifulSoup(response.text, "lxml")

    # TODO: reemplazar por los selectores reales del sitio
    name_el = soup.select_one("h1.product-title, h1")
    price_el = soup.select_one(".price, .product-price")
    description_el = soup.select_one(".product-description, [itemprop='description']")
    image_el = soup.select_one(".product-image img, [itemprop='image']")

    if not name_el:
        return None

    return {
        "name": name_el.get_text(strip=True),
        "price": price_el.get_text(strip=True) if price_el else "",
        "description": description_el.get_text(strip=True) if description_el else "",
        "image_url": image_el.get("src") if image_el else "",
        "url": url,
    }


def scrape_products() -> list[dict]:
    products: list[dict] = []
    with httpx.Client() as client:
        product_urls = discover_product_urls(client)
        logger.info("Encontradas %d URLs de producto", len(product_urls))
        for url in product_urls:
            product = parse_product_page(client, url)
            if product:
                products.append(product)
            time.sleep(REQUEST_DELAY_SECONDS)
    return products


def scrape_with_playwright() -> list[dict]:
    """Alternativa si el sitio renderiza el catalogo con JavaScript o bloquea httpx.

    Requiere: pip install playwright && playwright install chromium
    """
    from playwright.sync_api import sync_playwright

    products: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=settings.scrape_user_agent)
        page.goto(settings.scrape_base_url, wait_until="networkidle")
        product_links = {
            urljoin(settings.scrape_base_url, href)
            for href in page.eval_on_selector_all(
                PRODUCT_LINK_SELECTOR, "els => els.map(e => e.getAttribute('href'))"
            )
            if href
        }
        for url in product_links:
            page.goto(url, wait_until="networkidle")
            name = page.locator("h1").first.text_content() or ""
            products.append({"name": name.strip(), "url": url})
            time.sleep(REQUEST_DELAY_SECONDS)
        browser.close()
    return products

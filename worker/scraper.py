"""Scraper de productos de gandys.com.py.

Estructura real del sitio (confirmada por inspeccion):
- Listado con muestra de productos por categoria (HTML estatico, scrapeable):
    https://gandys.com.py/productos
- Pagina de detalle de producto (HTML estatico, scrapeable):
    https://gandys.com.py/productos/{slug}
- Buscador/listado completo por categoria (renderizado por JS, NO scrapeable
  con httpx/BeautifulSoup -- el HTML crudo devuelve "No se encontraron
  resultados" hasta que el JS del cliente carga los datos):
    https://gandys.com.py/productos/search?page=1&category={categoria}

Dos formas de obtener productos:

- scrape_products(): rapido, sin dependencias extra, pero solo trae la
  MUESTRA que aparece en /productos (~5 por categoria, 30 en total).
- scrape_products_full(): catalogo COMPLETO. Usa Playwright para paginar
  las paginas de busqueda por categoria (necesario porque son JS-rendered)
  y despues usa httpx (mas liviano) para parsear cada pagina de producto.
  Requiere: pip install playwright && playwright install chromium

El sitio no publica precios (es venta/alquiler B2B por cotizacion), asi que
el campo price va a quedar vacio -- es el comportamiento esperado, no un bug.
"""

import logging
import time
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings

logger = logging.getLogger("gandys-bot.scraper")

HEADERS = {
    "User-Agent": settings.scrape_user_agent,
    "Accept-Language": "es-PY,es;q=0.9",
}

# El listado /productos trae una muestra de cada categoria en HTML estatico.
CATEGORY_PATHS = ["/productos"]

# Slugs de categoria usados en /productos/search?category=<slug>
CATEGORY_SLUGS = [
    "racks-para-productos",
    "montacargas-apiladoras-y-otros",
    "maquinas-de-izaje",
    "pallets-1",
    "complementos-logisticos",
    "maquinas-de-limpieza",
]

# Matchea cualquier link que empiece con /productos/ -- se filtra despues
# para descartar /productos/search y el propio listado.
PRODUCT_LINK_SELECTOR = "a[href^='/productos/']"

REQUEST_DELAY_SECONDS = 1.0
MAX_PAGES_PER_CATEGORY = 50  # limite de seguridad para el paginado


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    try:
        response = client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        response.raise_for_status()
        return response
    except httpx.HTTPError as exc:
        logger.warning("Error al pedir %s: %s", url, exc)
        return None


def _is_product_detail_url(url: str) -> bool:
    """True si la URL es una pagina de detalle de producto individual
    (no el listado /productos ni el buscador /productos/search)."""
    path = urlparse(url).path.rstrip("/")
    if not path.startswith("/productos/"):
        return False
    if path == "/productos/search":
        return False
    return True


def discover_product_urls(client: httpx.Client) -> set[str]:
    """Descubre URLs de producto desde /productos (HTML estatico).
    Solo trae la muestra por categoria (~30 productos), no el catalogo
    completo -- para eso usar discover_product_urls_full()."""
    urls: set[str] = set()
    for path in CATEGORY_PATHS:
        response = _get(client, urljoin(settings.scrape_base_url, path))
        if response is None:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        for link in soup.select(PRODUCT_LINK_SELECTOR):
            href = link.get("href")
            if not href:
                continue
            full_url = urljoin(settings.scrape_base_url, href)
            if _is_product_detail_url(full_url):
                urls.add(full_url)
        time.sleep(REQUEST_DELAY_SECONDS)
    return urls


def discover_product_urls_full() -> set[str]:
    """Descubre TODAS las URLs de producto recorriendo, con un browser real,
    las paginas de busqueda por categoria (son JS-rendered, httpx no sirve
    aca). Pagina cada categoria hasta que una pagina no aporte productos
    nuevos.

    Requiere: pip install playwright && playwright install chromium
    """
    from playwright.sync_api import sync_playwright

    product_links: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=settings.scrape_user_agent)

        for category in CATEGORY_SLUGS:
            page_number = 1
            while page_number <= MAX_PAGES_PER_CATEGORY:
                search_url = urljoin(
                    settings.scrape_base_url,
                    f"/productos/search?page={page_number}&category={category}",
                )
                try:
                    page.goto(search_url, wait_until="networkidle", timeout=30000)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error cargando %s: %s", search_url, exc)
                    break

                hrefs = page.eval_on_selector_all(
                    PRODUCT_LINK_SELECTOR,
                    "els => els.map(e => e.getAttribute('href'))",
                )
                found_this_page = {
                    urljoin(settings.scrape_base_url, href)
                    for href in hrefs
                    if href and _is_product_detail_url(urljoin(settings.scrape_base_url, href))
                }

                if not found_this_page:
                    logger.info(
                        "Categoria %s: sin resultados en pagina %d, fin de categoria",
                        category, page_number,
                    )
                    break

                new_links = found_this_page - product_links
                product_links |= found_this_page
                logger.info(
                    "Categoria %s pagina %d: %d productos (%d nuevos)",
                    category, page_number, len(found_this_page), len(new_links),
                )

                if not new_links:
                    # La pagina repite lo mismo que la anterior -> no hay mas.
                    break

                page_number += 1
                time.sleep(REQUEST_DELAY_SECONDS)

        browser.close()

    return product_links


def _find_main_product_image(soup: BeautifulSoup) -> str:
    """Encuentra la imagen principal del producto.

    El sitio no tiene una clase CSS identificable para la imagen principal,
    pero se identificaron dos senales confiables inspeccionando el HTML real:
    1. La imagen grande tiene alt="Imagen grande de {nombre del producto}".
    2. Las imagenes de contenido (fotos de producto) se sirven desde el CDN
       de Strapi (dominio que contiene "strapiapp.com"), mientras que el
       logo y los iconos del sitio salen de gandys.com.py/_astro/.

    IMPORTANTE: usar solo "img" a secas (como estaba antes) trae el logo
    del header, que es el primer <img> del documento -- no la foto del
    producto. Por eso este filtro es necesario.
    """
    img = soup.select_one("img[alt*='Imagen grande']")
    if img and img.get("src"):
        return img["src"]

    for img in soup.select("img"):
        src = img.get("src", "")
        if "strapiapp.com" in src and "large_" in src:
            return src

    for img in soup.select("img"):
        src = img.get("src", "")
        if "strapiapp.com" in src:
            return src

    return ""


def parse_product_page(client: httpx.Client, url: str) -> dict | None:
    response = _get(client, url)
    if response is None:
        return None
    soup = BeautifulSoup(response.text, "lxml")

    name_el = soup.select_one("h1")
    if not name_el:
        return None

    # El sitio no tiene una clase especifica de descripcion identificada;
    # como fallback tomamos el primer parrafo con contenido real de la
    # pagina. Si mas adelante identificas la clase exacta (inspeccionando
    # el HTML con DevTools), agregala primero en este selector.
    description_el = soup.select_one(
        ".product-description, [itemprop='description'], main p, p"
    )
    price_el = soup.select_one(".price, .product-price")

    return {
        "name": name_el.get_text(strip=True),
        "price": price_el.get_text(strip=True) if price_el else "",
        "description": description_el.get_text(strip=True) if description_el else "",
        "image_url": _find_main_product_image(soup),
        "url": url,
    }


def scrape_products() -> list[dict]:
    """Rapido, sin dependencias extra. Solo trae la muestra de /productos
    (~30 productos). Para el catalogo completo usar scrape_products_full()."""
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


def scrape_products_full() -> list[dict]:
    """Catalogo completo de gandys.com.py.

    Fase 1 (Playwright): descubre todas las URLs de producto paginando las
    paginas de busqueda por categoria (JS-rendered).
    Fase 2 (httpx): parsea cada pagina de producto individual (HTML estatico,
    mas rapido que seguir usando el browser).

    Requiere: pip install playwright && playwright install chromium
    """
    product_urls = discover_product_urls_full()
    logger.info("Total de URLs de producto encontradas: %d", len(product_urls))

    products: list[dict] = []
    with httpx.Client() as client:
        for url in product_urls:
            product = parse_product_page(client, url)
            if product:
                products.append(product)
            time.sleep(REQUEST_DELAY_SECONDS)
    return products
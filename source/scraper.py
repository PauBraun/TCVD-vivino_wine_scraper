"""
Vivino Wine Scraper
========================
Script de web scraping per extreure dades de vins de Vivino.com.
Utilitza Selenium per gestionar el contingut dinàmic (JavaScript/React)
i BeautifulSoup per analitzar l'HTML resultant.

El procés s'estructura en dues fases:
  - Fase 1 (Descobriment): Navega per /explore amb filtres, recull URLs de vins.
  - Fase 2 (Extracció): Visita cada URL i extreu dades de 4 fonts:
      1. JSON-LD (Schema.org): nom, bodega, rating, preu
      2. Links <a>: país, regió, raïm, estil
      3. Body text: alcohol, fallbacks
      4. URL params: anyada, wine_id

Ús:
    python scraper.py --wine_type red --countries spain,france,italy --max_wines 500
    python scraper.py --wine_type white --min_rating 4.0 --max_wines 200 --debug

Autor: Pau Braun Arañó
Data: 08 d'Abril 2026
Assignatura: Tipologia i cicle de vida de les dades (UOC)
"""

import argparse
import csv
import json
import logging
import os
import random
import re
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ---------------------------------------------------------------------------
# Configuració del logging: registre dual a fitxer i consola
# Permet auditar el procés complet de scraping posteriorment
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants globals del projecte
# ---------------------------------------------------------------------------
BASE_URL = "https://www.vivino.com"
EXPLORE_URL = f"{BASE_URL}/explore"

# User-Agent: identifiquem el scraper com un navegador Chrome estàndard.
# Segons el material docent (Subirats i Calvo, 2018), és recomanable
# establir un User-Agent realista per evitar bloquejos.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Codis interns de Vivino per als tipus de vi (obtinguts de la URL d'explore)
WINE_TYPES = {
    "red": 1, "white": 2, "sparkling": 3,
    "rose": 4, "dessert": 7, "fortified": 24,
}

# Mapeig de noms de país a codis ISO per als filtres de Vivino
COUNTRY_CODES = {
    "spain": "es", "france": "fr", "italy": "it", "portugal": "pt",
    "argentina": "ar", "chile": "cl", "usa": "us", "australia": "au",
    "germany": "de", "south_africa": "za",
}

# Pausa entre peticions (en segons) per no saturar el servidor.
# Valor aleatori entre MIN i MAX per simular comportament humà.
MIN_DELAY = 2
MAX_DELAY = 5

# Camps del dataset CSV resultant (16 camps per registre)
CSV_FIELDS = [
    "wine_id", "wine_name", "winery", "wine_type", "grape_variety",
    "region", "country", "vintage", "average_rating", "num_ratings",
    "price_eur", "wine_style", "food_pairing", "alcohol_content",
    "wine_url", "scrape_date",
]


# ---------------------------------------------------------------------------
# Funcions auxiliars
# ---------------------------------------------------------------------------
def polite_delay():
    """
    Aplica una pausa aleatòria entre peticions per respectar el servidor.
    Segueix la recomanació de 'bon ús del web scraping' del material docent.
    """
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def setup_driver(headless=True):
    """
    Configura el navegador Chrome amb Selenium.

    Mesures anti-detecció implementades:
    - User-Agent personalitzat (no el per defecte de Selenium)
    - Desactivació de navigator.webdriver (propietat que delata automatització)
    - Exclusió del switch 'enable-automation' de Chrome
    - Desactivació de AutomationControlled

    Args:
        headless: Si True, el navegador s'executa sense interfície gràfica.
    Returns:
        webdriver.Chrome configurat.
    """
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")

    # Configuració del User-Agent explícit
    opts.add_argument(f"--user-agent={USER_AGENT}")
    logger.info(f"User-Agent: {USER_AGENT}")

    # Opcions d'estabilitat per entorns headless
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=en-US")

    # Mesures anti-detecció d'automatització
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=opts)

    # Eliminar la propietat navigator.webdriver del navegador
    # Vivino pot comprovar-la per detectar bots
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    driver.implicitly_wait(10)
    logger.info("WebDriver inicialitzat correctament.")
    return driver


# ---------------------------------------------------------------------------
# Classe principal del scraper
# ---------------------------------------------------------------------------
class VivinoScraper:
    """
    Classe que encapsula tot el procés de web scraping de Vivino.
    Gestiona el cicle de vida del navegador, el descobriment d'enllaços,
    l'extracció de dades i el desament en CSV.
    """

    def __init__(self, headless=True, output_dir="../dataset", debug=False):
        """
        Inicialitza el scraper.

        Args:
            headless: Executar Chrome sense interfície gràfica.
            output_dir: Directori on es desaran els fitxers CSV.
            debug: Si True, desa el text complet de les pàgines per diagnòstic.
        """
        self.driver = setup_driver(headless)
        self.output_dir = output_dir
        self.wines_data = []        # Llista de diccionaris amb les dades dels vins
        self.visited_urls = set()   # URLs ja visitades per evitar duplicats
        self.debug = debug
        self.current_country = ""   # País actual de la cerca (per fallback)
        self.current_wine_type = "" # Tipus de vi actual (per fallback)
        os.makedirs(self.output_dir, exist_ok=True)

    def close(self):
        """Tanca el navegador i allibera recursos."""
        if self.driver:
            self.driver.quit()

    def accept_cookies(self):
        """
        Gestiona el banner de cookies que apareix a la primera visita.
        Intenta trobar i clicar el botó d'acceptar durant 5 segons.
        """
        try:
            btn = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(text(), 'Accept') or "
                               "contains(text(), 'Got it') or "
                               "contains(@class, 'cookie')]")
                )
            )
            btn.click()
            logger.info("Cookies acceptades.")
            time.sleep(1)
        except TimeoutException:
            pass  # No hi ha banner de cookies, continuem

    # ----- FASE 1: Descobriment d'enllaços -----

    def scroll_to_load(self, max_scrolls=10):
        """
        Gestiona l'infinite scroll de la pàgina d'exploració de Vivino.
        Fa scroll fins al final de la pàgina repetidament per carregar
        més vins, i detecta quan no se'n carreguen més.

        Args:
            max_scrolls: Nombre màxim d'intents de scroll.
        Returns:
            int: Nombre total d'elements trobats a la pàgina.
        """
        last = 0
        for _ in range(max_scrolls):
            # Executar JavaScript per fer scroll fins al final
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # Esperar que React renderitzi els nous elements

            # Comptar els elements de vi carregats
            cards = self.driver.find_elements(
                By.CSS_SELECTOR,
                "[class*='wineCard'], [class*='wine-card'], "
                "[data-testid*='wine'], .explorerCard, .wineInfoVintage"
            )

            # Si no s'han carregat nous elements, intentar "Show more"
            if len(cards) == last:
                try:
                    self.driver.find_element(
                        By.XPATH, "//button[contains(text(), 'Show more')]"
                    ).click()
                    time.sleep(2)
                except NoSuchElementException:
                    break  # No hi ha més vins per carregar
            last = len(cards)
        return last

    def extract_wine_links(self):
        """
        Analitza la pàgina actual amb BeautifulSoup per extreure
        els enllaços a les pàgines de detall de cada vi.
        Filtra per URLs que continguin '/w/' (patró de Vivino per a vins).

        Returns:
            list: Llista d'URLs absolutes de detall de vi (sense duplicats).
        """
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Les pàgines de detall de vi contenen '/w/' a la URL
            if "/w/" in href:
                full = href if href.startswith("http") else BASE_URL + href
                if full not in self.visited_urls:
                    links.add(full)
        logger.info(f"Extrets {len(links)} enllaços nous.")
        return list(links)

    def scrape_explore_page(self, wine_type="red", country_code=None,
                            min_rating=3.0, max_wines=100):
        """
        Navega per la pàgina d'exploració de Vivino amb filtres específics
        i recull enllaços a vins mitjançant scroll i paginació.

        Args:
            wine_type: Tipus de vi (red, white, sparkling...).
            country_code: Codi ISO del país (es, fr, it...).
            min_rating: Puntuació mínima per filtrar.
            max_wines: Nombre màxim d'enllaços a recollir.
        Returns:
            list: Llista d'URLs de detall de vi.
        """
        all_links = []
        page = 1
        while len(all_links) < max_wines:
            # Construir la URL amb els filtres com a paràmetres GET
            params = [f"wine_type_ids[]={WINE_TYPES.get(wine_type, 1)}"]
            if country_code:
                params.append(f"country_codes[]={country_code}")
            if min_rating:
                params.append(f"min_rating={min_rating}")
            if page > 1:
                params.append(f"page={page}")
            url = f"{EXPLORE_URL}?{'&'.join(params)}"

            logger.info(f"Navegant a pàgina {page}: {url}")
            self.driver.get(url)
            polite_delay()

            # Acceptar cookies només a la primera pàgina
            if page == 1:
                self.accept_cookies()

            # Fer scroll per carregar tots els vins de la pàgina
            self.scroll_to_load(max_scrolls=5)

            # Extreure els enllaços als vins
            links = self.extract_wine_links()
            if not links:
                break  # No hi ha més vins, fi de la paginació

            all_links.extend(links)
            page += 1
            polite_delay()

        return all_links[:max_wines]

    # ----- FASE 2: Extracció de dades -----

    def extract_wine_detail(self, url):
        """
        Visita la pàgina de detall d'un vi i n'extreu totes les dades.

        Estratègia d'extracció (4 fonts, ordenades per fiabilitat):
          1. JSON-LD (Schema.org): nom, bodega, rating, num_ratings, preu
          2. Links <a> del DOM: país, regió, raïm, estil, maridatge
          3. Body text renderitzat: alcohol, wine style, fallbacks
          4. URL params: anyada (year=), wine_id (/w/XXXX)
          5. Context de cerca: país i tipus de vi com a fallback final

        Args:
            url: URL de la pàgina de detall del vi.
        Returns:
            dict amb els 16 camps del dataset, o None si hi ha error.
        """
        try:
            self.driver.get(url)
            self.visited_urls.add(url)
            polite_delay()

            # Esperar que React renderitzi el contingut dinàmic
            # 15s de timeout + 3s extra per contingut asíncron
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(3)

            # Inicialitzar el diccionari amb tots els camps buits
            wine = {f: "" for f in CSV_FIELDS}
            wine["wine_url"] = url
            wine["scrape_date"] = datetime.now().strftime("%Y-%m-%d")

            # --- FONT 4: Dades de la URL ---
            # L'anyada es troba al paràmetre 'year' de la URL
            try:
                params = parse_qs(urlparse(url).query)
                year = params.get("year", [None])[0]
                if year and year.isdigit() and 1900 < int(year) < 2030:
                    wine["vintage"] = year
            except Exception:
                pass

            # L'ID del vi es troba al path: /w/XXXXX
            id_match = re.search(r"/w/(\d+)", url)
            if id_match:
                wine["wine_id"] = id_match.group(1)

            # --- Executar JavaScript per extreure les dades del DOM ---
            # Utilitzem JS perquè les classes CSS de React són dinàmiques
            # i canvien entre versions. Les fonts que llegim (JSON-LD,
            # href dels links, innerText) són molt més estables.
            data = self.driver.execute_script("""
                var r = {};

                // Font 1: JSON-LD (dades estructurades Schema.org)
                var ld = document.querySelector('script[type="application/ld+json"]');
                if (ld) { try { r.ld = JSON.parse(ld.textContent); } catch(e) { r.ld = null; } }

                // Font 2: Tots els enllaços <a> amb el seu href i text
                var allLinks = [];
                document.querySelectorAll('a[href]').forEach(function(a) {
                    var h = a.getAttribute('href') || '';
                    var t = (a.innerText || '').trim().split('\\n')[0].trim();
                    if (t && t.length > 0 && t.length < 80) {
                        allLinks.push({href: h, text: t});
                    }
                });
                r.links = allLinks;

                // Font 3: Text complet del body (primers 8000 chars)
                r.body = (document.body.innerText || '').substring(0, 8000);

                // Metadades addicionals
                r.title = document.title || '';
                var md = document.querySelector('meta[name="description"]');
                r.meta = md ? md.content : '';

                return r;
            """)

            ld = data.get("ld")
            links = data.get("links", [])
            body = data.get("body", "")
            meta = data.get("meta", "")
            title = data.get("title", "")

            # --- Mode debug: desar text complet per diagnòstic ---
            if self.debug and len(self.wines_data) < 3:
                debug_file = os.path.join(self.output_dir, f"debug_body_{wine['wine_id']}.txt")
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(f"URL: {url}\nTITLE: {title}\nMETA: {meta}\n\n")
                    f.write(f"JSON-LD: {json.dumps(ld, indent=2, default=str) if ld else 'None'}\n\n")
                    f.write("LINKS:\n")
                    for lk in links:
                        f.write(f"  {lk['href']} -> {lk['text']}\n")
                    f.write(f"\nBODY TEXT:\n{body}\n")

            # ============================================================
            # FONT 1: JSON-LD (la font més fiable)
            # Proporciona: nom, bodega, rating, num_ratings, preu
            # El JSON-LD segueix l'estàndard Schema.org/Product
            # ============================================================
            if ld and isinstance(ld, dict):
                wine["wine_name"] = ld.get("name", "")

                # Bodega: dins de l'objecte 'brand'
                brand = ld.get("brand", {})
                if isinstance(brand, dict):
                    wine["winery"] = brand.get("name", "")

                # Puntuació i nombre de valoracions: dins 'aggregateRating'
                agg = ld.get("aggregateRating", {})
                if isinstance(agg, dict):
                    if agg.get("ratingValue"):
                        wine["average_rating"] = str(agg["ratingValue"])
                    if agg.get("ratingCount"):
                        wine["num_ratings"] = str(agg["ratingCount"])

                # Preu: buscar l'oferta per a Espanya (ES) en EUR
                # El JSON-LD conté ofertes per a múltiples regions/monedes
                offers = ld.get("offers", [])
                for offer in offers:
                    if isinstance(offer, dict):
                        region = offer.get("eligibleRegion", {})
                        region_name = region.get("name", "") if isinstance(region, dict) else ""
                        currency = offer.get("priceCurrency", "")
                        # Prioritzem el preu espanyol en EUR
                        if region_name == "ES" and currency == "EUR":
                            wine["price_eur"] = str(offer.get("lowPrice", ""))
                            break

                # Fallback: qualsevol oferta en EUR si no hi ha preu espanyol
                if not wine["price_eur"]:
                    for offer in offers:
                        if isinstance(offer, dict) and offer.get("priceCurrency") == "EUR":
                            wine["price_eur"] = str(offer.get("lowPrice", ""))
                            break

            # Fallback nom: del títol de la pàgina
            if not wine["wine_name"] and title:
                wine["wine_name"] = title.split("|")[0].split(" - Vivino")[0].strip()

            # Netejar nom: eliminar el prefix de la bodega si està duplicat
            # Vivino sovint posa "Bodega NomDelVi" com a nom complet
            if wine["wine_name"] and wine["winery"]:
                name = wine["wine_name"]
                if name.startswith(wine["winery"]):
                    name = name[len(wine["winery"]):].strip()
                # Separar anyada enganxada al final (p.ex. "Margaux2016")
                name = re.sub(r"(\D)((?:19|20)\d{2})$", r"\1 \2", name)
                if name:
                    wine["wine_name"] = name

            # ============================================================
            # FONT 2: Links <a> del DOM
            # Classifiquem cada link pel patró de la seva URL (href):
            #   /explore/countries/  → país
            #   /explore/regions/    → regió (agafem l'últim = més específic)
            #   /explore/grapes/     → varietat de raïm
            #   /wine-styles/        → estil del vi
            #   /wine-news/          → maridatge (noms d'aliments)
            # ============================================================
            grapes = []
            regions = []
            foods = []

            for lk in links:
                href = lk.get("href", "")
                text = lk.get("text", "")
                if not text or not href:
                    continue

                # País: /explore/countries/spain → "Spain"
                if "/explore/countries/" in href and not wine["country"]:
                    wine["country"] = text

                # Regió: /explore/regions/ribera-del-duero → "Ribera del Duero"
                # Recollim totes les regions; l'última és la més específica
                elif "/explore/regions/" in href:
                    if text.lower() not in ("regions", "region", ""):
                        regions.append(text)

                # Raïm: /explore/grapes/tempranillo → "Tempranillo"
                elif "/explore/grapes/" in href:
                    if text.lower() not in ("grapes", "grape", "blend", ""):
                        grapes.append(text)

                # Tipus de vi: link amb wine_type_ids i text descriptiu
                elif "wine_type_ids" in href and not wine["wine_type"]:
                    if any(t in text for t in ["Red", "White", "Sparkling", "Rosé"]):
                        wine["wine_type"] = text

                # Estil: /wine-styles/spanish-rioja-red → "Spanish Rioja Red"
                elif "/wine-styles/" in href and not wine["wine_style"]:
                    if text.lower() not in ("read more", "wine style", ""):
                        wine["wine_style"] = text

                # Maridatge: /wine-news/ amb noms d'aliments
                elif "/wine-news/" in href:
                    if text and text not in ("Wine News",) and len(text) < 40:
                        foods.append(text)

            # Assignar raïm (eliminar duplicats mantenint l'ordre)
            if grapes:
                seen = set()
                unique = []
                for g in grapes:
                    if g not in seen:
                        seen.add(g)
                        unique.append(g)
                wine["grape_variety"] = ", ".join(unique)

            # Assignar regió: l'última trobada és la més específica
            # (Vivino ordena: Spain → Castilla y León → Ribera del Duero)
            if regions:
                wine["region"] = regions[-1]

            # Assignar maridatge
            if foods:
                wine["food_pairing"] = "; ".join(foods)

            # ============================================================
            # FONT 3: Text del body (fallbacks)
            # El text renderitzat de la pàgina conté informació addicional
            # que no sempre és accessible via JSON-LD o links
            # ============================================================

            # Alcohol: patró "Alcohol content\n\t14.5%"
            alc_match = re.search(
                r"Alcohol\s+content\s*\n\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%",
                body
            )
            if alc_match:
                wine["alcohol_content"] = alc_match.group(1).replace(",", ".")

            # Wine style fallback: si no s'ha trobat als links
            if not wine["wine_style"]:
                style_match = re.search(r"Wine\s+style\s*\n\s*([A-Z][^\n]+)", body)
                if style_match:
                    val = style_match.group(1).strip()
                    if val.lower() not in ("wine style", ""):
                        wine["wine_style"] = val

            # Regió fallback: del text "Region\n\tSpain / Castilla / Ribera del Duero"
            if not wine["region"]:
                region_match = re.search(r"Region\s*\n\s*(.+?)(?:\n|$)", body)
                if region_match:
                    parts = [p.strip() for p in region_match.group(1).split("/")]
                    # Agafar l'última part (la més específica)
                    wine["region"] = parts[-1] if len(parts) > 1 else parts[0]

            # Food pairing fallback: del text del body
            if not wine["food_pairing"]:
                food_match = re.search(
                    r"food pairings?\s*\n\s*((?:[A-Z][^\n]*\n?)+?)(?:\nWine style|\n\n)",
                    body
                )
                if food_match:
                    raw = food_match.group(1).strip()
                    items = [line.strip() for line in raw.split("\n") if line.strip()]
                    wine["food_pairing"] = "; ".join(items)

            # ============================================================
            # FONT 5: Fallbacks del context de cerca
            # Si les fonts anteriors no han proporcionat el país o tipus,
            # utilitzem la informació del filtre de cerca actual
            # ============================================================

            # País: del codi de país de la cerca actual
            if not wine["country"] and self.current_country:
                country_map = {
                    "es": "Spain", "fr": "France", "it": "Italy",
                    "pt": "Portugal", "ar": "Argentina", "cl": "Chile",
                    "us": "United States", "au": "Australia",
                    "de": "Germany", "za": "South Africa",
                }
                wine["country"] = country_map.get(self.current_country, "")

            # Tipus de vi: del filtre de cerca actual
            if not wine["wine_type"] and self.current_wine_type:
                wine["wine_type"] = self.current_wine_type.title()

            # Preu fallback: del body text (evitant el banner "€15 off")
            if not wine["price_eur"]:
                price_match = re.search(r"€(\d+(?:[.,]\d{2})?)", body)
                if price_match:
                    val = price_match.group(1).replace(",", ".")
                    if float(val) > 15:  # Descartar el "€15 off" promocional
                        wine["price_eur"] = val

            # Log del resultat per monitoritzar el procés
            logger.info(
                f"Extret: {wine['wine_name']} - {wine['winery']} | "
                f"Regió: {wine['region']} | País: {wine['country']} | "
                f"Tipus: {wine['wine_type']} | Raïm: {wine['grape_variety']} | "
                f"Estil: {wine['wine_style']} | "
                f"Rating: {wine['average_rating']} ({wine['num_ratings']}) | "
                f"Preu: {wine['price_eur']}€ | Alcohol: {wine['alcohol_content']}% | "
                f"Maridatge: {wine['food_pairing']}"
            )
            return wine

        except Exception as e:
            logger.error(f"Error extraient dades de {url}: {e}")
            return None

    # ----- Orquestració del procés complet -----

    def scrape_wines(self, wine_type="red", countries=None, min_rating=3.0,
                     max_wines=500):
        """
        Procés principal: orquestra les dues fases de scraping.

        Fase 1: Per a cada país, navega per /explore i recull URLs.
        Fase 2: Visita cada URL i extreu les dades del vi.
        Desa el CSV parcial cada 50 vins per seguretat.

        Args:
            wine_type: Tipus de vi a cercar.
            countries: Llista de codis ISO de país.
            min_rating: Puntuació mínima.
            max_wines: Nombre màxim total de vins a recollir.
        """
        if countries is None:
            countries = ["es", "fr", "it"]

        # Repartir equitativament els vins entre països
        wines_per_country = max_wines // len(countries)
        all_links = []
        self.current_wine_type = wine_type

        # FASE 1: Descobriment d'enllaços per país
        for country in countries:
            logger.info(f"=== Cercant vins de {country.upper()} ===")
            self.current_country = country
            links = self.scrape_explore_page(
                wine_type=wine_type, country_code=country,
                min_rating=min_rating, max_wines=wines_per_country,
            )
            # Guardar el país associat a cada link per al fallback
            for lk in links:
                all_links.append((lk, country))

        # Eliminar duplicats mantenint l'associació amb el país
        seen = set()
        unique_links = []
        for lk, ctry in all_links:
            if lk not in seen:
                seen.add(lk)
                unique_links.append((lk, ctry))

        logger.info(f"Total d'enllaços únics: {len(unique_links)}")

        # FASE 2: Visitar cada pàgina de detall i extreure dades
        for i, (link, country) in enumerate(unique_links):
            self.current_country = country
            logger.info(f"Processant vi {i + 1}/{len(unique_links)}")

            wine_data = self.extract_wine_detail(link)
            if wine_data and wine_data.get("wine_name"):
                self.wines_data.append(wine_data)

            # Desament parcial cada 50 vins per evitar pèrdua de dades
            if (i + 1) % 50 == 0:
                logger.info(f"Progrés: {i + 1}/{len(unique_links)} processats.")
                self.save_to_csv(partial=True)

        logger.info(f"Scraping finalitzat. Total de vins extrets: {len(self.wines_data)}")

    def save_to_csv(self, filename="vivino_wines.csv", partial=False):
        """
        Desa les dades recollides en format CSV (UTF-8).

        Args:
            filename: Nom del fitxer CSV de sortida.
            partial: Si True, afegeix prefix 'partial_' al nom.
        """
        prefix = "partial_" if partial else ""
        path = os.path.join(self.output_dir, f"{prefix}{filename}")
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                w.writeheader()
                w.writerows(self.wines_data)
            logger.info(f"Dataset desat: {path} ({len(self.wines_data)} registres)")
        except IOError as e:
            logger.error(f"Error desant CSV: {e}")


# ---------------------------------------------------------------------------
# Punt d'entrada: arguments de línia de comandes
# ---------------------------------------------------------------------------
def main():
    """
    Punt d'entrada principal. Analitza els arguments de línia de comandes
    i executa el procés de scraping.
    """
    parser = argparse.ArgumentParser(
        description="Vivino Wine Scraper v4 - Extracció de dades de vins de Vivino.com"
    )
    parser.add_argument("--wine_type", default="red",
                        choices=list(WINE_TYPES.keys()),
                        help="Tipus de vi a cercar (default: red)")
    parser.add_argument("--countries", default="spain,france,italy",
                        help="Països separats per comes (default: spain,france,italy)")
    parser.add_argument("--min_rating", type=float, default=3.0,
                        help="Puntuació mínima (default: 3.0)")
    parser.add_argument("--max_wines", type=int, default=500,
                        help="Nombre màxim de vins (default: 500)")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="Executar sense interfície gràfica (default: True)")
    parser.add_argument("--no-headless", dest="headless", action="store_false",
                        help="Executar amb interfície gràfica visible")
    parser.add_argument("--output", default="vivino_wines.csv",
                        help="Nom del fitxer CSV de sortida")
    parser.add_argument("--debug", action="store_true", default=False,
                        help="Desar fitxers de diagnòstic amb el text de cada pàgina")
    args = parser.parse_args()

    # Convertir noms de països a codis ISO
    country_names = [c.strip().lower() for c in args.countries.split(",")]
    country_codes = [COUNTRY_CODES.get(c, c) for c in country_names]

    logger.info("=" * 60)
    logger.info("VIVINO WINE SCRAPER v4")
    logger.info(f"Tipus: {args.wine_type} | Països: {country_names}")
    logger.info(f"Rating mínim: {args.min_rating} | Màxim vins: {args.max_wines}")
    logger.info("=" * 60)

    scraper = VivinoScraper(headless=args.headless, debug=args.debug)

    try:
        scraper.scrape_wines(
            wine_type=args.wine_type, countries=country_codes,
            min_rating=args.min_rating, max_wines=args.max_wines,
        )
        scraper.save_to_csv(filename=args.output)

    except KeyboardInterrupt:
        # Ctrl+C: desar el que tinguem fins ara
        logger.warning("Scraping interromput per l'usuari. Desant dades parcials...")
        scraper.save_to_csv(filename=args.output)

    except Exception as e:
        logger.error(f"Error inesperat: {e}")
        scraper.save_to_csv(filename=args.output)

    finally:
        scraper.close()


if __name__ == "__main__":
    main()

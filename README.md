# Vivino Wine Dataset

Projecte de web scraping per extreure dades de vins de Vivino.com. Desenvolupat com a Pràctica 1 de l'assignatura "Tipologia i cicle de vida de les dades" del Màster en Ciència de Dades de la UOC.

## Integrants del grup

## DOI del dataset

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19473017.svg)](https://doi.org/10.5281/zenodo.19473017)

## Descripció

Dataset de 4.760 vins negres extrets de Vivino.com mitjançant web scraping (abril de 2026). Cobreix tres dels principals països productors de vi d'Europa: Espanya (1.642 vins), França (1.593) i Itàlia (1.525). Cada registre conté 16 camps: nom del vi, bodega, tipus de vi, varietat de raïm, regió, país, anyada, puntuació mitjana dels usuaris, nombre de valoracions, preu en euros, estil del vi, maridatge, contingut d'alcohol, URL de Vivino i data d'extracció.

## Fitxers del repositori

| Fitxer | Descripció |
|--------|------------|
| `source/scraper.py` | Script principal de web scraping (Python + Selenium + BeautifulSoup) |
| `dataset/vivino_wines.csv` | Dataset resultant amb 4.760 vins en format CSV |
| `requirements.txt` | Dependències Python amb versions |
| `README.md` | Aquest fitxer |

## Com utilitzar el codi

### Requisits previs

- Python 3.9 o superior
- Google Chrome instal·lat

### Instal·lació

```bash
git clone https://github.com/[usuari]/vivino-wine-scraper.git
cd vivino-wine-scraper
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac
pip install -r requirements.txt
```

### Exemples d'ús

```bash
# Execució bàsica: 500 vins negres d'Espanya, França i Itàlia
python source/scraper.py --wine_type red --countries spain,france,italy --max_wines 500

# Vins blancs amb puntuació mínima de 4.0
python source/scraper.py --wine_type white --min_rating 4.0 --max_wines 200

# Amb navegador visible (per debug)
python source/scraper.py --wine_type red --countries spain --max_wines 20 --no-headless

# Mode debug (desa el text de les pàgines per diagnòstic)
python source/scraper.py --wine_type red --countries spain --max_wines 10 --debug
```

### Paràmetres

| Paràmetre | Descripció | Per defecte |
|-----------|------------|-------------|
| `--wine_type` | Tipus de vi (red, white, sparkling, rose, dessert, fortified) | `red` |
| `--countries` | Països separats per comes | `spain,france,italy` |
| `--min_rating` | Puntuació mínima (1.0 - 5.0) | `3.0` |
| `--max_wines` | Nombre màxim de vins a recollir | `500` |
| `--headless` | Executar sense interfície gràfica | `True` |
| `--no-headless` | Executar amb navegador visible | - |
| `--output` | Nom del fitxer CSV de sortida | `vivino_wines.csv` |
| `--debug` | Desar fitxers de diagnòstic | `False` |

## Camps del dataset

| Camp | Descripció | Tipus |
|------|------------|-------|
| `wine_id` | Identificador únic del vi a Vivino | string |
| `wine_name` | Nom del vi | string |
| `winery` | Bodega productora | string |
| `wine_type` | Tipus de vi (Red wine, White wine...) | categòric |
| `grape_variety` | Varietat(s) de raïm | string |
| `region` | Regió d'origen | categòric |
| `country` | País d'origen | categòric |
| `vintage` | Any de collita | numèric |
| `average_rating` | Puntuació mitjana (1.0-5.0) | numèric |
| `num_ratings` | Nombre de valoracions | numèric |
| `price_eur` | Preu en euros | numèric |
| `wine_style` | Estil del vi | categòric |
| `food_pairing` | Maridatge recomanat | string |
| `alcohol_content` | Contingut d'alcohol (% vol.) | numèric |
| `wine_url` | URL de la pàgina a Vivino | string |
| `scrape_date` | Data d'extracció | data |

## Llicència

Dataset publicat sota llicència **CC BY-NC-SA 4.0** (Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International).

"""Компании из карт: 2ГИС (официальный Catalog API, нужен ключ) и OpenStreetMap (бесплатно)."""
import time

import requests

from common import HEADERS, Store, norm_phone

DGIS = "https://catalog.api.2gis.com"
OVERPASS = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRROR = "https://overpass.kumi.systems/api/interpreter"  # только последняя попытка: из РФ часто недоступен
RETRY_DELAYS = [5, 10, 20, 30, 60]  # 504 на overpass-api.de случайные — повтор через несколько секунд обычно проходит
# Overpass отвечает 406 на запросы с браузерным User-Agent: нужно честно представиться скриптом
OSM_HEADERS = {"User-Agent": "lead-parser/1.0 (personal lead search script; python-requests)",
               "Accept-Language": HEADERS["Accept-Language"]}

# Ниша -> теги OpenStreetMap. Если ниши нет в словаре — ищем по слову в названии.
OSM_TAGS = {
    "стоматология": ['"amenity"="dentist"'],
    "салон красоты": ['"shop"="beauty"', '"shop"="hairdresser"'],
    "парикмахерская": ['"shop"="hairdresser"'],
    "автосервис": ['"shop"="car_repair"'],
    "фитнес": ['"leisure"="fitness_centre"'],
    "кафе": ['"amenity"="cafe"'],
    "ресторан": ['"amenity"="restaurant"'],
    "гостиница": ['"tourism"="hotel"'],
    "клиника": ['"amenity"="clinic"'],
    "ветклиника": ['"amenity"="veterinary"'],
    "юрист": ['"office"="lawyer"'],
    "недвижимость": ['"office"="estate_agent"'],
    "цветы": ['"shop"="florist"'],
    "автомойка": ['"amenity"="car_wash"'],
    "барбершоп": ['"shop"="hairdresser"]["name"~"барбер|barber",i', '"shop"="hairdresser"]["hairdresser"~"barber|male"'],
    "шиномонтаж": ['"shop"="tyres"', '"shop"="car_repair"]["service:vehicle:tyres"="yes"'],
    "массаж": ['"shop"="massage"'],
    "spa": ['"leisure"="sauna"', '"amenity"="spa"'],
    "аптека": ['"amenity"="pharmacy"'],
    "автосалон": ['"shop"="car"'],
    "мебель": ['"shop"="furniture"'],
    "ремонт техники": ['"craft"="electronics_repair"', '"shop"="mobile_phone"]["repair"="yes"'],
    "школа": ['"amenity"="language_school"', '"amenity"="driving_school"'],
    "детский сад": ['"amenity"="kindergarten"'],
}


# ---------------- 2ГИС ----------------
def _dgis_region(city, key):
    r = requests.get(f"{DGIS}/2.0/region/search", params={"q": city, "key": key}, timeout=20)
    items = r.json().get("result", {}).get("items", [])
    return items[0]["id"] if items else None


def dgis(cfg, store):
    m = cfg["maps"]
    key = m.get("dgis_key")
    if not key:
        print("[2gis] ключ не задан (maps.dgis_key) — пропускаю")
        return
    warned = False
    for city in m["cities"]:
        region = _dgis_region(city, key)
        for niche in m["niches"]:
            print(f"[2gis] {niche} / {city}")
            for page in range(1, m.get("dgis_pages", 5) + 1):
                params = {"q": niche if region else f"{niche} {city}", "page": page, "page_size": 10,
                          "type": "branch", "fields": "items.contact_groups,items.address", "key": key}
                if region:
                    params["region_id"] = region
                data = requests.get(f"{DGIS}/3.0/items", params=params, timeout=20).json()
                meta = data.get("meta", {})
                if meta.get("code") != 200:
                    if page == 1:
                        print(f"  ! {meta.get('error', {}).get('message', meta)}")
                    break
                for it in data["result"]["items"]:
                    if "contact_groups" not in it and not warned:
                        warned = True
                        print("  ! 2ГИС не отдаёт контакты по этому ключу (демо-ключ) — будут только названия и адреса")
                    phones, emails, sites = [], [], []
                    for g in it.get("contact_groups", []):
                        for c in g.get("contacts", []):
                            if c["type"] == "phone":
                                phones.append(norm_phone(c.get("value", "")))
                            elif c["type"] == "email":
                                emails.append(c.get("value", ""))
                            elif c["type"] == "website":
                                sites.append(c.get("text") or c.get("value", ""))
                    _add(store, cfg, "2ГИС", niche, city, it.get("name", ""), phones, emails, sites,
                         it.get("address_name", ""), key=f"2gis:{it.get('id')}",
                         unknown="contact_groups" not in it)
                time.sleep(0.5)


# ---------------- OpenStreetMap ----------------
def _overpass(query):
    """Список элементов или None, если все попытки не удались."""
    tries = len(RETRY_DELAYS) + 1
    for i in range(tries):
        url = OVERPASS if i < tries - 1 else OVERPASS_MIRROR
        try:
            r = requests.post(url, data={"data": query}, headers=OSM_HEADERS, timeout=(10, 180))
            if r.ok:
                data = r.json()
                if "runtime error" not in data.get("remark", ""):
                    return data.get("elements", [])
                why = "сервер не успел выполнить запрос"
            else:
                why = f"HTTP {r.status_code}"
        except requests.Timeout:
            why = "нет ответа"
        except Exception as e:
            why = type(e).__name__
        if i < tries - 1:
            delay = RETRY_DELAYS[i] * (3 if why == "HTTP 429" else 1)
            print(f"  ! {why}, повтор {i + 1}/{tries - 1} через {delay} с")
            time.sleep(delay)
        else:
            print(f"  ! {why} — пропускаю, попробую при следующем запуске")
    return None


def osm(cfg, store):
    m = cfg["maps"]
    if not m.get("use_osm", True):
        return
    failed = []
    for city in m["cities"]:
        for niche in m["niches"]:
            print(f"[osm] {niche} / {city}")
            tags = OSM_TAGS.get(niche.lower())
            if tags:
                filters = "".join(f"nwr(area.a)[{t}];" for t in tags)
            else:
                stem = niche.lower()[:max(4, len(niche) - 2)]
                # только среди организаций (shop/amenity/office/…): поиск по всем объектам города слишком тяжёлый
                filters = f'nwr(area.a)["name"~"{stem}",i][~"^(shop|amenity|office|craft|leisure|healthcare|tourism)$"~"."];'
            q = (f'[out:json][timeout:150];area["name"="{city}"]["boundary"="administrative"]->.a;'
                 f'({filters});out tags center;')
            elements = _overpass(q)
            if elements is None:
                failed.append(f"{niche} / {city}")
                continue
            print(f"  найдено объектов: {len(elements)}")
            for el in elements:
                t = el.get("tags", {})
                name = t.get("name")
                if not name:
                    continue
                phones = [norm_phone(p) for p in (t.get("phone") or t.get("contact:phone") or "").split(";") if p.strip()]
                emails = [e for e in [(t.get("email") or t.get("contact:email") or "").strip()] if e]
                sites = [s for s in [(t.get("website") or t.get("contact:website") or "").strip()] if s]
                addr = ", ".join(x for x in [t.get("addr:street"), t.get("addr:housenumber")] if x)
                _add(store, cfg, "OSM", niche, city, name, phones, emails, sites, addr,
                     key=f"osm:{el['type']}{el['id']}")
            time.sleep(5)  # не перегружать бесплатные серверы
    if failed:
        print(f"[osm] не удалось загрузить ({len(failed)}): {', '.join(failed)} — повторный запуск их догрузит")


def _add(store, cfg, src, niche, city, name, phones, emails, sites, addr, key, unknown=False):
    """unknown=True: источник не дал контактов, поэтому «нет сайта» утверждать нельзя."""
    if cfg["maps"].get("only_without_site") and (sites or unknown):
        return
    store.add({
        "source": src,
        "title": niche,
        "company": name,
        "city": city,
        "phone": ", ".join(dict.fromkeys(p for p in phones if p)),
        "email": ", ".join(dict.fromkeys(emails)),
        "website": sites[0] if sites else "",
        "text": addr,
        "score": "контакты скрыты" if unknown else ("" if sites else "нет сайта"),
    }, key=key)


def run(cfg):
    store = Store("maps")
    try:
        dgis(cfg, store)
        osm(cfg, store)
    finally:
        store.close()


def check_dgis_key(key):
    """Проверка ключа 2ГИС: (ok, сообщение)."""
    try:
        data = requests.get(f"{DGIS}/3.0/items", params={"q": "кафе", "region_id": 32, "page_size": 1, "key": key},
                            timeout=20).json()
    except Exception as e:
        return False, str(e)
    meta = data.get("meta", {})
    if meta.get("code") == 200:
        return True, f"ключ работает, найдено {data['result'].get('total', '?')} кафе в Москве"
    return False, meta.get("error", {}).get("message", str(meta))

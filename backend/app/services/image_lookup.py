# grabs a real image off the web for a topic so lesson pages have something
# to show instead of that old fake "emulation" placeholder thing.
#
# uses openverse (api.openverse.org) - free, no api key needed, searches
# openly-licensed images from wikimedia, flickr, museums etc.
#
# just plain stdlib http calls, no extra pip package for this. fails soft -
# any network hiccup / timeout / no results just means no image shows up,
# doesn't break the page
import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

OPENVERSE_SEARCH_URL = "https://api.openverse.org/v1/images/"
REQUEST_TIMEOUT_SECONDS = 6


def find_topic_image(query: str) -> Optional[Dict[str, Any]]:
    # searches openverse for one DIAGRAM/illustration matching query (usually
    # topic title, sometimes + unit name for extra context) - never a plain
    # photograph. returns None if nothing found or the request failed for
    # whatever reason. shape when it works:
    #   { url, thumbnail_url, title, creator, license, source_url }
    #
    # categories=illustration is openverse's real filter for diagrams,
    # schematics, infographics, and similar - as opposed to photographs.
    # deliberately no fallback to an unfiltered search if nothing turns up:
    # a topic with no diagram available should show no image, not a random
    # stock photo instead.
    if not query or not query.strip():
        return None

    params = {
        "q": query.strip(),
        "page_size": 1,
        "license_type": "all",
        "mature": "false",
        "categories": "illustration",
    }
    url = f"{OPENVERSE_SEARCH_URL}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NSYA-lesson-image-lookup/1.0"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        # Network unavailable, API down, DNS blocked, timeout, bad JSON —
        # any of these should just mean "no image", not a broken lesson page.
        return None

    results = data.get("results") or []
    if not results:
        return None

    result = results[0]
    return {
        "url": result.get("url"),
        "thumbnail_url": result.get("thumbnail") or result.get("url"),
        "title": result.get("title") or query,
        "creator": result.get("creator") or "",
        "license": result.get("license") or "",
        "source_url": result.get("foreign_landing_url") or result.get("url"),
    }

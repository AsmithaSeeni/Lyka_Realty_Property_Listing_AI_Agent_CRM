import json
import os
import re
import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def parse_price(price_str: str) -> Optional[float]:
    """Parse Arabic numeral price like '65,00,000' or '2,000,000' to float."""
    if not price_str:
        return None
    try:
        clean = price_str.replace(",", "")
        return float(clean)
    except (ValueError, TypeError):
        return None


def parse_area(area_str: str) -> Optional[float]:
    """Parse area string like '2,766 sqft' to sqft float."""
    if not area_str:
        return None
    try:
        match = re.match(r"[\d,]+", area_str)
        if match:
            return float(match.group().replace(",", ""))
    except (ValueError, TypeError):
        return None
    return None


def _find_dataset() -> Optional[str]:
    """Locate the dataset file, searching common locations."""
    candidates = [
        "UAErealestate.json",
        "uaerealestate.json",
        os.path.join(os.path.dirname(__file__), "..", "..", "UAErealestate.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "UAErealestate.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "uaerealestate.json"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


# Cache the loaded dataset in memory (it's read-only)
_properties_cache: Optional[List[Dict[str, Any]]] = None


def load_properties(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load properties from the dataset JSON file (cached after first load)."""
    global _properties_cache
    if _properties_cache is not None:
        return _properties_cache

    file_path = path or _find_dataset()
    if not file_path:
        logger.warning("Dataset file not found")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            _properties_cache = data.get("properties", [])
            logger.info("Loaded %d properties from %s", len(_properties_cache), file_path)
            return _properties_cache
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Failed to load dataset: %s", e)
        return []


def search_properties(
    db: Session,
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    buy_rent: Optional[str] = None,
    max_price: Optional[float] = None,
    min_price: Optional[float] = None,
    min_bedrooms: Optional[int] = None,
    max_bedrooms: Optional[int] = None,
    min_bathrooms: Optional[float] = None,
    max_bathrooms: Optional[float] = None,
    min_area: Optional[float] = None,
    max_area: Optional[float] = None,
    furnishing: Optional[str] = None,
    amenities: Optional[str] = None,
    developer: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Deterministic property search that filters and ranks properties based on available fields.
    Never invents property information; recommendations must come from the dataset.
    """
    all_properties = load_properties()
    
    # Filter properties
    results = []
    for prop in all_properties:
        # Location filter (check if location contains the search term)
        if location:
            loc = prop.get("location", "").lower()
            if location.lower() not in loc:
                continue
        
        # Property type filter
        if property_type:
            pt = prop.get("property_type", "").lower()
            if property_type.lower() not in pt:
                continue
        
        # Buy/Rent filter - dataset doesn't distinguish, so skip or treat all as available
        # The dataset doesn't have buy/rent field, so we don't filter by this
        
        # Price filter
        price_str = prop.get("price", "")
        price = parse_price(price_str)
        if price is not None:
            if max_price is not None and price > max_price:
                continue
            if min_price is not None and price < min_price:
                continue
        
        # Bedrooms filter
        beds_str = str(prop.get("no__of__beds", "")).strip()
        if min_bedrooms is not None or max_bedrooms is not None:
            # Treat "Studio" as 0 bedrooms; exclude unparseable values when filtering
            if beds_str.lower() == "studio":
                beds = 0
            else:
                try:
                    beds = int(float(beds_str))
                except (ValueError, TypeError):
                    continue  # unknown bedroom count -> exclude when filtering
            if min_bedrooms is not None and beds < min_bedrooms:
                continue
            if max_bedrooms is not None and beds > max_bedrooms:
                continue
        
        # Bathrooms filter
        baths_str = prop.get("no_of_baths", "")
        try:
            baths = float(baths_str) if baths_str else None
            if baths is not None and min_bathrooms is not None and baths < min_bathrooms:
                continue
            if baths is not None and max_bathrooms is not None and baths > max_bathrooms:
                continue
        except (ValueError, TypeError):
            pass
        
        # Area filter
        area_str = prop.get("area", "")
        area = parse_area(area_str)
        if area is not None:
            if min_area is not None and area < min_area:
                continue
            if max_area is not None and area > max_area:
                continue
        
        # furnishing filter (search in highlights)
        if furnishing:
            highlights = prop.get("highlights", "").lower()
            if furnishing.lower() not in highlights:
                continue
        
        results.append(prop)
    
    # Sort by relevance - sort by price (ascending) as default
    results.sort(key=lambda p: parse_price(p.get("price", "0")) or 0)
    
    # Apply pagination
    total = len(results)
    paginated = results[offset:offset + limit]
    
    return {
        "results": paginated,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
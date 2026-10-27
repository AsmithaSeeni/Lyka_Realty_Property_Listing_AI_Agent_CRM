"""GET /api/properties/dataset — the dataset-backed browse endpoint.

Why this endpoint exists (property-page fix): the production `properties`
table holds no approved+available rows, so the browse page had nothing to
render, while the 25,082-row UAE dataset (already used by chat search) was
unreachable from the browse UI. This suite pins the contract the frontend
relies on:

  - populated results (the dataset really is served),
  - empty results (honest zero, not an error),
  - filtering (location / type / price / bedrooms),
  - pagination (disjoint pages, stable total, beyond-the-end page),
  - API errors (bad values -> 422; `purpose` rejected loudly instead of
    silently dropped),
  - response-field mapping (normalized keys; nulls for fields the dataset
    does not have; no fabricated images/availability; dataset id space).
"""

DATASET_SIZE = 25082  # pinned by the repo's backend/UAErealestate.json


def _get(client, qs: str = ""):
    return client.get(f"/api/properties/dataset{qs}")


# ---------------------------------------------------------------- populated

def test_populated_results(client):
    res = _get(client, "?limit=5")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == DATASET_SIZE
    assert len(body["results"]) == 5
    assert body["limit"] == 5
    assert body["offset"] == 0


def test_default_page_size_and_price_order(client):
    res = _get(client)
    assert res.status_code == 200
    body = res.json()
    assert body["limit"] == 24
    assert len(body["results"]) == 24
    prices = [row["price"] for row in body["results"]]
    assert prices == sorted(prices), "browse order must be deterministic price ascending"


# ------------------------------------------------------------------- empty

def test_empty_results_are_a_clean_zero(client):
    res = _get(client, "?location=zzz-no-such-place-xyz")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["results"] == []


# ---------------------------------------------------------------- filtering

def test_filter_location(client):
    res = _get(client, "?location=Dubai&limit=48")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    assert all("dubai" in row["location"].lower() for row in body["results"])


def test_filter_property_type(client):
    res = _get(client, "?property_type=villa&limit=48")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    assert all("villa" in row["property_type"].lower() for row in body["results"])


def test_filter_min_price(client):
    res = _get(client, "?min_price=1000000&limit=48")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    assert all(row["price"] >= 1_000_000 for row in body["results"])


def test_filter_min_bedrooms(client):
    res = _get(client, "?min_bedrooms=3&limit=48")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    # rows with unparseable bedrooms are excluded by the server whenever a
    # bedroom filter is active, so every returned row has a comparable int
    assert all(isinstance(row["bedrooms"], int) and row["bedrooms"] >= 3
               for row in body["results"])


def test_studio_rows_are_bedrooms_zero(client):
    res = _get(client, "?min_bedrooms=0&max_bedrooms=0&limit=48")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    assert all(row["bedrooms"] == 0 for row in body["results"])


def test_combined_filters(client):
    res = _get(client, "?location=Dubai&property_type=apartment&min_price=500000&limit=48")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    for row in body["results"]:
        assert "dubai" in row["location"].lower()
        assert "apartment" in row["property_type"].lower()
        assert row["price"] >= 500_000


# --------------------------------------------------------------- pagination

def test_pagination_pages_are_disjoint(client):
    first = _get(client, "?limit=5&offset=0").json()
    second = _get(client, "?limit=5&offset=5").json()
    assert len(first["results"]) == 5
    assert len(second["results"]) == 5
    assert first["total"] == second["total"] == DATASET_SIZE
    ids_a = {row["id"] for row in first["results"]}
    ids_b = {row["id"] for row in second["results"]}
    assert not ids_a & ids_b, "pages must not overlap"


def test_pagination_beyond_the_end_is_empty_with_total(client):
    res = _get(client, "?limit=5&offset=100000")
    assert res.status_code == 200
    body = res.json()
    assert body["results"] == []
    assert body["total"] == DATASET_SIZE


# -------------------------------------------------------------- API errors

def test_invalid_values_return_422(client):
    for qs in ("?limit=0", "?limit=49", "?min_price=-5", "?min_price=abc",
               "?min_bedrooms=-1", "?min_bedrooms=abc", "?offset=-1"):
        res = _get(client, qs)
        assert res.status_code == 422, f"{qs} should be rejected, got {res.status_code}"


def test_purpose_is_rejected_not_silently_dropped(client):
    """The dataset has no sale/rent column: accepting `purpose` and ignoring
    it would silently return the wrong result set."""
    res = _get(client, "?purpose=sale&limit=5")
    assert res.status_code == 422
    assert "purpose" in res.text.lower()
    # ...while purpose-filtered browsing keeps working on the DB endpoint
    db_res = client.get("/api/properties?purpose=sale&limit=1")
    assert db_res.status_code == 200
    assert set(db_res.json()) == {"results", "total", "limit", "offset"}


# --------------------------------------------------------- response mapping

def test_response_field_mapping(client):
    body = _get(client, "?limit=1").json()
    row = body["results"][0]

    expected_keys = {
        "id", "source", "title", "price", "currency", "purpose",
        "price_period", "property_type", "bedrooms", "bathrooms", "area",
        "area_unit", "location", "highlights", "images", "availability",
        "is_demo",
    }
    assert set(row) == expected_keys

    # dataset id space, clearly labeled
    assert isinstance(row["id"], int) and 1 <= row["id"] <= DATASET_SIZE
    assert row["source"] == "dataset"

    # fields that DO exist in the dataset — real values, correct types
    assert isinstance(row["title"], str) and row["title"].strip()
    assert isinstance(row["price"], (int, float)) and row["price"] > 0
    assert row["currency"] == "AED"
    assert isinstance(row["property_type"], str) and row["property_type"]
    assert isinstance(row["bedrooms"], int)
    assert isinstance(row["bathrooms"], (int, float))
    assert isinstance(row["area"], (int, float)) and row["area"] > 0
    assert row["area_unit"] == "sqft"
    assert isinstance(row["location"], str) and row["location"]
    assert isinstance(row["highlights"], str)

    # fields the dataset does NOT have — stated, never invented
    assert row["purpose"] is None
    assert row["price_period"] is None
    assert row["availability"] is None
    assert row["is_demo"] is False
    assert row["images"] == [], "dataset has no image fields; photos are never fabricated"

    # raw dataset column names must not leak into the browse payload
    for raw_key in ("property_id", "no__of__beds", "no_of_baths"):
        assert raw_key not in row


def test_dataset_ids_resolve_through_the_dataset_detail_route(client):
    """A browse card's id must open the DATASET detail page, not a DB record."""
    row = _get(client, "?limit=1").json()["results"][0]
    res = client.get(f"/api/properties/{row['id']}")
    assert res.status_code == 200
    assert res.json()["property_id"] == row["id"]


def test_db_list_endpoint_shape_unchanged(client):
    """The approved+available inventory endpoint keeps its exact contract."""
    res = client.get("/api/properties?limit=1")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"results", "total", "limit", "offset"}

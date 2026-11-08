"""AWS prices: read from the Price List's offer files, tiers applied, snapshot as the fallback."""

import json

import pytest

from mac.pricing import DIMENSIONS, OFFER_URL, PricingError, load_prices, parse_offer, refresh_snapshot, snapshot_prices


def offer(products: dict[str, tuple[str, list[tuple[float, str, str]], str]], published="2026-11-05T16:40:16Z"):
    """A minimal offer file: sku -> (usagetype, [(begin, end, usd)], unit)."""
    data = {"publicationDate": published, "products": {}, "terms": {"OnDemand": {}}}
    for sku, (usagetype, tiers, unit) in products.items():
        data["products"][sku] = {"sku": sku, "attributes": {"usagetype": usagetype}}
        dims = {f"{sku}.T.{i}": {"unit": unit, "beginRange": str(b), "endRange": e, "pricePerUnit": {"USD": u},
                                 "description": f"{usagetype} tier {i}"} for i, (b, e, u) in enumerate(tiers)}
        data["terms"]["OnDemand"][sku] = {f"{sku}.T": {"effectiveDate": "2026-11-01T00:00:00Z", "priceDimensions": dims}}
    return data


def all_offers():
    """Every service DIMENSIONS needs, with AWS's us-east-1 prices as of 2026-11."""
    return {
        "AWSLambda": offer({"GU2Z": ("Request", [(0, "Inf", "0.0000002000")], "Requests"),
                            "TG3M": ("Lambda-GB-Second", [(0, "6000000000", "0.0000166667"),
                                                          (6000000000, "15000000000", "0.0000150000"),
                                                          (15000000000, "Inf", "0.0000133334")], "Lambda-GB-Second"),
                            "K7BX": ("Request-ARM", [(0, "Inf", "0.0000002000")], "Requests"),
                            "72SB": ("Lambda-GB-Second-ARM", [(0, "Inf", "0.0000133334")], "Lambda-GB-Second"),
                            "OTHR": ("Provisioned-GB-Second", [(0, "Inf", "0.000004")], "Lambda-GB-Second")}),
        "AmazonDynamoDB": offer({"4W4Z": ("ReadRequestUnits", [(0, "Inf", "0.0000001250")], "ReadRequestUnits"),
                                 "FGXV": ("WriteRequestUnits", [(0, "Inf", "0.0000006250")], "WriteRequestUnits"),
                                 "F3E2": ("TimedStorage-ByteHrs", [(0, "25", "0.0000000000"), (25, "Inf", "0.25")],
                                          "GB-Mo")}),
        "AmazonCloudWatch": offer({"96K5": ("DataProcessing-Bytes", [(0, "Inf", "0.50")], "GB"),
                                   "JRHJ": ("TimedStorage-ByteHrs", [(0, "Inf", "0.03")], "GB-Mo")}),
    }


def fetcher(offers, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        service = url.split("/aws/")[1].split("/")[0]
        return offers[service]
    return fetch


def test_parse_keeps_sku_rate_codes_dates_and_tiers():
    prices = parse_offer(all_offers()["AmazonDynamoDB"], "AmazonDynamoDB",
                         {"dynamodb.storage_gb_month": "TimedStorage-ByteHrs"}, "https://x/index.json")
    storage = prices["dynamodb.storage_gb_month"]
    assert storage.sku == "F3E2" and storage.unit == "GB-Mo" and storage.source == "aws-price-list"
    assert storage.effective_date == "2026-11-01T00:00:00Z" and storage.publication_date == "2026-11-05T16:40:16Z"
    assert storage.rate_codes == ("F3E2.T.0", "F3E2.T.1") and storage.offer_url == "https://x/index.json"
    assert storage.cost(20) == 0 and storage.cost(25) == 0 and storage.cost(35) == pytest.approx(2.5)


def test_tiers_are_applied_in_order():
    lam = parse_offer(all_offers()["AWSLambda"], "AWSLambda", {"g": "Lambda-GB-Second"}, "u")["g"]
    assert lam.cost(1_000_000) == pytest.approx(16.6667)
    assert lam.cost(7_000_000_000) == pytest.approx(6e9 * 0.0000166667 + 1e9 * 0.000015)


def test_rate_text_is_readable():
    prices = {k: v for o in ("AWSLambda", "AmazonDynamoDB") for k, v in parse_offer(
        all_offers()[o], o, {n: u for n, (s, u) in DIMENSIONS.items() if s == o}, "u").items()}
    assert prices["lambda.requests"].rate_text() == "$0.2 per 1M Requests"
    assert prices["dynamodb.write_units"].rate_text() == "$0.625 per 1M WriteRequestUnits"
    assert prices["dynamodb.storage_gb_month"].rate_text() == "$0 per GB-Mo up to 25, then $0.25 per GB-Mo"


def test_ambiguous_or_missing_products_are_refused():
    data = all_offers()["AWSLambda"]
    with pytest.raises(PricingError, match="expected one On-Demand product, found 0"):
        parse_offer(data, "AWSLambda", {"x": "Nope"}, "u")
    data["products"]["DUP"] = {"sku": "DUP", "attributes": {"usagetype": "Request"}}
    data["terms"]["OnDemand"]["DUP"] = data["terms"]["OnDemand"]["GU2Z"]
    with pytest.raises(PricingError, match="found 2"):
        parse_offer(data, "AWSLambda", {"x": "Request"}, "u")


def test_load_prices_reads_every_dimension_from_the_offer_files():
    calls: list[str] = []
    prices, notes = load_prices("us-east-1", fetch=fetcher(all_offers(), calls))
    assert set(prices) == set(DIMENSIONS) and notes == []
    assert OFFER_URL.format(service="AmazonDynamoDB", region="us-east-1") in calls


def test_unreachable_aws_falls_back_to_the_snapshot_and_says_so(tmp_path):
    snap = tmp_path / "snap.json"
    refresh_snapshot(snap, fetch=fetcher(all_offers()))

    def down(url):
        raise OSError("no network")

    from mac import pricing
    pricing._cache.clear()
    prices, notes = load_prices("us-east-1", fetch=down, snapshot=snap)
    assert prices["lambda.requests"].source == "snapshot" and prices["lambda.requests"].sku == "GU2Z"
    assert "not reachable" in notes[0] and "snapshot saved" in notes[1]


def test_the_committed_snapshot_has_every_price():
    prices = snapshot_prices()
    assert set(prices) == set(DIMENSIONS)
    assert all(p.sku and p.effective_date and p.offer_url.startswith("https://pricing.us-east-1.amazonaws.com/")
               for p in prices.values())


def test_snapshot_for_another_region_is_refused(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"region": "eu-west-1", "prices": {}}), encoding="utf-8")
    with pytest.raises(PricingError, match="eu-west-1"):
        snapshot_prices(snap)
    with pytest.raises(PricingError, match="region"):
        load_prices("eu-west-1", live=True, fetch=fetcher(all_offers()), snapshot=snap)

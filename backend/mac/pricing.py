"""AWS prices, from AWS's official Price List, with the SKU and dates of every price used.

The cost estimate never contains a price someone typed in. Prices come from the public Price
List bulk files (no AWS credentials needed), and each one keeps where it came from: the
service's offer file, the product SKU, the rate code, and when AWS published it. If AWS can't
be reached, the saved copy in `prices_snapshot.json` is used and the estimate says so.
`mise run mac prices --refresh` rewrites that copy from the live files.
"""

import json
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

OFFER_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{service}/current/{region}/index.json"
SNAPSHOT = Path(__file__).resolve().parent / "prices_snapshot.json"
CACHE_SECONDS = 6 * 3600

# Usage types carry a region prefix everywhere except us-east-1 (the landing zone's only region).
REGION_PREFIX = {"us-east-1": ""}

# Every price the calculator may use: name -> (Price List service code, usage type).
DIMENSIONS: dict[str, tuple[str, str]] = {
    "lambda.requests": ("AWSLambda", "Request"),
    "lambda.gb_seconds": ("AWSLambda", "Lambda-GB-Second"),
    "lambda.requests_arm": ("AWSLambda", "Request-ARM"),
    "lambda.gb_seconds_arm": ("AWSLambda", "Lambda-GB-Second-ARM"),
    "dynamodb.read_units": ("AmazonDynamoDB", "ReadRequestUnits"),
    "dynamodb.write_units": ("AmazonDynamoDB", "WriteRequestUnits"),
    "dynamodb.storage_gb_month": ("AmazonDynamoDB", "TimedStorage-ByteHrs"),
    "logs.ingest_gb": ("AmazonCloudWatch", "DataProcessing-Bytes"),
    "logs.storage_gb_month": ("AmazonCloudWatch", "TimedStorage-ByteHrs"),
}


class PricingError(Exception):
    """A price couldn't be found or read."""


@dataclass(frozen=True)
class Tier:
    begin: float
    end: float | None  # None: no upper limit
    usd: float  # per unit


@dataclass(frozen=True)
class Price:
    name: str  # a key of DIMENSIONS
    service: str
    usagetype: str
    unit: str  # as AWS writes it: Requests, Lambda-GB-Second, GB-Mo, ...
    tiers: tuple[Tier, ...]
    sku: str
    rate_codes: tuple[str, ...]
    description: str
    effective_date: str
    publication_date: str
    offer_url: str
    source: str  # "aws-price-list" (fetched now) or "snapshot" (the saved copy)

    def cost(self, quantity: float) -> float:
        """What AWS charges for this quantity, applying the tiers in order."""
        total = 0.0
        for tier in self.tiers:
            if quantity <= tier.begin:
                break
            top = quantity if tier.end is None else min(quantity, tier.end)
            total += (top - tier.begin) * tier.usd
        return total

    def rate_text(self) -> str:
        """e.g. '$0.20 per 1M Requests', or the tiers: '$0 per GB-Mo up to 25, then $0.25'."""
        def one(usd: float) -> str:
            if 0 < usd < 0.001 and "Request" in self.unit:
                return f"${usd * 1_000_000:,.4g} per 1M {self.unit}"
            plain = f"{usd:.10f}".rstrip("0").rstrip(".") or "0"
            return f"${plain} per {self.unit}"
        if len(self.tiers) == 1:
            return one(self.tiers[0].usd)
        parts = [one(self.tiers[0].usd) + f" up to {self.tiers[0].end:,.0f}"]
        parts += [f"then {one(t.usd)}" + (f" up to {t.end:,.0f}" if t.end is not None else "") for t in self.tiers[1:]]
        return ", ".join(parts)

    def to_json(self) -> dict:
        data = asdict(self)
        data["tiers"] = [asdict(t) for t in self.tiers]
        data["rate"] = self.rate_text()
        return data

    @classmethod
    def from_json(cls, data: dict, source: str) -> "Price":
        tiers = tuple(Tier(t["begin"], t["end"], t["usd"]) for t in data["tiers"])
        fields = {k: data[k] for k in ("name", "service", "usagetype", "unit", "sku", "description",
                                       "effective_date", "publication_date", "offer_url")}
        return cls(**fields, tiers=tiers, rate_codes=tuple(data["rate_codes"]), source=source)


def parse_offer(offer: dict, service: str, wanted: dict[str, str], offer_url: str,
                source: str = "aws-price-list") -> dict[str, Price]:
    """The On-Demand prices of the wanted usage types (name -> usage type) in one offer file."""
    by_usagetype: dict[str, list[str]] = {}
    for sku, product in offer.get("products", {}).items():
        usagetype = product.get("attributes", {}).get("usagetype")
        if usagetype in wanted.values():
            by_usagetype.setdefault(usagetype, []).append(sku)
    prices = {}
    for name, usagetype in wanted.items():
        skus = [s for s in by_usagetype.get(usagetype, []) if s in offer.get("terms", {}).get("OnDemand", {})]
        if len(skus) != 1:
            raise PricingError(f"{service} {usagetype}: expected one On-Demand product, found {len(skus)}")
        sku = skus[0]
        terms = list(offer["terms"]["OnDemand"][sku].values())
        if len(terms) != 1:
            raise PricingError(f"{service} {usagetype}: expected one On-Demand term, found {len(terms)}")
        term = terms[0]
        dims = sorted(term["priceDimensions"].items(), key=lambda kv: float(kv[1].get("beginRange", 0)))
        tiers = tuple(Tier(float(d.get("beginRange", 0)),
                           None if d.get("endRange", "Inf") == "Inf" else float(d["endRange"]),
                           float(d["pricePerUnit"]["USD"])) for _, d in dims)
        units = {d["unit"] for _, d in dims}
        if len(units) != 1:
            raise PricingError(f"{service} {usagetype}: tiers in different units {sorted(units)}")
        prices[name] = Price(
            name=name, service=service, usagetype=usagetype, unit=units.pop(), tiers=tiers, sku=sku,
            rate_codes=tuple(rc for rc, _ in dims), description=dims[-1][1].get("description", ""),
            effective_date=term.get("effectiveDate", ""), publication_date=offer.get("publicationDate", ""),
            offer_url=offer_url, source=source)
    return prices


def _wanted(region: str) -> dict[str, dict[str, str]]:
    if region not in REGION_PREFIX:
        raise PricingError(f"no usage-type prefix known for region {region}")
    prefix = REGION_PREFIX[region]
    per_service: dict[str, dict[str, str]] = {}
    for name, (service, usagetype) in DIMENSIONS.items():
        per_service.setdefault(service, {})[name] = prefix + usagetype
    return per_service


def _fetch(url: str, timeout: int = 30) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "mac-cost-calculator"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed AWS URL
        return json.loads(response.read().decode("utf-8"))


_cache: dict[str, tuple[float, dict[str, Price]]] = {}


def live_prices(region: str = "us-east-1", fetch=_fetch, use_cache: bool = True) -> dict[str, Price]:
    """Every price in DIMENSIONS, from AWS's current offer files. Raises PricingError."""
    if use_cache and region in _cache and time.time() - _cache[region][0] < CACHE_SECONDS:
        return _cache[region][1]
    prices: dict[str, Price] = {}
    for service, wanted in _wanted(region).items():
        url = OFFER_URL.format(service=service, region=region)
        try:
            offer = fetch(url)
        except Exception as e:  # noqa: BLE001 - network, HTTP or JSON: all mean "not reachable"
            raise PricingError(f"couldn't read {url}: {e}") from e
        prices.update(parse_offer(offer, service, wanted, url))
    _cache[region] = (time.time(), prices)
    return prices


def snapshot_prices(path: Path = SNAPSHOT, region: str = "us-east-1") -> dict[str, Price]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PricingError(f"no usable price snapshot at {path}: {e}") from e
    if data.get("region") != region:
        raise PricingError(f"the price snapshot is for {data.get('region')}, not {region}")
    prices = {name: Price.from_json(p, "snapshot") for name, p in data.get("prices", {}).items()}
    missing = sorted(set(DIMENSIONS) - set(prices))
    if missing:
        raise PricingError(f"the price snapshot has no {', '.join(missing)}; run `mise run mac prices --refresh`")
    return prices


def load_prices(region: str = "us-east-1", live: bool = True, fetch=_fetch,
                snapshot: Path = SNAPSHOT) -> tuple[dict[str, Price], list[str]]:
    """(prices, notes). Live prices when AWS answers, else the snapshot, with a note saying so."""
    notes: list[str] = []
    _wanted(region)  # an unsupported region is refused, never answered from a snapshot
    if live:
        try:
            return live_prices(region, fetch), notes
        except PricingError as e:
            notes.append(f"AWS Price List not reachable ({e}); used the saved snapshot")
    prices = snapshot_prices(snapshot, region)
    fetched = json.loads(Path(snapshot).read_text(encoding="utf-8")).get("fetched", "")
    notes.append(f"prices from the snapshot saved {fetched}")
    return prices, notes


def refresh_snapshot(path: Path = SNAPSHOT, region: str = "us-east-1", fetch=_fetch) -> dict[str, Price]:
    prices = live_prices(region, fetch, use_cache=False)
    data = {"region": region, "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": "Written by `mise run mac prices --refresh` from AWS's public Price List. Don't edit by hand.",
            "prices": {name: p.to_json() for name, p in sorted(prices.items())}}
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return prices

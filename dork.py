#!/usr/bin/env python3
"""Ambil URL/domain dari hasil pencarian keyword publik."""

from __future__ import annotations

import argparse
import base64
import html
import ipaddress
import random
import socket
import sys
import time
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import urllib.error
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT = 15
DEFAULT_MAX_RESULTS = 100
DEFAULT_EXTRA_PAGES = 10
DEFAULT_DELAY = 0.2
REQUEST_RETRIES = 3
RETRY_BACKOFF = 1.0
DEFAULT_KEYWORDS_FILE = Path(__file__).with_name("keyword.txt")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("scan_results")
MAX_THREADS = 10
SEARCH_REGIONS = {
    "ID": ("id-ID", "id"),
    "US": ("en-US", "us"),
    "CA": ("en-CA", "ca"),
    "MX": ("es-MX", "mx"),
    "BR": ("pt-BR", "br"),
    "AR": ("es-AR", "ar"),
    "CL": ("es-CL", "cl"),
    "CO": ("es-CO", "co"),
    "PE": ("es-PE", "pe"),
    "UK": ("en-GB", "gb"),
    "IE": ("en-IE", "ie"),
    "DE": ("de-DE", "de"),
    "FR": ("fr-FR", "fr"),
    "IT": ("it-IT", "it"),
    "ES": ("es-ES", "es"),
    "NL": ("nl-NL", "nl"),
    "BE": ("nl-BE", "be"),
    "CH": ("de-CH", "ch"),
    "AT": ("de-AT", "at"),
    "PL": ("pl-PL", "pl"),
    "SE": ("sv-SE", "se"),
    "NO": ("nb-NO", "no"),
    "DK": ("da-DK", "dk"),
    "FI": ("fi-FI", "fi"),
    "PT": ("pt-PT", "pt"),
    "CZ": ("cs-CZ", "cz"),
    "RO": ("ro-RO", "ro"),
    "HU": ("hu-HU", "hu"),
    "GR": ("el-GR", "gr"),
    "UA": ("uk-UA", "ua"),
    "RU": ("ru-RU", "ru"),
    "TR": ("tr-TR", "tr"),
    "IN": ("en-IN", "in"),
    "IL": ("he-IL", "il"),
    "SA": ("ar-SA", "sa"),
    "EG": ("ar-EG", "eg"),
    "JP": ("ja-JP", "jp"),
    "KR": ("ko-KR", "kr"),
    "TW": ("zh-TW", "tw"),
    "HK": ("zh-HK", "hk"),
    "SG": ("en-SG", "sg"),
    "MY": ("ms-MY", "my"),
    "TH": ("th-TH", "th"),
    "VN": ("vi-VN", "vn"),
    "PH": ("en-PH", "ph"),
    "AU": ("en-AU", "au"),
    "NZ": ("en-NZ", "nz"),
    "ZA": ("en-ZA", "za"),
    "AE": ("en-AE", "ae"),
}
SEARCH_HOSTS = {
    "duckduckgo.com",
    "www.duckduckgo.com",
    "html.duckduckgo.com",
    "bing.com",
    "www.bing.com",
}
USER_AGENT = "KeywordDomainScanner/1.0 (public research)"


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.result_links: list[str] = []
        self._bing_result_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag.lower() == "li" and "b_algo" in classes:
            self._bing_result_depth += 1
        if tag.lower() != "a":
            return

        href = attributes.get("href")
        if not href:
            return
        link = html.unescape(href)
        self.links.append(link)
        link_path = urlparse(link).path
        if (
            self._bing_result_depth
            or "result__a" in classes
            or "b_algo" in classes
            or link_path.startswith("/ck/")
        ):
            self.result_links.append(link)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "li" and self._bing_result_depth:
            self._bing_result_depth -= 1


def normalize_url(value: str) -> str | None:
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "",
         parsed.query, "")
    )


def unwrap_result_url(value: str) -> str | None:
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    target = query.get("uddg", [None])[0] or query.get("url", [None])[0]
    bing_target = query.get("u", [None])[0]
    if not target and bing_target and bing_target.startswith("a1"):
        encoded = bing_target[2:]
        encoded += "=" * (-len(encoded) % 4)
        try:
            target = base64.urlsafe_b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            target = None
    return normalize_url(target or value)


def search_queries(keyword: str) -> list[str]:
    """Return equivalent queries used to reach different ranking buckets."""
    queries = [keyword]
    if " " in keyword.strip():
        quoted = f'"{keyword.strip()}"'
        queries.append(quoted)
    return queries


def search_keyword(
    keyword: str,
    max_results: int,
    timeout: int,
    delay: float = 0,
    language: str = "en-US",
    market: str = "us",
    extra_pages: int = DEFAULT_EXTRA_PAGES,
) -> list[str]:
    page_results: list[list[str]] = []
    page_size = 10
    errors: list[str] = []
    requested_pages = (max_results + page_size - 1) // page_size
    page_count = requested_pages + extra_pages
    page_offsets = list(range(0, page_count * page_size, page_size))

    for offset in page_offsets:
        offset_results: list[str] = []
        offset_seen: set[str] = set()
        requests: list[tuple[str, str]] = []
        for query in search_queries(keyword):
            requests.extend(
                (
                    (
                        "https://www.bing.com/search?",
                        urlencode(
                            {
                                "q": query,
                                "first": offset + 1,
                                "count": page_size,
                                "setlang": language,
                                "cc": market,
                            }
                        ),
                    ),
                    (
                        "https://html.duckduckgo.com/html?",
                        urlencode({"q": query, "s": offset, "dc": offset + 1}),
                    ),
                )
            )

        def fetch_page(endpoint: tuple[str, str]) -> tuple[str, str | None]:
            base_url, encoded_parameters = endpoint
            for attempt in range(REQUEST_RETRIES):
                try:
                    request = Request(
                        base_url + encoded_parameters,
                        headers={"User-Agent": USER_AGENT},
                    )
                    with urlopen(request, timeout=timeout) as response:
                        return base_url, response.read().decode(
                            "utf-8", errors="replace"
                        )
                except urllib.error.HTTPError as error:
                    if error.code not in {429, 500, 502, 503, 504}:
                        return f"{base_url.split('/')[2]}: HTTP {error.code}", None
                    if attempt == REQUEST_RETRIES - 1:
                        return f"{base_url.split('/')[2]}: HTTP {error.code}", None
                except OSError as error:
                    if attempt == REQUEST_RETRIES - 1:
                        return f"{base_url.split('/')[2]}: {error}", None
                time.sleep(RETRY_BACKOFF * (attempt + 1))
            return f"{base_url.split('/')[2]}: request failed", None

        with ThreadPoolExecutor(max_workers=len(requests)) as page_executor:
            pages = list(page_executor.map(fetch_page, requests))

        for source, body in pages:
            if body is None:
                errors.append(source)
                continue
            parser = LinkParser()
            parser.feed(body)
            for link in parser.result_links:
                url = unwrap_result_url(link)
                hostname = (urlparse(url).hostname or "").lower() if url else ""
                if not url or hostname in SEARCH_HOSTS or url in offset_seen:
                    continue
                offset_seen.add(url)
                offset_results.append(url)
        if offset_results:
            page_results.append(offset_results)
        if delay and offset + page_size < page_count * page_size:
            time.sleep(delay)

    if not page_results and errors:
        raise OSError("; ".join(errors[-2:]))


    results: list[str] = []
    seen: set[str] = set()
    page_index = 0
    while page_results and len(results) < max_results:
        page = page_results[page_index % len(page_results)]
        if page:
            url = page.pop(0)
            if url not in seen:
                seen.add(url)
                results.append(url)
        page_results = [page for page in page_results if page]
        page_index += 1
    return results


def domain_from_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def resolve_domain_ips(domain: str, timeout: int) -> list[str]:
    try:
        ipaddress.ip_address(domain)
        return [domain]
    except ValueError:
        pass

    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        addresses: set[str] = {
            str(result[4][0])
            for result in socket.getaddrinfo(domain, None, socket.AF_INET)
        }
        return sorted(addresses, key=ipaddress.ip_address)
    except OSError:
        return []
    finally:
        socket.setdefaulttimeout(previous_timeout)


def load_keywords(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig") as input_file:
        return list(dict.fromkeys(
            line.strip() for line in input_file
            if line.strip() and not line.lstrip().startswith("#")
        ))


def choose_regions() -> list[str]:
    region_names = list(SEARCH_REGIONS)
    print("\nPilih region pencarian:")
    for index, region in enumerate(region_names, start=1):
        print(f"  {index:>2}. {region}")
    print("  0. Semua region")

    while True:
        selection = input(
            "\nMasukkan nomor region (contoh: 1 atau 1,3,10): "
        ).strip()
        if not selection:
            print("[!] Pilih minimal satu region.")
            continue
        if selection == "0":
            return region_names

        values = [value.strip() for value in selection.replace(",", " ").split()]
        if not all(value.isdigit() for value in values):
            print("[!] Masukkan nomor saja, dipisahkan koma atau spasi.")
            continue
        indexes = list(dict.fromkeys(int(value) for value in values))
        if any(index < 1 or index > len(region_names) for index in indexes):
            print(f"[!] Nomor harus antara 1 dan {len(region_names)}, atau 0.")
            continue
        return [region_names[index - 1] for index in indexes]


def scan_keywords(
    keywords: list[str],
    max_results: int,
    timeout: int,
    delay: float,
    output_dir: Path | None = None,
    workers: int = MAX_THREADS,
    regions: dict[str, tuple[str, str]] | None = None,
    extra_pages: int = DEFAULT_EXTRA_PAGES,
) -> tuple[list[str], list[str]]:
    urls: list[str] = []
    domains: list[str] = []
    ips: list[str] = []
    domain_ip_pairs: list[str] = []
    seen_urls: set[str] = set()
    seen_domains: set[str] = set()
    seen_ips: set[str] = set()
    seen_domain_ip_pairs: set[str] = set()

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        urls_file = output_dir / "urls.txt"
        domains_file = output_dir / "domains.txt"
        ips_file = output_dir / "ips.txt"
        domain_ip_file = output_dir / "domain_ip.txt"
        urls_file.write_text("", encoding="utf-8")
        domains_file.write_text("", encoding="utf-8")
        ips_file.write_text("", encoding="utf-8")
        domain_ip_file.write_text("", encoding="utf-8")
    else:
        urls_file = domains_file = ips_file = domain_ip_file = None

    def scan_one(
        keyword: str, region: str, language: str, market: str
    ) -> tuple[str, str, list[str]]:
        if delay:
            time.sleep(random.uniform(0, delay))
        return keyword, region, search_keyword(
            keyword, max_results, timeout, delay, language, market, extra_pages
        )

    selected_regions = regions or SEARCH_REGIONS
    total_jobs = len(keywords) * len(selected_regions)
    job_iter = (
        (keyword, region, language, market)
        for keyword in keywords
        for region, (language, market) in selected_regions.items()
    )
    worker_count = min(workers, max(1, total_jobs))
    dns_workers = min(32, max(1, worker_count * 2))
    with (
        ThreadPoolExecutor(max_workers=worker_count) as executor,
        ThreadPoolExecutor(max_workers=dns_workers) as dns_executor,
    ):

        pending: dict[
            Future[tuple[str, str, list[str]]], tuple[str, str]
        ] = {}
        for _ in range(worker_count * 2):
            try:
                keyword, region, language, market = next(job_iter)
            except StopIteration:
                break
            future = executor.submit(scan_one, keyword, region, language, market)
            pending[future] = (keyword, region)

        index = 0
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            future = next(iter(completed))
            index += 1
            keyword, region = pending.pop(future)
            try:
                _, _, found_urls = future.result()
            except Exception as error:
                print(f"[ERROR] {keyword}: {error}", file=sys.stderr, flush=True)
                found_urls = []
            new_urls: list[str] = []
            new_domains: list[str] = []
            new_ips: list[str] = []
            new_domain_ip_pairs: list[str] = []
            for url in found_urls:
                if url not in seen_urls:
                    seen_urls.add(url)
                    urls.append(url)
                    new_urls.append(url)
                domain = domain_from_url(url)
                if domain and domain not in seen_domains:
                    seen_domains.add(domain)
                    domains.append(domain)
                    new_domains.append(domain)
            print(
                f"[{index}/{total_jobs}] {region}/{keyword}: "
                f"{len(found_urls)} URL, total {len(domains)} domain",
                flush=True,
            )
            dns_futures = {
                domain: dns_executor.submit(resolve_domain_ips, domain, timeout)
                for domain in new_domains
            }
            future_domains = {
                dns_future: domain
                for domain, dns_future in dns_futures.items()
            }
            for dns_future in as_completed(future_domains):
                domain = future_domains[dns_future]
                for ip in dns_future.result():
                    if ip not in seen_ips:
                        seen_ips.add(ip)
                        ips.append(ip)
                        new_ips.append(ip)
                    pair = f"{domain} -> {ip}"
                    if pair not in seen_domain_ip_pairs:
                        seen_domain_ip_pairs.add(pair)
                        domain_ip_pairs.append(pair)
                        new_domain_ip_pairs.append(pair)
            if urls_file and new_urls:
                with urls_file.open("a", encoding="utf-8") as output_file:
                    output_file.write("\n".join(new_urls) + "\n")
            if domains_file and new_domains:
                with domains_file.open("a", encoding="utf-8") as output_file:
                    output_file.write("\n".join(new_domains) + "\n")
            if ips_file and new_ips:
                with ips_file.open("a", encoding="utf-8") as output_file:
                    output_file.write("\n".join(new_ips) + "\n")
            if domain_ip_file and new_domain_ip_pairs:
                with domain_ip_file.open("a", encoding="utf-8") as output_file:
                    output_file.write("\n".join(new_domain_ip_pairs) + "\n")
            if found_urls:
                print(
                    f"    [+] Hasil sementara ditulis: "
                    f"{len(urls)} URL / {len(domains)} domain",
                    flush=True,
                )
                try:
                    next_job = next(job_iter)
                except StopIteration:
                    continue
                next_keyword, next_region, next_language, next_market = next_job
                next_future = executor.submit(
                    scan_one,
                    next_keyword,
                    next_region,
                    next_language,
                    next_market,
                )
                pending[next_future] = (next_keyword, next_region)
            else:
                try:
                    next_job = next(job_iter)
                except StopIteration:
                    continue
                next_keyword, next_region, next_language, next_market = next_job
                next_future = executor.submit(
                    scan_one,
                    next_keyword,
                    next_region,
                    next_language,
                    next_market,
                )
                pending[next_future] = (next_keyword, next_region)
    return urls, domains


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan keyword publik menjadi URL dan domain."
    )
    parser.add_argument("keywords", nargs="*", help="Keyword yang ingin dicari")
    parser.add_argument(
        "-f", "--file", type=Path,
        help="File satu keyword per baris (default: keyword.txt di folder script)",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT_DIR,
        help="Folder output (default: scan_results di folder script)",
    )
    parser.add_argument("--max-results", type=int, default=None)
    parser.add_argument(
        "--extra-pages",
        type=int,
        default=DEFAULT_EXTRA_PAGES,
        help=(
            "Tambahan halaman yang dijelajahi di luar kuota max-results "
            f"(default: {DEFAULT_EXTRA_PAGES})"
        ),
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--workers", type=int, default=MAX_THREADS)
    parser.add_argument(
        "--regions",
        nargs="+",
        metavar="REGION",
        help=(
            "Region pencarian, satu atau lebih kode (contoh: --regions ID US SG). "
            "Default: semua region"
        ),
    )
    args = parser.parse_args()
    requested_max_results = (
        args.max_results if args.max_results is not None else DEFAULT_MAX_RESULTS
    )

    keywords = list(dict.fromkeys(args.keywords))
    keyword_file = args.file or DEFAULT_KEYWORDS_FILE
    if keyword_file.is_file():
        keywords.extend(load_keywords(keyword_file))
        keywords = list(dict.fromkeys(keywords))
        print(f"[*] File keyword: {keyword_file}", flush=True)
    elif args.file:
        parser.error(f"file keyword tidak ditemukan: {keyword_file}")
    if not keywords:
        parser.error("masukkan keyword atau gunakan --file")
    selected_region_names = (
        [name.upper() for name in args.regions]
        if args.regions
        else choose_regions()
    )
    invalid_regions = [
        name for name in selected_region_names if name not in SEARCH_REGIONS
    ]
    if invalid_regions:
        parser.error(
            "region tidak dikenal: "
            + ", ".join(invalid_regions)
            + ". Pilihan: "
            + ", ".join(SEARCH_REGIONS)
        )
    if (
        requested_max_results < 1
        or args.extra_pages < 0
        or args.timeout < 1
        or args.delay < 0
        or args.workers < 1
    ):
        parser.error(
            "--max-results/--timeout/--workers harus > 0, "
            "--extra-pages tidak boleh negatif, dan --delay >= 0"
        )

    print(f"[*] Memproses {len(keywords)} keyword...", flush=True)
    selected_regions = {
        name: SEARCH_REGIONS[name] for name in dict.fromkeys(selected_region_names)
    }
    total_jobs = len(keywords) * len(selected_regions)
    effective_max_results = requested_max_results
    effective_extra_pages = args.extra_pages
    effective_delay = args.delay
    if total_jobs > 5000:
        estimated_requests = (
            total_jobs
            * 2
            * 2
            * (
                (effective_max_results + 9) // 10
                + effective_extra_pages
            )
        )
        print(
            "[!] Scan besar terdeteksi: "
            f"{total_jobs:,} pekerjaan, sekitar {estimated_requests:,} request.",
            flush=True,
        )
        print(
            "[*] Parameter scan dipertahankan sesuai konfigurasi. "
            f"max-results={effective_max_results}, "
            f"extra-pages={effective_extra_pages}, delay={effective_delay}.",
            flush=True,
        )
    print(
        f"[*] Region: {', '.join(selected_regions)} "
        f"({len(selected_regions)} region, "
        f"{total_jobs} pekerjaan)",
        flush=True,
    )
    urls, domains = scan_keywords(
        keywords, effective_max_results, args.timeout, effective_delay, args.output,
        max(args.workers, 20) if total_jobs > 5000 else args.workers,
        selected_regions, effective_extra_pages,
    )
    args.output.mkdir(parents=True, exist_ok=True)

    (args.output / "urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")
    (args.output / "domains.txt").write_text("\n".join(domains) + "\n", encoding="utf-8")
    print(f"[+] Selesai: {len(urls)} URL, {len(domains)} domain")
    print(
        f"[+] Output: {args.output / 'urls.txt'}, "
        f"{args.output / 'domains.txt'}, {args.output / 'ips.txt'}, "
        f"dan {args.output / 'domain_ip.txt'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

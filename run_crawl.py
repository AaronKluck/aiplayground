import argparse
from aiplay.crawl import Crawler


def parse_args():
    parser = argparse.ArgumentParser(description="Web crawler script")

    # Required argument
    parser.add_argument("url", help="Starting URL to crawl")

    # Optional arguments
    parser.add_argument(
        "--workers", type=int, default=8, help="Number of worker threads (default: 8)"
    )
    parser.add_argument(
        "--max-count",
        type=int,
        help="Maximum number of pages to crawl before stopping early (default: unset, indicating no limit)",
    )
    parser.add_argument(
        "--max-url-params",
        type=int,
        help="Maximum number of URL parameters to preserve (default: unset, indicating no limit)",
    )
    parser.add_argument(
        "--max-components",
        type=int,
        default=10,
        help="Maximum number of components allowed in a crawled URL (default: 10)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=5,
        help="Maximum clicks away from origin page (default: 5)",
    )
    parser.add_argument(
        "--stale-hours",
        type=int,
        default=24,
        help="After completion, records older than these many hours will be culled (default: 24)",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    crawler = Crawler(
        args.url,
        args.workers,
        args.stale_hours,
        max_count=args.max_count,
        max_components=args.max_components,
        max_depth=args.max_depth,
        max_params=args.max_url_params,
    )
    crawler.run()

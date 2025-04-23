from hashlib import sha3_256

from aiplay.crawl import Crawler
from aiplay.db.schema import create_schema
from aiplay.gemini.client import cache_inline_file, query, query_inline_file
from aiplay.util.download import download_file, download_rendered

SAMPLE_DOC_1 = "https://sciotownship.granicus.com/DocumentViewer.php?file=sciotownship_10361e2f7845c52c94ea74f36a70daaa.pdf"
SAMPLE_DOC_2 = "https://sciotownship.granicus.com/DocumentViewer.php?file=sciotownship_971b781dd3d28b5cb385afec6c5c49c2.pdf"
SAMPLE_SITE_1 = "https://www.sciotownship.org/community/advanced-components/list-detail-pages/elected-officials"

BASE_SITE_1 = "https://www.a2gov.org/"
BASE_SITE_2 = "https://bozeman.net/"
BASE_SITE_3 = "https://asu.edu/"
BASE_SITE_4 = "https://boerneisd.net/"


def ai_stuff():
    """
    data, mime = download_file(SAMPLE_DOC_2)
    # cache_name = cache_inline_file("Analyze this document. The next few prompts will ask questions about it", data, mime)
    print(query_inline_file("What is the document about?", data, mime))
    print(query_inline_file("Who was involved in the meeting?", data, mime))
    print(
        query_inline_file(
            "From this document, what initiatives might the municipality be undertaking in the near future? Specifically focus on those that an outside agency might win a contract for.",
            data,
            mime,
        )
    )
    """
    boze = download_rendered(BASE_SITE_2)
    assert "<h1>Access Denied</h1>" not in boze

    h1 = download_rendered(BASE_SITE_1)
    h3 = download_rendered(BASE_SITE_3)
    h4 = download_rendered(BASE_SITE_4)
    html = download_rendered(SAMPLE_SITE_1)
    print(
        query_inline_file(
            "Look at this web content and find contacts. List their name, title, and phone number. If an email address is found, list it, but otherwise put <unknown>.",
            html.encode(),
            "text/html",
        )
    )


def crawl():
    create_schema()

    # crawler = Crawler("https://www.a2gov.org/")
    crawler = Crawler("https://bozeman.net/")
    crawler.run()


def compare():
    url_1 = (
        "https://www.bozeman.net/Home/Components/Calendar/Event/34759/3126?backlist=%2f"
    )
    url_2 = "https://www.bozeman.net/Home/Components/Calendar/Event/34759/3126?backlist=%2fhome"
    url_3 = "https://www.a2gov.org/"
    url_4 = "https://www.a2gov.org/finance-and-administrative-services/treasury/"

    html_1 = download_rendered(url_4, True)
    with open("test1.html", "w", encoding="utf-8") as f:
        f.write(html_1)
    print(sha3_256(html_1.encode()).hexdigest())

    # try again
    html_2 = download_rendered(url_4, True)
    with open("test2.html", "w", encoding="utf-8") as f:
        f.write(html_2)
    print(sha3_256(html_2.encode()).hexdigest())


if __name__ == "__main__":
    crawl()

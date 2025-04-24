from aiplay.crawl import Crawler
from aiplay.db.schema import create_schema
from aiplay.ai.inspect import inspect_links
from aiplay.ai.gemini.base import query_inline_file
from aiplay.ai.types import AIModel
from aiplay.util.download import download_rendered
from aiplay.util.html import extract_links

SAMPLE_DOC_1 = "https://sciotownship.granicus.com/DocumentViewer.php?file=sciotownship_10361e2f7845c52c94ea74f36a70daaa.pdf"
SAMPLE_DOC_2 = "https://sciotownship.granicus.com/DocumentViewer.php?file=sciotownship_971b781dd3d28b5cb385afec6c5c49c2.pdf"
SAMPLE_SITE_1 = "https://www.sciotownship.org/community/advanced-components/list-detail-pages/elected-officials"
SAMPLE_SITE_2 = (
    "https://www.a2gov.org/parks-and-recreation/give-365/youth-volunteer-opportunities/"
)

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

    # crawler = Crawler(BASE_SITE_1)  # a2gov
    # crawler = Crawler(BASE_SITE_2)  # bozeman
    # crawler = Crawler(BASE_SITE_3)  # asu
    crawler = Crawler(BASE_SITE_4)  # boerneisd
    crawler.run()


def deconstruct_test():
    url_4 = BASE_SITE_3
    html_4 = download_rendered(url_4)
    with open("test5.html", "w") as f:
        f.write(html_4)
    links = extract_links(BASE_SITE_3, html_4)
    kw_links = inspect_links(AIModel.OPENAI, links)
    print(kw_links)


if __name__ == "__main__":
    crawl()
    # link_test()
    # deconstruct_test()

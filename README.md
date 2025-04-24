# Installation / Setup
1. Set up a fresh Python environment in your shell (optional).
1. Run `git update-index --assume-unchanged aiplay/ai/gemini/key.txt aiplay/ai/openai/key.txt` so that local changes to these files won't be detected.
1. Visit https://aistudio.google.com/app/apikey and click `Create API key`. Copy the generated value into `aiplay/gemini.key.txt`.
1. Run `pip install -r requirements.txt`.
1. Run `pywright install`.


# Design
Taking notes on the shape of the algorithm. At the time I'm starting this, I already have a basic crawler that looks for links *within the same domain* that don't violate `robots.txt` and queues them up to be processed by one of many worker threads.

>[!NOTE]
> So far my biggest headache has been websites that _really don't want to be crawled_ and send back Access Denied pages (the prime example being https://bozeman.net, one of the test websites listed in the challenge.) This was solved by trying multiple different browser drivers (and sticking with the first that works) along with the `playwright_stealth` module to make my headless mode look more real.

So with that basic crawling pattern done, here's what's next. If anything changes, I'll leave the notes here in ~~strikethrough~~ to better show my process.

## Big Idea
The idea is to store a record of each page visited, along with a hash of its contents. The next time we perform the crawl, these hashes will indicate whether the contents have changed since; if not, then we can skip "processing" of that page, which is to say, we skip asking the AI anything about it, as that's the slowest and most expensive piece of the whole procedure. We still recurse through to child links, because _those_ might have changed.

## Data Model
I'm going to use SQLite for this. I've used it before (albeit from C++, not from Python), it doesn't require any external processes or API calls.

There will be four tables for the base functionality. (I may add more if I get to any stretch goals.)

### Site Table
This represents the entrypoint to the crawl and will always be a FQDN. In a real product, this would have extra fields tying it to customer data, but here, it mostly just keeps the timestamp of the last run of the crawler on that site. Any timestamp column in another table from the most recent run will use this same value (even if the run takes a while), so that the run itself is uniquely identified.

- `id`: primary key
- `url`: the base URL where the crawl begins
  - unique constraint
- `crawl_time`: the timestamp the last crawl began at

### Page Table
This represents each individual page within a site. Each page visited is represented here, regardless of whether it is deemed interesting or not. I considered saving storage by having only the "path" that follows the base URL of the site, but eventually decided that this only complicated matters (requiring a `JOIN` just to get the full URL, for example), so I kept it denormalized.

- `id`: primary key
- `site_id`: foreign key to `site.id` w/ `ON DELETE CASCADE`
  - part of compound unique constraint, along with `url`
- `url`: URL of the specific page
  - part of compound unique constraint, along with `site_id`
- `hash`: MD5 (or something) of the page contents
- `crawl_time`: the timestamp of the crawl that read the page w/ this hash

> [!NOTE]
> You may notice that these last two tables have intger primary keys, even though they also have unique constraints that _could_ act as the primary keys. This is for performance. Indexes on integers are a lot faster than those on strings, so it's better to have a foreign key to an integer, especially during a `JOIN`. 

> [!IMPORTANT]
> At the end of a crawl, any pages with a `crawl_time` less than that of the site itself were not seen during this crawl and can be deleted. (Or, in a real product, archived somehow, or have any scorings associated with them reduced, et cetera.) If a page was seen the previous crawl, its `crawl_time` will be updated to the new one.

### Link Table
This represents "high value links". Not every page will have them.

- `id`: primary key
- `site_id`: foreign key to `site.id` w/ `ON DELETE CASCADE`
  - This is a bit redundant, since it's implied by the below column. However, it saves us a lot of extra `JOIN`'ing when we're listing by site.
- `page_id`: foreign key to `page.id` w/ `ON DELETE CASCADE`
- `url`: URL that the link points to
- `score`: a relevance score
- `keywords`: delimited list of keywords contributing to the link being high-value
- `crawl_time`: the timestamp of the crawl that noted this link

The `keywords` column will have a single-character delimiter that splits each keyword as well as pads the entire string. For example, if the delimiter is `;`, then a fake `keywords` entry might look like `;foo;bar;cat;dog;`. This allows query clauses such as `keywords LIKE '%;bar;%'` to find all links that were chosen due to keyword "bar".

The downside of this implementation is that the column can't be indexed effectively. Instead, we'll rely on foreign keys to `page` and/or `site` and assume that the number of links in a single page or site are reasonably small enough that doing some filtering over them isn't a big deal. Another way to do this would be a whole other 1:N table representing the relation. This could be then indexed on the keyword (and probably also duplicate the `site_id` column). Or, if there are properties associated with those keywords, you could have two extra tables; one that relates a site to a keyword, and another that relates a link to that site-keyword combo.

## Algorithm
- At the beginning of a crawl, the `site` table is queried for the domain in question, then updated with a new `crawl_time` (the value of which will be propagated to other records as we go along).
- The `page` table will be queried. Every single page record for that 
site will be grabbed and kept in memory so that the database isn't being constantly spammed.
    - This makes an assumption about scalability. If there are practical memory limits, I might consider processing only chunks of the namespace at a time - say, those with a prefix between "{site}/aaa" and "{site}/baa", alphabetically. Or just loading the first X many from the database to determine the range. Now, this then requires that the pages you _process_ fall into this range as well for it to do any good, so they'd have to be queued up on disk in an indexed fashion. Even then, I foresee this tactic having starvation issues. Not an easy problem - luckily, I don't plan to solve it here.
- As we read the current page with `playwright`, the rendered content is hashed. If we already know about the current page in memory (i.e. from the aforementioned database query), then we compare the hash. If it's different, or if we didn't already know about the page, then we proceed to the AI inspection step. Otherwise, the page's `crawl_time` is updated in memory and then upserted into the database.
- If we've deemed that the page will be inspected by AI, then the page's rendered content is sent to Gemini and a series of questions are asked about it to produce a list of relevant links and their scores. These are upserted into the `link` table such that, if it already existed, it simply results in the `score`, `comment`, and `crawl_time` being updated. Finally, we upsert into the `page` table, such that if it already existed, we're merely updating the `hash` and `crawl_time`.
    - I'm hand-waving over a pretty big piece of complexity here. The prompting and scoring are their own big thing that I'll figure out later. Luckily, that's can all be self-contained, which is why I'm designing the rest of the application around it first.
- Regardless of whether the page was inspected by AI, the hyperlinks within it will be traversed, producing the next round of URLs to process.
- If the link has been processed already, it'll be skipped. If 
it's not an HTTP or HTTPS protocol, it'll be skipped. If it points somewhere outside of the site's domain, it'll be skipped. If crawling it is forbidden by `robots.txt`, it'll be skipped.
- After the entire crawl is completed (i.e. it exhausts all links internal to the site), we can clean up stale entries. Starting with `page`, then `link`, delete all the records associated with the site whose `crawl_time` is less than the time for the run we just completed. (By deleting from `page` first, the `ON DELETE CASCADE` effect will clean up a lot of links along the way, even before we query for those directly). This way, we'll only have the freshest info left over.

## API
- Basic CRUD for the three tables.
- A way to list all `page` records by site, all `link` records by site, or all `link` records by `page`.
- Output of `link` records will be `JOIN`'d with their parent `page` records so that you can see where they come from. They'll be sorted by score.

> [!NOTE]
> In cases like this data model, where I've added integer primary keys for performance reasons only, I'd consider hiding them from the API layer, such that you access the REST resources via the values in the unique constraints. However, here, those unique values are URLs, which are _very_ awkward to use as REST resources IDs, because you have to URL sanitize them (i.e. escaping all the slashes and junk). So I'll probably use the primary keys in the basic CRUD endpoints. If you want a very distinct, single `site` or `page` but don't know its primary key, I expect that I'll provide a filter on the listing API that will result in 0 or 1 result being returned in the list.
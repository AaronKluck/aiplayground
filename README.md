# Installation / Setup
1. Set up a fresh Python environment in your shell (optional). I used Python 3.13, but most modern versions are probably compatible.
1. If you checked this out with Git, run `git update-index --assume-unchanged aiplay/ai/openai/key.txt` so that local changes to these files won't be detected.
1. Get an OpenAI API token and copy the generated value into `aiplay/ai/openai/key.txt`.
1. Run `pip install -r requirements.txt`.
1. Run `playwright install`.

# Running the Crawler
From the project directory, run `python3 run_crawl.py "https://www.your-base-url.com"`. 

There are also a bunch of commandline options that tweak behavior. You can explore them by running `python3 run_crawl.py -h`.

# Running the API
From the project directory, run `python3 run_api.py`.

This will host the API server at `http://localhost:8000`, which you can play around with via Swagger UI by visiting `http://localhost:8000/docs` in your browser.

# Design
Taking notes on the shape of the algorithm. At the time I'm starting this, I already have a basic crawler that looks for links *within the same domain* that don't violate `robots.txt` and queues them up to be processed by one of many worker threads.

So with that basic crawling pattern done, here's what's next.

> [!NOTE]
> A note from my future-self: this initial design pattern generally held true. Any big deviations I'll go over in the `Post-Implementation Notes` section.


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

# Post-Implementation Notes
Now that I'm done, here are some noteworthy things about the process.

## Link-Preprocessing
I originally thought I'd be sending entire rendered HTML docs to the AI to have it scour for links. What I ended up doing instead is pulling out the raw links along with their visible text and stuffing them into some JSON. This served two purposes.

The first was that it's a lot less for the AI to deal with, which directly translates to lower cost. The second was that I now had a much more consistent document to hash for change detection. If you run the crawler, then run it again immediately against the same site, nearly all the pages detect as unchanged. This gets around _lots_ of the randomness that some sites will put in their pages, like images or even the IDs within HTML tags.

When I first went down this road, I tried also extracting contextual information, i.e. text that was _near_ the link but not the link text itself. The thinking was that you might have a situation where the header of some section might give context clues that were important, or the words preceding the link describe it further. Unfortunately, I wasn't able to get this to work consistently.

## Link Scoring
I didn't havce a firm idea of this when I wrote the original design above, so here's what I came up with.

You can go read the big prompt I send in `aiplay/ai/inspect.py` for the details, but gist is that I ask the AI to look at each of the links I send it and determine, based on the content of the URL and the visible text of the link, whether any of a set of requested keywords are applicable to that link.

Each keyword gets a score from 0 to 1 based on how applicable it is. 1 means the word (or a plural version of it) was literally present. Less than 1 means some variation of the word, or a related word, was present. I give a few examples, but I largely leave the determination of how "close" something is to a keyword up to the AI.

Any links that have at least one matching keyword are sent back, along with their matching keywords and the scores.

Back in my own code, I now apply weights to those keywords, which are just multipliers that are again between 0 and 1. This way, the AI only has to worry about whether a keyword is relevant to the link and not how relevant a given keyword is to *me*. (Sometimes the AI returns keywords that I didn't feed it, even though I tell it not to. In that case, I allow the keywords through but assign them a low weight of 0.25.)

Now, a whole bunch of different scores isn't particularly useful - we want one score to tell at a glance if a link is important. However, we don't want to just sum them all up - a link with a whole bunch of low-scoring keywords is *not* as good as a link with only a few or even a single high-scoring keyword.

So instead, after applying the weightings, I sort the keywords by score from high to low. Going in order, each contributes less of itself than the previous to the final score. Specifically, the first score contributes its whole value, then the next contributes only half, then the next contributes only a quarter, then the next conributes only an eight, and so on. Even if you had an infinite number of keywords on single link, and they all scored a perfect 1.0 individually, the total score would converge to only 2.0 (because `1 + .5 + .25 + .125 ... ~= 2`).

## Challenges
Here are some of the unexpected challenges I faced and how I overcame (or sidestepped) them.

### Access Denied
Just hitting a public webpage with the `requests` library will often yield an "Access Denied" error. Websites don't like non-humans visiting them, so you need to pretend, which I did using `playwright`. This wasn't surprising, but https://www.bozeman.net was extremely resistant to my crawling attempts, even after supplementing with the `playwright-stealth` module.

What finally got around it was attempting to read the site with each of the 3 browser engines `playwright` has available until I found one that works. So that's now one of the first things the crawler does. It visits the site's homepage, determines which browser will work, then uses that for the rest of the run.

### Drupal Links
When I started crawling https://www.asu.edu/, I was noticing very few links being detected, and my crawl was over way too fast. This ended up being because there aren't actually many `<a href/>` tags on the site. Instead, there's a Drupal config located in a `<script/>` tag, and a JavaScript lib reads it and produces links somehow. If it's on the screen, then it seems like there ought to be a way to explore DOM to find the links it produces, but that's not how I solved it.

Instead, I look for that specific Drupal config (identified by the attributes in the `<script/>`), which always contains JSON. I crawl the JSON looking for things that look like URLs (e.g. starting with "http", "https", or "/"), and then I look _next to that_ for things with field names that might indicate descriptive text.

It's very imperfect, but it works for the ASU edge-case, and I tried it on a few other Drupal sites I could find too.

### Too Many Pages!!!
There are many ways that a URL can be different, yet basically refer to the same content. This yields wasteful duplicates in my result set. Here are some of the heuristical ways I sought to combat this - each of which is tunable via commandline arguments.

- Maximum URL parameters.
  - Very often, the URL params have no bearing whatsoever on the link content in a page. They contain tracking information, or sorting order, or any number of other inanities. Yet *sometimes* they're important. So to strike a balance, I let the crawler be configured with how many are allowed, with any remainder stripped off. A max of 1 is often sufficient, as most pages where it matters put the actually important param first, though by default there is no max.
- Maximum components.
  - Sometimes there are additional path components that are acting as parameters. This is something you'd want to tune per site, I think; I left the default at a convervative 10.
- Max depth.
  - This is how many "steps" away from the homepage you're allowed to get. The vast majority of pages can be gotten to within a couple clicks - certainly those with any links of importance. This also serves to protect against diving down rabbit holes of `?page=1`, `?page=2`, `?page=3`, et cetera.


## What I'd Do Different

### Link Representation
One weakness of my implementation is that, while I did a lot to avoid duplicate of a single page (in its processing and representation), I didn't do anything to avoid duplication of links _from different pages_. My justification, as I planned all this out, was that a 

Ideally, there'd be a single link entity in the database per URL being linked to, and rather than a foreign key to the page that linked to it, a separate table would track that 1:N relation.

### Prompt
Maybe not _different_, but... I feel like prompt tuning is something I could have spent a lot more time on. It takes a lot of trial and error, and due to the time-limited nature of this little project, I felt my time was better spent on things I could control.

Looking at the results, it usually makes sense, but it sometimes definitely hallucinates, or makes weird decisions, or flat-out disobeys my directives.

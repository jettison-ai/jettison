---
name: web-scraper
description: Fetch and parse web pages politely with caching and rate limits
---

# Web scraper

Respect robots.txt for every domain before fetching. Cache all responses on disk keyed by URL hash with a 24 hour TTL. Rate limit to at most one request per second per domain. Parse HTML with BeautifulSoup using the lxml backend. For JavaScript-heavy pages escalate to Playwright but only when static parsing yields no main content. Strip tracking parameters from URLs before storing them.

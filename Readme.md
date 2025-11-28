# 🐦 Twitter Multi-Language Scraper

Advanced Twitter/X data collection tool with comprehensive search strategies, multi-language support, and rich metadata extraction.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ Features

- 🌍 **Multi-Language Support** - Automatically scrapes in 11 languages (en, ja, es, pt, ar, fr, ko, de, hi, tr, it)
- 🔍 **Comprehensive Search** - Combines hashtag, keyword, and plural variants for maximum coverage
- 💾 **SQLite Storage** - Efficient local database with rich metadata
- ⚡ **Concurrent Scraping** - Up to 2000+ jobs running simultaneously
- 📊 **Rich Metadata** - User profiles, engagement metrics, media URLs, and more
- 🔄 **Automatic Variants** - Searches hashtags (#), keywords, plurals, and cashtags ($)
- 🎯 **Smart Filtering** - Engagement, media, verified users, and more

## 🚀 Quick Start

### Installation
```bash
# Clone repository
git clone https://github.com/YOUR_USERNAME/twitter-multilang-scraper.git
cd twitter-multilang-scraper

# Install dependencies
pip install -r requirements.txt

# Setup Twitter accounts
twscrape add_accounts accounts.txt username:password:email:email_password
twscrape login_accounts
```

### Usage

1. **Create `x.json`** with your search targets:
```json
[
  {
    "label": "#AI",
    "keyword": null,
    "start_datetime": null,
    "end_datetime": null,
    "weight": 1.0
  }
]
```

2. **Run the scraper:**
```bash
python aggressive_scrape.py
```

3. **View results:**
```bash
sqlite3 tweets.db "SELECT COUNT(*) FROM tweets;"
```

## 📋 Configuration

### x.json Format
```json
[
  {
    "label": "#cryptocurrency",
    "keyword": null,
    "start_datetime": "2024-01-01T00:00:00Z",
    "end_datetime": "2024-12-31T23:59:59Z",
    "weight": 2.5
  }
]
```

**Parameters:**
- `label` - Hashtag, keyword, or cashtag to search
- `keyword` - Optional additional keyword filter
- `start_datetime` - Start date (ISO format) or null for last 30 days
- `end_datetime` - End date (ISO format) or null for today
- `weight` - Priority weight (unused in current version)

## 🔧 Advanced Features

### Multi-Language Scraping

Automatically creates jobs for 11 languages:
- English (en)
- Japanese (ja)
- Spanish (es)
- Portuguese (pt)
- Arabic (ar)
- French (fr)
- Korean (ko)
- German (de)
- Hindi (hi)
- Turkish (tr)
- Italian (it)

### Search Variants

For `#bitcoin`, automatically searches:
- `#bitcoin` (hashtag)
- `bitcoin` (keyword)
- `"bitcoin"` (exact phrase)
- `#bitcoins` (plural)
- `bitcoins` (plural keyword)
- `$bitcoin` (cashtag)

### Database Schema
```sql
CREATE TABLE tweets (
    id TEXT PRIMARY KEY,
    url TEXT,
    username TEXT,
    user_id TEXT,
    text TEXT,
    timestamp DATETIME,
    language TEXT,
    like_count INTEGER,
    retweet_count INTEGER,
    reply_count INTEGER,
    -- ... 30+ more fields
);
```

## 📊 Example Output
```
================================================================================
SCRAPING COMPLETE
================================================================================
Jobs completed: 2343
New tweets: 15,847
  - Posts: 12,453
  - Replies: 3,394
  - Retweets: 1,247
Duration: 0:45:23
Rate: 5.8 tweets/sec

DATABASE STATS:
  Total tweets in DB: 15,847
  Database size: 234.56 MB
  Date range: 2024-01-01 to 2024-12-31

Top hashtags:
  #bitcoin: 3,456 tweets
  #crypto: 2,891 tweets
  #ethereum: 2,234 tweets
================================================================================
```

## 🛠️ Requirements
```
twscrape>=0.10.0
asyncio
```

## 📁 Project Structure
```
twitter-multilang-scraper/
├── aggressive_scrape.py    # Main scraper
├── storage_sqlite.py       # Database handler
├── x.json                  # Search configuration
├── accounts.db            # Twitter accounts (twscrape)
├── tweets.db              # Scraped data
└── README.md
```

## ⚙️ Configuration Options

Edit `aggressive_scrape.py`:
```python
# Max concurrent jobs
max_concurrent = 10

# Languages to scrape
LANGUAGES = ['en', 'ja', 'es', 'pt', 'ar', 'fr', 'ko', 'de', 'hi', 'tr', 'it']

# Reply limit per tweet
reply_limit = 100
```

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## 📝 License

MIT License - see [LICENSE](LICENSE) file

## ⚠️ Disclaimer

This tool is for educational and research purposes. Ensure compliance with Twitter's Terms of Service and rate limits. Use responsibly.

## 🙏 Acknowledgments

Built with:
- [twscrape](https://github.com/vladkens/twscrape) - Twitter scraping library
- [asyncio](https://docs.python.org/3/library/asyncio.html) - Async I/O

## 📧 Contact

Issues and questions: [GitHub Issues](https://github.com/YOUR_USERNAME/twitter-multilang-scraper/issues)

---

⭐ Star this repo if you find it useful!
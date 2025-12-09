# On-Demand Twitter Scraping

This module provides **on-demand scraping** functionality that runs separately from the main `aggressive_scrape.py` continuous scraping process.

## 🎯 Features

✅ **100% XContent Field Validation** - Every field matches validators' expectations  
✅ **Separate Worker Process** - Doesn't interfere with main scraping  
✅ **Multiple Request Types** - URL, username, keyword searches  
✅ **Automatic Result Storage** - Results saved to `on_demand_results/`  
✅ **Same Storage Format** - Uses SqliteMinerStorage (DataEntity format)  

---

## 🚀 Quick Start

### 1. Start the On-Demand Handler

```bash
cd /home/rohitt/data-universe/x-data-collector

# Option 1: Run directly
python3 on_demand_handler.py

# Option 2: Run with pm2 (recommended for 24/7)
pm2 start on_demand_handler.py --name x-ondemand --interpreter python3
pm2 logs x-ondemand
```

### 2. Submit Requests

Create or modify `on_demand_requests.json`:

```json
[
  {
    "request_id": "my_request_001",
    "usernames": ["elonmusk", "bittensor_"],
    "keywords": ["AI", "crypto"],
    "keyword_mode": "any",
    "start_datetime": "2025-01-01T00:00:00Z",
    "end_datetime": "2025-01-15T23:59:59Z",
    "limit": 100
  }
]
```

The handler checks every **10 seconds** for new requests and processes them automatically.

### 3. Get Results

Results are saved to `on_demand_results/{request_id}_result.json`:

```json
{
  "request_id": "my_request_001",
  "tweets_found": 85,
  "tweets_valid": 85,
  "tweets_stored": 85,
  "errors": [],
  "start_time": "2025-01-09T10:30:00",
  "end_time": "2025-01-09T10:32:15"
}
```

---

## 📋 Request Format

### Required Fields

```json
{
  "request_id": "unique_identifier"
}
```

### Optional Search Parameters

```json
{
  "usernames": ["user1", "user2"],        // OR logic between usernames
  "keywords": ["keyword1", "keyword2"],   // Use keyword_mode for logic
  "url": "https://x.com/user/status/123", // Single tweet lookup
  "keyword_mode": "any",                  // "any" (OR) or "all" (AND)
  "start_datetime": "2025-01-01T00:00:00Z",
  "end_datetime": "2025-01-31T23:59:59Z",
  "limit": 100
}
```

---

## 🔍 Request Types

### 1. **Username Search**

Get tweets from specific users:

```json
{
  "request_id": "username_search",
  "usernames": ["elonmusk", "bittensor_"],
  "start_datetime": "2025-01-01T00:00:00Z",
  "limit": 50
}
```

**Query**: `(from:elonmusk OR from:bittensor_) since:2025-01-01`

### 2. **Keyword Search (ANY)**

Find tweets with ANY of the keywords:

```json
{
  "request_id": "keyword_any",
  "keywords": ["bitcoin", "ethereum", "crypto"],
  "keyword_mode": "any",
  "limit": 100
}
```

**Query**: `("bitcoin" OR "ethereum" OR "crypto")`

### 3. **Keyword Search (ALL)**

Find tweets with ALL keywords:

```json
{
  "request_id": "keyword_all",
  "keywords": ["AI", "machine learning"],
  "keyword_mode": "all",
  "limit": 50
}
```

**Query**: `"AI" "machine learning"`

### 4. **Single Tweet Lookup**

Fetch a specific tweet by URL:

```json
{
  "request_id": "single_tweet",
  "url": "https://x.com/elonmusk/status/1234567890123456789",
  "limit": 1
}
```

### 5. **Combined Search**

Mix usernames and keywords:

```json
{
  "request_id": "combined",
  "usernames": ["bittensor_"],
  "keywords": ["TAO"],
  "keyword_mode": "any",
  "start_datetime": "2024-12-01T00:00:00Z",
  "end_datetime": "2025-01-31T23:59:59Z",
  "limit": 200
}
```

**Query**: `(from:bittensor_) ("TAO") since:2024-12-01 until:2025-01-31`

---

## ✅ Field Validation

Every scraped tweet is validated against the **XContent model** before storage:

### Required Fields (Validated)
- ✅ `username` (str)
- ✅ `text` (str)
- ✅ `url` (str)
- ✅ `timestamp` (datetime)
- ✅ `tweet_hashtags` (list)

### Optional Enhanced Fields
- ✅ `user_id`, `user_display_name`, `user_verified`
- ✅ `tweet_id`, `is_reply`, `is_quote`
- ✅ `conversation_id`, `in_reply_to_user_id`
- ✅ `language`, `quoted_tweet_id`
- ✅ `like_count`, `retweet_count`, `reply_count`, `quote_count`, `view_count`, `bookmark_count`
- ✅ `user_blue_verified`, `user_description`, `user_location`
- ✅ `profile_image_url`, `user_followers_count`, `user_following_count`

**Invalid tweets are logged** and skipped - only 100% valid tweets are stored!

---

## 🗄️ Storage

All on-demand scraped tweets are stored in the **same format** as regular scraping:

- **Database**: `/root/data-universe/storage/miner/SqliteMinerStorage.sqlite`
- **Format**: DataEntity (XContent converted to bytes)
- **Compatible**: 100% compatible with validators' S3 upload process

---

## 🔄 Integration with Main Scraper

```
aggressive_scrape.py          on_demand_handler.py
        ↓                              ↓
   [50 Workers]                 [On-Demand Workers]
        ↓                              ↓
   x.json jobs              on_demand_requests.json
        ↓                              ↓
        └──────── SAME DATABASE ───────┘
              SqliteMinerStorage.sqlite
```

Both systems:
- ✅ Share the same database
- ✅ Use the same `accounts.db` (200 accounts)
- ✅ Store in XContent → DataEntity format
- ✅ Support S3 upload workflow

---

## 📊 Monitoring

### Check Handler Status

```bash
# If running with pm2
pm2 logs x-ondemand

# If running directly
# Check console output
```

### Check Results

```bash
ls -lh on_demand_results/

# View specific result
cat on_demand_results/my_request_001_result.json | jq
```

### Check Database

```bash
sqlite3 /root/data-universe/storage/miner/SqliteMinerStorage.sqlite

# Count tweets
SELECT COUNT(*) FROM data_entities WHERE source = 2;
```

---

## 🛠️ Troubleshooting

### "No tweets found"

- Check if request parameters are too restrictive
- Verify date ranges are valid
- Ensure usernames exist (without @)

### "Validation failed"

- Check logs for specific field errors
- Ensure tweet data has required fields
- May indicate Twitter API changes

### "Account rate limited"

- Handler automatically rotates through 200 accounts
- Wait for rate limit to reset (~15 min)
- Add more accounts if needed

---

## 📝 Example Workflow

```bash
# 1. Start handler
pm2 start on_demand_handler.py --name x-ondemand --interpreter python3

# 2. Create request
cat > on_demand_requests.json << 'EOF'
[
  {
    "request_id": "urgent_crypto_search",
    "keywords": ["Bitcoin", "BTC halving"],
    "keyword_mode": "any",
    "start_datetime": "2025-01-01T00:00:00Z",
    "limit": 200
  }
]
EOF

# 3. Wait for processing (check logs)
pm2 logs x-ondemand

# 4. Check result
cat on_demand_results/urgent_crypto_search_result.json
```

---

## 🎯 Perfect for Validators

This on-demand scraper is designed specifically for **validators' on-demand API**:

✅ **Exact XContent format** - Every field matches model  
✅ **Field validation** - Only valid tweets stored  
✅ **DataEntity storage** - Ready for S3 upload  
✅ **Low engagement allowed** - No spam filtering  
✅ **Fast response** - Dedicated workers  

---

## 🔒 Security Notes

- Uses same `accounts.db` as main scraper
- Results stored locally in `on_demand_results/`
- Processes are isolated (won't crash main scraper)
- All tweets deduplicated globally

---

## 📞 Support

For issues or questions, check:
1. Handler logs: `pm2 logs x-ondemand`
2. Result errors: `on_demand_results/{request_id}_result.json`
3. Database: `SqliteMinerStorage.sqlite`

**Your on-demand scraper is ready for 24/7 operation!** 🚀

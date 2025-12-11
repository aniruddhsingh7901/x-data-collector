# 🧪 Testing Guide - Aggressive Scrape with 2 Workers

## Overview

This guide explains how to test aggressive_scrape.py with 2 workers to verify all functionality works correctly before scaling to production.

**Configuration:**
- **Workers:** 2 (set in code)
- **Accounts:** 4 in accounts.db
- **Account Pool:** Shared across both workers with automatic rotation

---

## 🎯 Testing Objectives

### ✅ 1. Worker-to-Job Ratio (1:1)
**Goal:** Verify each worker picks up exactly 1 job at a time

**How It Works:**
```python
async def worker(worker_id: int):
    """Worker that processes jobs from the queue"""
    while keep_running:
        try:
            # BLOCKING: Worker waits for a job
            job = await asyncio.wait_for(job_queue.get(), timeout=5.0)
            
            # EXCLUSIVE: Only this worker has this job
            logger.info(f"[Worker {worker_id}] Starting job: {job.label}")
            
            # PROCESS: Do the scraping (this blocks the worker)
            result = await scrape_job(api, job, storage, dedup)
            
            # COMPLETE: Mark job as done, worker picks up next job
            job_queue.task_done()
```

**Expected Behavior:**
- 2 workers = 2 jobs running simultaneously (MAX)
- When Worker 0 finishes Job A, it immediately picks up Job C
- When Worker 1 finishes Job B, it immediately picks up Job D
- **No worker sits idle if jobs are available**

**Verification:**
```bash
cd /home/anirudh/data-universe/x-data-collector
python3 aggressive_scrape.py 2>&1 | grep -E "\[Worker [0-9]+\]"

# Expected output:
# [Worker 0] Starting job: #bitcoin
# [Worker 1] Starting job: #ethereum
# [Worker 0] Completed job: #bitcoin
# [Worker 0] Starting job: #crypto    <- Worker 0 picks up next job
# [Worker 1] Completed job: #ethereum
# [Worker 1] Starting job: #defi      <- Worker 1 picks up next job
```

---

### ✅ 2. Rate Limit Handling with Account Rotation
**Goal:** When one account hits rate limit, system automatically switches to another

**How It Works:**
```python
# twscrape's API class (accounts.db) automatically handles this:
# 1. Worker makes request with Account 1
# 2. Account 1 hits rate limit (429 error)
# 3. twscrape marks Account 1 as rate-limited
# 4. Worker automatically retries with Account 2
# 5. Process continues seamlessly
```

**Account Pool Management:**
- **4 accounts** in pool
- **2 workers** sharing the pool
- Each worker can use any available account
- Rate-limited accounts are automatically skipped

**Expected Behavior:**
```
Worker 0 uses Account 1 → Rate limit hit
Worker 0 switches to Account 2 → Continues
Worker 1 uses Account 3 → Working fine
Worker 1 continues with Account 3
```

**Verification:**
```bash
# Monitor account usage
cd /home/anirudh/data-universe/x-data-collector
python3 aggressive_scrape.py 2>&1 | grep -i "rate"

# Look for messages like:
# "Account rate limited, trying next account..."
# "Switched to account: @username"
```

**Check Account Status:**
```bash
cd /home/anirudh/data-universe/x-data-collector
python3 -c "
from twscrape import API
import asyncio

async def check_accounts():
    api = API('accounts.db')
    accounts = await api.pool.accounts_info()
    for acc in accounts:
        status = '✅ Active' if acc.active else '⏸️  Rate Limited'
        print(f'{acc.username}: {status} (Requests: {acc.requests_count})')

asyncio.run(check_accounts())
"
```

---

### ✅ 3. Date Range Filtering
**Goal:** Only scrape tweets within specified date range

**How It Works:**
```python
class ScrapingJob:
    def __init__(self, ...):
        # If dates provided, use them
        if end_datetime:
            self.end_date = datetime.fromisoformat(end_datetime.replace('Z', '+00:00'))
        else:
            # Default: now
            self.end_date = datetime.now(timezone.utc)
        
        if start_datetime:
            self.start_date = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
        else:
            # Default: 30 days ago
            self.start_date = self.end_date - timedelta(days=30)
    
    def build_query(self) -> str:
        # Date range added to X search query
        query_parts.append(f"since:{self.start_date.strftime('%Y-%m-%d')}")
        query_parts.append(f"until:{self.end_date.strftime('%Y-%m-%d')}")
```

**X.json Configuration:**
```json
{
  "id": "test_job",
  "params": {
    "label": "#bitcoin",
    "keyword": null,
    "post_start_datetime": "2025-08-28T17:30:47.075039Z",  // Specific start
    "post_end_datetime": "2025-11-26T17:30:47.075039Z"     // Specific end
  }
}
```

**Verification:**
```bash
# Check the query being built
python3 aggressive_scrape.py 2>&1 | grep "Query:"

# Expected output:
# Query: (#bitcoin OR bitcoin OR ...) since:2025-08-28 until:2025-11-26

# Check scraped tweet dates in database
sqlite3 ../storage/miner/SqliteMinerStorage.sqlite "
  SELECT json_extract(content, '$.timestamp'), 
         json_extract(content, '$.text')
  FROM data_entities 
  WHERE source = 'x'
  ORDER BY datetime 
  LIMIT 10;
"

# All timestamps should be between start_datetime and end_datetime
```

---

### ✅ 4. Pagination Working
**Goal:** Scrape ALL tweets, not just first page

**How It Works:**
```python
# UNLIMITED PAGINATION
async for tweet in api.search(query, limit=-1):  # limit=-1 = infinite
    # twscrape automatically:
    # 1. Fetches page 1
    # 2. Gets cursor for page 2
    # 3. Fetches page 2
    # 4. Gets cursor for page 3
    # ... continues until no more tweets
    
    if tweet.id not in tweet_ids_seen:
        storage.store_tweet(tweet_data)
        stats["posts"] += 1
        
        # Progress logging every 100 tweets
        if stats["posts"] % 100 == 0:
            logger.info(f"Stored {stats['posts']} posts")
```

**Resume Capability:**
```python
# If scraping is interrupted:
# 1. Cursor saved in pagination_state.db
# 2. Next run resumes from exact position
# 3. No duplicate tweets scraped

existing_state = await pagination_mgr.get_state(query_hash)
if existing_state and not existing_state.get('completed'):
    resume_cursor = existing_state.get('cursor')
    logger.info(f"Resuming from cursor: {resume_cursor[:20]}...")
```

**Verification:**
```bash
# Monitor pagination progress
python3 aggressive_scrape.py 2>&1 | grep "Stored"

# Expected output:
# [#bitcoin] Stored 100 posts
# [#bitcoin] Stored 200 posts
# [#bitcoin] Stored 300 posts
# [#bitcoin] Stored 400 posts    <- Pagination working!

# Check pagination state
sqlite3 pagination_state.db "
  SELECT query_text, items_fetched, completed 
  FROM pagination_state 
  ORDER BY updated_at DESC 
  LIMIT 5;
"

# Test resume capability:
# 1. Start scraping
# 2. Press Ctrl+C after 200 tweets
# 3. Restart scraping
# 4. Verify it resumes from ~200 tweets (not starting from 0)
```

---

### ✅ 5. Data Format - 100% Validator Compatible
**Goal:** All scraped data passes validator checks

**Field Verification:**
```bash
# Extract a tweet from database
sqlite3 ../storage/miner/SqliteMinerStorage.sqlite "
  SELECT content 
  FROM data_entities 
  WHERE source = 'x' 
  LIMIT 1;
" | python3 -m json.tool

# Expected fields (matching XContent model):
{
  "id": "1234567890",
  "url": "https://x.com/user/status/1234567890",
  "username": "someuser",
  "text": "Tweet content here",
  "timestamp": "2025-11-26T17:30:47+00:00",
  
  // User info
  "user_id": "123456",
  "user_display_name": "Some User",      // ✅ Correct field name
  "user_verified": false,
  
  // Tweet metadata
  "tweet_id": "1234567890",              // ✅ Present
  "language": "en",
  "is_reply": false,
  "is_quote": false,
  "conversation_id": "1234567890",
  
  // Content
  "tweet_hashtags": ["bitcoin", "crypto"], // ✅ Correct field name (was hashtags)
  "media": ["https://..."],                 // ✅ Correct field name (was media_urls)
  
  // Engagement metrics
  "like_count": 42,
  "retweet_count": 10,
  "reply_count": 5,
  "quote_count": 2,
  "view_count": 1000,
  "bookmark_count": 8,
  
  // User profile
  "user_blue_verified": false,
  "user_description": "Bio text",
  "user_location": "USA",
  "profile_image_url": "https://...",
  "user_followers_count": 1234,
  "user_following_count": 567,
  
  // Job tracking
  "job_label": "#bitcoin",
  "job_keyword": null,
  "search_strategy": "hashtag"
}
```

**Critical:** NO "source" field in tweet JSON!
- ❌ BAD: `{"source": "x", ...}` in content
- ✅ GOOD: `source` set at DataEntity level (`DataSource.X`)

---

### ✅ 6. S3 Upload Compatibility
**Goal:** Miner can upload scraped data to S3 and validators can retrieve it

**How It Works:**
```python
# 1. aggressive_scrape.py stores in SqliteMinerStorage
storage = SqliteMinerStorage(database="SqliteMinerStorage.sqlite")

# 2. Miner's auto-upload (every 2 hours) reads from SqliteMinerStorage
# 3. Converts DataEntity → S3 format
# 4. Uploads to S3 bucket
# 5. Validators retrieve and validate

# Data flow:
# aggressive_scrape.py → SqliteMinerStorage.sqlite → Miner → S3 → Validators
```

**Verification:**
```bash
# Check data in SqliteMinerStorage
cd /home/anirudh/data-universe/storage/miner

# Count tweets
sqlite3 SqliteMinerStorage.sqlite "
  SELECT COUNT(*) as total_tweets
  FROM data_entities 
  WHERE source = 'x';
"

# Check date range
sqlite3 SqliteMinerStorage.sqlite "
  SELECT 
    MIN(datetime) as earliest,
    MAX(datetime) as latest,
    COUNT(*) as total
  FROM data_entities 
  WHERE source = 'x';
"

# Verify DataEntity structure
sqlite3 SqliteMinerStorage.sqlite "
  SELECT uri, datetime, source, label, content_size_bytes
  FROM data_entities 
  WHERE source = 'x'
  LIMIT 5;
"

# Expected:
# uri: x://tweet/1234567890 or https://x.com/...
# datetime: 2025-11-26T17:30:47+00:00
# source: x
# label: #bitcoin
# content_size_bytes: 1234
```

---

## 🚀 Running Tests

### Test 1: Basic 2-Worker Test
```bash
cd /home/anirudh/data-universe/x-data-collector

# Create minimal test config (x.json)
cat > x_test.json << 'EOF'
[
  {
    "id": "test_1",
    "weight": 1.0,
    "params": {
      "label": "#bitcoin",
      "keyword": null,
      "platform": "x",
      "post_start_datetime": null,
      "post_end_datetime": null
    }
  },
  {
    "id": "test_2",
    "weight": 1.0,
    "params": {
      "label": "#ethereum",
      "keyword": null,
      "platform": "x",
      "post_start_datetime": null,
      "post_end_datetime": null
    }
  },
  {
    "id": "test_3",
    "weight": 1.0,
    "params": {
      "label": "#crypto",
      "keyword": null,
      "platform": "x",
      "post_start_datetime": null,
      "post_end_datetime": null
    }
  },
  {
    "id": "test_4",
    "weight": 1.0,
    "params": {
      "label": "#defi",
      "keyword": null,
      "platform": "x",
      "post_start_datetime": null,
      "post_end_datetime": null
    }
  }
]
EOF

# Backup x.json
cp x.json x.json.backup

# Use test config
cp x_test.json x.json

# Run test (Ctrl+C after 5 minutes to see if works)
python3 aggressive_scrape.py
```

### Test 2: Verify Worker Behavior
```bash
# Run in one terminal
python3 aggressive_scrape.py 2>&1 | tee test_output.log

# In another terminal, monitor workers
tail -f test_output.log | grep -E "\[Worker [0-9]+\]"

# Expected:
# Both workers start jobs simultaneously
# When one finishes, it immediately picks up next job
# No gaps where both workers are idle
```

### Test 3: Verify Date Filtering
```bash
# Modify x_test.json with specific dates
python3 aggressive_scrape.py

# Check results
sqlite3 ../storage/miner/SqliteMinerStorage.sqlite "
  SELECT 
    COUNT(*) as total,
    MIN(json_extract(content, '$.timestamp')) as earliest,
    MAX(json_extract(content, '$.timestamp')) as latest
  FROM data_entities 
  WHERE source = 'x'
  AND json_extract(content, '$.job_label') = '#bitcoin';
"
```

### Test 4: Verify Resume Capability
```bash
# Start scraping
python3 aggressive_scrape.py

# Wait for 200 tweets, then press Ctrl+C

# Check pagination state
sqlite3 pagination_state.db "SELECT * FROM pagination_state;"

# Restart - should resume from ~200
python3 aggressive_scrape.py
```

---

## 📊 Success Criteria

### ✅ All Tests Pass If:

1. **Worker Distribution:**
   - 2 workers processing jobs simultaneously
   - No worker sits idle while jobs available
   - Jobs complete in ~50% of time vs 1 worker

2. **Account Rotation:**
   - When rate limit hit, automatically switches accounts
   - No errors that stop scraping
   - All 4 accounts used efficiently

3. **Date Filtering:**
   - All tweets between `post_start_datetime` and `post_end_datetime`
   - Default: last 30 days if dates not specified
   - Query includes `since:YYYY-MM-DD until:YYYY-MM-DD`

4. **Pagination:**
   - Scrapes >1000 tweets per job (proves pagination working)
   - Progress logs every 100 tweets
   - Can resume from interruption point

5. **Data Quality:**
   - All fields match XContent model
   - ✅ `tweet_hashtags` (not `hashtags`)
   - ✅ `media` (not `media_urls`)
   - ✅ `user_display_name` (not `display_name`)
   - ✅ `tweet_id` present
   - ❌ NO `source` field in content JSON

6. **S3 Compatibility:**
   - Data stored in SqliteMinerStorage.sqlite
   - DataEntity structure correct (uri, datetime, source, label, content)
   - Miner can read and upload to S3

---

## 🔧 Troubleshooting

### Problem: Workers Not Starting
```bash
# Check accounts
cd /home/anirudh/data-universe/x-data-collector
twscrape accounts accounts.db

# Expected: 4 accounts with ACTIVE status
```

### Problem: No Tweets Scraped
```bash
# Check query being built
python3 aggressive_scrape.py 2>&1 | head -50

# Look for "Query:" line - should have search terms
```

### Problem: Rate Limits Hit Immediately
```bash
# Check account status
python3 check_accounts.py

# If all rate-limited, wait or add more accounts
```

### Problem: Database Locked
```bash
# Kill other processes using database
lsof ../storage/miner/SqliteMinerStorage.sqlite
kill -9 <PID>
```

---

## 📈 Production Scaling

Once 2-worker test passes:

```python
# In aggressive_scrape.py, line ~1250:
await scrape_jobs_concurrently(jobs, max_concurrent=50)  # Scale to 50 workers

# Account recommendations:
# - 50 workers → 50-100 accounts recommended
# - More accounts = better rate limit distribution
```

**Performance Estimates:**
- 2 workers: ~100-200 tweets/minute
- 50 workers: ~2,500-5,000 tweets/minute
- 100 workers: ~5,000-10,000 tweets/minute

---

## ✅ Final Checklist

Before declaring test successful:

- [ ] 2 workers running simultaneously
- [ ] Workers pick up jobs 1:1 (never >2 jobs at once)
- [ ] Account rotation working (when rate limit hit)
- [ ] Date filtering working (tweets in specified range)
- [ ] Pagination working (>1000 tweets per job)
- [ ] Resume capability working (can Ctrl+C and resume)
- [ ] Data format correct (all fields match XContent)
- [ ] NO "source" field in tweet content JSON
- [ ] Data in SqliteMinerStorage.sqlite
- [ ] Deduplication working (no duplicate tweet IDs)

**Test passed?** → Ready for production with max_concurrent=50! 🚀

**Restore original config:**
```bash
cp x.json.backup x.json
```

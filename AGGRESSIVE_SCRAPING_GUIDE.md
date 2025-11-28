# Aggressive Scraping Guide - 100M Tweets/Day

## 🎯 Overview

This guide shows you how to use the modified twscrape system to scrape 100M tweets per day with:
- ✅ 100 accounts with pre-existing tokens
- ✅ Aggressive 400 req/15min rate limiting
- ✅ Automatic 5-min cooldowns
- ✅ Seamless account rotation
- ✅ Pagination continuation across accounts
- ✅ Real-time monitoring

---

## 📋 Quick Start

### Step 1: Prepare Your Accounts File

Create `accounts.txt` with one account per line in this format:
```
username:password:email:email_password:ct0:auth_token:proxy_host:proxy_port:proxy_user:proxy_pass
```

**Example:**
```
JenniferTu63671:ruthking15215:wdxbzkvhqp@rambler.ru:1198718MYNTva:d0dc507929e9880670a7f0388ef0387db571d931753f708a50e913368ca5d6719d461b792b73b03ca758fcc645d78283e10bde504ccff866b0df39fe89ff3bdfd619de91ca37b7bcba822656a141e14d:cbb381e1e18af71bfc8d177d7d1b1e8707581066:5.249.176.154:5432:uae2k:ddfivl8d
```

**Fields:**
1. `username` - Twitter username
2. `password` - Twitter password
3. `email` - Email address
4. `email_password` - Email password
5. `ct0` - CSRF token (from cookies)
6. `auth_token` - Auth token (from cookies)
7. `proxy_host` - Proxy IP address
8. `proxy_port` - Proxy port
9. `proxy_user` - Proxy username
10. `proxy_pass` - Proxy password

### Step 2: Load Accounts

```bash
python load_accounts.py accounts.txt
```

**Output:**
```
Loading accounts from accounts.txt...

[INFO] Account JenniferTu63671 added with tokens (active=True, proxy=5.249.176.***)
[INFO] Account user2 added with tokens (active=True, proxy=192.168.1.***)
...

✅ Successfully added 100 accounts!

Next steps:
1. Check accounts: python -m twscrape accounts
2. Check stats: python -m twscrape stats
3. Start scraping: python aggressive_scrape.py
```

### Step 3: Verify Accounts

```bash
python -m twscrape accounts
```

**Check active accounts:**
```bash
python -m twscrape stats
```

### Step 4: Start Scraping

```bash
python aggressive_scrape.py
```

### Step 5: Monitor in Real-Time (Optional)

Open a second terminal:
```bash
python monitor_scraping.py
```

---

## 🔧 How It Works

### 1. Aggressive Rate Limiting

**Traditional Approach:**
- Twitter rate limits: 500 requests per 15 minutes
- System waits for Twitter to rate limit
- 15-minute lockout when rate limited

**Aggressive Approach:**
- Self-impose limit: 400 requests per 15 minutes
- Apply 5-minute cooldown before Twitter's limit
- Switches to next account immediately
- Minimizes downtime

**Flow:**
```
Account A: Request 1, 2, 3... 400
            ↓
         5-min cooldown
            ↓
Account B: Request 1, 2, 3... 400
            ↓
         5-min cooldown
            ↓
Account C: Request 1, 2, 3... 400
            ↓
Account A: (cooldown expired, ready again!)
```

### 2. Pagination Continuation

**Problem:** When Account A gets rate limited mid-pagination, you lose the cursor.

**Solution:** Shared pagination state

```python
Query: "#bitcoin since:2024-11-01"
  ↓
Account A: Page 1, 2, 3... (rate limited)
  ↓ (save cursor "ABC123...")
Account B: Continue from cursor "ABC123..."
  ↓
Account B: Page 4, 5, 6... (rate limited)
  ↓ (save cursor "XYZ789...")
Account C: Continue from cursor "XYZ789..."
```

### 3. Request Tracking

Every request is tracked per account per endpoint:

```python
Account: JenniferTu63671
Endpoint: SearchTimeline
Timestamps: [1732843801, 1732843802, 1732843803, ...]
Count (last 15 min): 395/400

→ Keep going (still below limit)
```

When count reaches 400:
```python
Count (last 15 min): 400/400

→ Apply 5-min cooldown
→ Switch to next account
```

---

## 📊 Performance Metrics

### Expected Performance with 100 Accounts

**Requests:**
- 100 accounts × 400 requests/15min = 40,000 requests per cycle
- 4 cycles per hour (with 5-min cooldowns) = 160,000 requests/hour
- 24 hours = **3.84M requests/day**

**Tweets:**
- Average 20-50 tweets per request
- 3.84M requests × 25 tweets = **96M tweets/day** ✅

**With optimization:**
- Focus on high-yield endpoints (search returns 20+ tweets)
- Collect replies (additional tweets)
- Total possible: **100M-150M tweets/day**

### Real-World Example

```
Time: 10:00 AM
Active accounts: 100
Accounts in cooldown: 0

First cycle (15 min):
- All 100 accounts make 400 requests each
- Total: 40,000 requests
- Tweets collected: ~800,000

Time: 10:15 AM
Active accounts: 0
Accounts in cooldown: 100 (5-min cooldown)

Time: 10:20 AM
Active accounts: 100 (cooldown expired)
Accounts in cooldown: 0

Second cycle begins...
```

---

## 🎮 Usage Examples

### Example 1: Scrape Single Hashtag

```python
import asyncio
from twscrape import API

async def main():
    api = API("accounts.db")
    
    # Scrape #bitcoin for last 30 days
    query = "#bitcoin since:2024-10-29"
    
    count = 0
    async for tweet in api.search(query, limit=-1):
        count += 1
        if count % 100 == 0:
            print(f"Collected {count} tweets...")
    
    print(f"Total: {count} tweets")

asyncio.run(main())
```

### Example 2: Scrape Multiple Keywords with Replies

```python
import asyncio
from twscrape import API

async def scrape_with_replies(api, query):
    tweets = []
    
    # Get main tweets
    async for tweet in api.search(query, limit=10000):
        tweets.append(tweet)
        
        # Get replies for each tweet
        async for reply in api.tweet_replies(tweet.id, limit=1000):
            tweets.append(reply)
    
    return tweets

async def main():
    api = API("accounts.db")
    
    keywords = ["bitcoin", "ethereum", "crypto"]
    all_tweets = []
    
    for keyword in keywords:
        query = f"{keyword} since:2024-11-01"
        tweets = await scrape_with_replies(api, query)
        all_tweets.extend(tweets)
        print(f"{keyword}: {len(tweets)} tweets")
    
    print(f"Total: {len(all_tweets)} tweets")

asyncio.run(main())
```

### Example 3: Continuous Scraping with Monitoring

```python
import asyncio
from datetime import datetime, timedelta
from twscrape import API

async def continuous_scrape():
    api = API("accounts.db")
    
    # Scrape last 24 hours continuously
    while True:
        start = datetime.now() - timedelta(hours=24)
        query = f"#trending since:{start.strftime('%Y-%m-%d')}"
        
        count = 0
        async for tweet in api.search(query, limit=100000):
            count += 1
            
            if count % 1000 == 0:
                # Get stats
                stats = await api.pool.get_aggressive_stats()
                print(f"Collected: {count}, Active: {stats['active_accounts']}, "
                      f"Cooldown: {stats['accounts_in_cooldown']}")
        
        # Wait 1 hour before next cycle
        await asyncio.sleep(3600)

asyncio.run(continuous_scrape())
```

---

## 🔍 Monitoring

### Real-Time Monitor

```bash
python monitor_scraping.py
```

**Output:**
```
================================================================================
                        AGGRESSIVE SCRAPING MONITOR
================================================================================
Time: 2024-11-29 01:30:00
================================================================================

📊 OVERALL STATISTICS
   Total Accounts: 100
   Active Accounts: 100
   Inactive Accounts: 0
   Accounts in Cooldown: 25

⚡ RATE LIMITING
   Requests (last 15 min): 30,000
   Estimated Capacity: 160,000 req/hour
   Daily Projection: 3,840,000 requests
   Tweet Projection: 76,800,000 tweets/day

🔒 LOCKED QUEUES
   SearchTimeline: 25 accounts
   TweetDetail: 10 accounts

👥 ACCOUNT STATUS (Top 10)
   Username             Active   Requests   Last Used
   -------------------- -------- ---------- --------------------
   JenniferTu63671      ✓        1,250      2024-11-29 01:29:55
   user2                ✓        1,180      2024-11-29 01:29:50
   ...

📈 REQUEST BREAKDOWN (Last 15 min)
   JenniferTu63671: 395 requests
      - SearchTimeline: 300
      - TweetDetail: 95
   user2: 380 requests
      - SearchTimeline: 380

================================================================================
Press Ctrl+C to exit
================================================================================
```

### Check Stats Manually

```python
import asyncio
from twscrape import AccountsPool

async def check_stats():
    pool = AccountsPool("accounts.db")
    stats = await pool.get_aggressive_stats()
    
    print(f"Active accounts: {stats['active_accounts']}")
    print(f"In cooldown: {stats['accounts_in_cooldown']}")
    print(f"Requests (15min): {stats['total_requests_15min']}")
    print(f"Capacity/hour: {stats['estimated_capacity_per_hour']:,}")

asyncio.run(check_stats())
```

---

## ⚠️ Important Notes

### 1. Account Safety

- **Proxies are critical** - Each account must use its own proxy
- **Distribute requests** - Don't hammer single endpoint
- **Monitor bans** - Check inactive accounts regularly
- **Rotate IPs** - Use residential proxies if possible

### 2. Rate Limit Strategy

- **400 requests is conservative** - Twitter allows 500, but we use 400 for safety
- **5-min cooldown is aggressive** - Adjust if getting banned
- **15-min cooldown** - Applied automatically if Twitter rate limits

### 3. Data Storage

- **100M tweets/day ≈ 50GB/day** (compressed JSON)
- Use database (PostgreSQL, MongoDB) for production
- Implement batching to reduce memory usage

### 4. Error Handling

If accounts get banned:
```bash
# Check inactive accounts
python -m twscrape accounts | grep "active: False"

# Delete inactive accounts
python -m twscrape delete_inactive

# Add new accounts
python load_accounts.py new_accounts.txt
```

---

## 🚀 Optimization Tips

### 1. Increase Capacity

- Add more accounts (200-300 accounts → 200M tweets/day)
- Use faster proxies (reduce latency)
- Optimize queries (specific date ranges)

### 2. Reduce Ban Rate

- Lower limit to 350 requests (more conservative)
- Increase cooldown to 10 minutes
- Randomize request intervals

### 3. Improve Data Quality

- Filter by engagement (likes > 10)
- Focus on verified accounts
- Collect only recent tweets (last 7 days)

---

## 📞 Troubleshooting

### Problem: All accounts in cooldown

**Solution:**
```bash
# Reset locks manually
python -m twscrape reset_locks

# Or wait for cooldowns to expire (5-15 minutes)
```

### Problem: No requests being made

**Check:**
1. Are accounts active? `python -m twscrape accounts`
2. Are all accounts locked? `python -m twscrape stats`
3. Check logs for errors

### Problem: Low tweet rate

**Optimize:**
1. Use broader queries (more results)
2. Scrape replies and retweets
3. Add more accounts
4. Reduce cooldown time (risky)

### Problem: Accounts getting banned

**Solutions:**
1. Use better proxies (residential)
2. Lower request limit (400 → 300)
3. Increase cooldown (5 min → 10 min)
4. Rotate user agents

---

## 📈 Scaling Beyond 100M/Day

### 200M tweets/day
- 200 accounts
- Distribute across multiple machines
- Use load balancer for proxies

### 500M tweets/day
- 500 accounts
- Distributed system (10 machines × 50 accounts)
- Dedicated proxy pool
- Database sharding

### 1B tweets/day
- 1000+ accounts
- Full distributed architecture
- Cloud infrastructure (AWS, GCP)
- Real-time processing pipeline

---

## ✅ Summary

You now have:
1. ✅ Pagination state manager for continuation
2. ✅ Aggressive rate limiting (400 req/15min)
3. ✅ Account loader for token-based accounts
4. ✅ Request tracking and cooldown management
5. ✅ Scraping examples
6. ✅ Real-time monitoring

**Ready to scrape 100M tweets/day!** 🚀

When you have your `accounts.txt` ready, just run:
```bash
python load_accounts.py accounts.txt
python aggressive_scrape.py
```

Good luck with your scraping! 🎉

#!/usr/bin/env python3
"""
Aggressive Scraping with Jobs from x.json
Enhanced with rich metadata parsing and SQLite storage

ENHANCEMENTS:
- Multiple search strategies (hashtag, keyword, user, location, advanced)
- Network expansion (conversations, retweeters, user networks)
- Multi-language support
- Smart pagination with resume capability
- Advanced X search operators
"""

# ========== CONFIGURATION ==========
ENABLE_MULTI_LANGUAGE = True  # Set to False for all-languages-only (no filter)
TOP_LANGUAGES = [
    'en',  # English (highest volume)
    'ja',  # Japanese
    'es',  # Spanish
    'pt',  # Portuguese
    'ar',  # Arabic
    'fr',  # French
    'ko',  # Korean
    'de',  # German
    'hi',  # Hindi
    'tr',  # Turkish
    'it',  # Italian
]

# REPLY/COMMENT SCRAPING SETTINGS
SCRAPE_ALL_REPLIES = True  # Set to False to limit replies per tweet
MAX_REPLIES_PER_TWEET = -1  # -1 = unlimited, or set a number like 500
# ===================================

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set
from enum import Enum
from twscrape import API
from twscrape.logger import set_log_level, logger
from twscrape.pagination_state import PaginationStateManager
from storage_sqlite import TweetStorage


class SearchStrategy(str, Enum):
    """Search strategy types for X/Twitter"""
    HASHTAG = "hashtag"
    KEYWORD = "keyword"
    USER = "user"
    LOCATION = "location"
    ADVANCED = "advanced"


class ScrapingJob:
    """Represents a single scraping job with enhanced search capabilities"""
    
    def __init__(self, label: str, keyword: Optional[str], 
                 start_datetime: Optional[str], end_datetime: Optional[str], 
                 weight: float, 
                 strategy: str = "hashtag",
                 additional_filters: Optional[Dict] = None,
                 language: Optional[str] = None,
                 enable_network_expansion: bool = False,
                 max_network_depth: int = 1):
        self.label = label
        self.keyword = keyword
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime
        self.weight = weight
        self.strategy = SearchStrategy(strategy) if isinstance(strategy, str) else strategy
        self.additional_filters = additional_filters or {}
        self.language = language
        self.enable_network_expansion = enable_network_expansion
        self.max_network_depth = max_network_depth
        
        # Parse dates or use defaults (last 30 days)
        if end_datetime:
            self.end_date = datetime.fromisoformat(end_datetime.replace('Z', '+00:00'))
        else:
            self.end_date = datetime.now()
        
        if start_datetime:
            self.start_date = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
        else:
            self.start_date = self.end_date - timedelta(days=30)
    
    def build_comprehensive_variants(self, base_term: str) -> List[str]:
        """
        Build multiple query variants for maximum coverage
        
        Args:
            base_term: The base term (with or without #)
        
        Returns:
            List of query variants
        """
        # Remove # or $ if present to get base
        clean_term = base_term.lstrip('#$').strip()
        
        variants = []
        
        # 1. Original hashtag (most important)
        variants.append(f"#{clean_term}")
        
        # 2. Keyword without hashtag (catches non-hashtag usage)
        variants.append(clean_term)
        
        # 3. Exact phrase (catches precise mentions)
        variants.append(f'"{clean_term}"')
        
        # 4. Plural forms (if applicable and word length > 3)
        if not clean_term.endswith('s') and len(clean_term) > 3:
            variants.append(f"#{clean_term}s")
            variants.append(f"{clean_term}s")
        
        # 5. For crypto: add cashtag version if original was hashtag
        if base_term.startswith('#'):
            variants.append(f"${clean_term}")
        elif base_term.startswith('$'):
            variants.append(f"#{clean_term}")
        
        return variants
    
    def build_query(self) -> str:
        """Enhanced query builder with comprehensive search variants and advanced filters"""
        query_parts = []
        
        # Apply search strategy
        if self.strategy == SearchStrategy.HASHTAG:
            # Use comprehensive variants for maximum coverage
            if self.additional_filters.get('use_variants', True):
                variants = self.build_comprehensive_variants(self.label)
                # Combine with OR for broader reach
                query_parts.append(f"({' OR '.join(variants)})")
            else:
                query_parts.append(self.label)
        elif self.strategy == SearchStrategy.KEYWORD:
            query_parts.append(f'"{self.label}"')  # Exact phrase
        elif self.strategy == SearchStrategy.USER:
            query_parts.append(f"from:{self.label.lstrip('@')}")
        elif self.strategy == SearchStrategy.LOCATION:
            query_parts.append(f"near:{self.label}")
        elif self.strategy == SearchStrategy.ADVANCED:
            query_parts.append(self.label)  # Use label as-is for advanced queries
        
        # Add keyword filter
        if self.keyword:
            query_parts.append(self.keyword)
        
        # Advanced filters
        filters = self.additional_filters
        
        if filters.get('min_likes'):
            query_parts.append(f"min_faves:{filters['min_likes']}")
        if filters.get('min_retweets'):
            query_parts.append(f"min_retweets:{filters['min_retweets']}")
        if filters.get('min_replies'):
            query_parts.append(f"min_replies:{filters['min_replies']}")
        
        # Content type filters
        if filters.get('has_media'):
            query_parts.append("filter:media")
        if filters.get('has_video'):
            query_parts.append("filter:videos")
        if filters.get('has_images'):
            query_parts.append("filter:images")
        if filters.get('has_links'):
            query_parts.append("filter:links")
        if filters.get('has_mentions'):
            query_parts.append("filter:mentions")
        
        # Tweet type filters
        if filters.get('filter_replies'):
            query_parts.append("filter:replies")
        if filters.get('filter_quotes'):
            query_parts.append("filter:quote")
        if filters.get('filter_spaces'):
            query_parts.append("filter:spaces")
        
        # User filters
        if filters.get('verified_only'):
            query_parts.append("filter:verified")
        if filters.get('blue_verified_only'):
            query_parts.append("filter:blue_verified")
        
        # Exclude filters
        if filters.get('exclude_retweets'):
            query_parts.append("-filter:retweets")
        if filters.get('exclude_replies'):
            query_parts.append("-filter:replies")
        if filters.get('exclude_quotes'):
            query_parts.append("-filter:quote")
        
        # Language filter (use instance language if set, otherwise use filter)
        # ONLY add if it's a valid 2-letter language code, NOT 'all'
        lang = self.language or filters.get('language')
        if lang and lang != 'all' and len(lang) == 2:
            query_parts.append(f"lang:{lang}")
        
        # URL filter
        if filters.get('url_contains'):
            query_parts.append(f"url:{filters['url_contains']}")
        
        # Mention/to filters
        if filters.get('to_user'):
            query_parts.append(f"to:{filters['to_user'].lstrip('@')}")
        if filters.get('mention_user'):
            query_parts.append(f"@{filters['mention_user'].lstrip('@')}")
        
        # Date range
        query_parts.append(f"since:{self.start_date.strftime('%Y-%m-%d')}")
        query_parts.append(f"until:{self.end_date.strftime('%Y-%m-%d')}")
        
        return " ".join(query_parts)
    
    def __repr__(self):
        return f"Job({self.label}, keyword={self.keyword}, {self.start_date.date()} to {self.end_date.date()})"


def extract_rich_metadata(tweet) -> Dict:
    """
    Extract rich metadata from tweet object
    Similar to ApiDojoTwitterScraper parsing logic
    """
    try:
        # Basic tweet data
        tweet_data = {
            'id': str(tweet.id),
            'url': tweet.url,
            'username': tweet.user.username,
            'user_id': str(tweet.user.id) if hasattr(tweet.user, 'id') else None,
            'user_display_name': tweet.user.displayname if hasattr(tweet.user, 'displayname') else None,
            'text': tweet.rawContent,
            'timestamp': tweet.date,
            'source': 2,  # X/Twitter
        }
        
        # Tweet metadata
        tweet_data['language'] = tweet.lang if hasattr(tweet, 'lang') else None
        tweet_data['is_reply'] = tweet.inReplyToTweetId is not None
        tweet_data['is_retweet'] = tweet.retweetedTweet is not None
        tweet_data['is_quote'] = tweet.quotedTweet is not None
        tweet_data['in_reply_to_user_id'] = str(tweet.inReplyToTweetId) if tweet.inReplyToTweetId else None
        tweet_data['quoted_tweet_id'] = str(tweet.quotedTweet.id) if tweet.quotedTweet else None
        tweet_data['conversation_id'] = str(tweet.conversationId) if hasattr(tweet, 'conversationId') else None
        
        # Engagement metrics
        tweet_data['like_count'] = tweet.likeCount if hasattr(tweet, 'likeCount') else None
        tweet_data['retweet_count'] = tweet.retweetCount if hasattr(tweet, 'retweetCount') else None
        tweet_data['reply_count'] = tweet.replyCount if hasattr(tweet, 'replyCount') else None
        tweet_data['quote_count'] = tweet.quoteCount if hasattr(tweet, 'quoteCount') else None
        tweet_data['view_count'] = tweet.viewCount if hasattr(tweet, 'viewCount') else None
        tweet_data['bookmark_count'] = tweet.bookmarkCount if hasattr(tweet, 'bookmarkCount') else None
        
        # User profile data
        if hasattr(tweet, 'user') and tweet.user:
            user = tweet.user
            tweet_data['user_verified'] = getattr(user, 'verified', False)
            tweet_data['user_blue_verified'] = getattr(user, 'blueVerified', False)
            tweet_data['user_description'] = getattr(user, 'rawDescription', None)
            tweet_data['user_location'] = getattr(user, 'location', None)
            tweet_data['user_followers_count'] = getattr(user, 'followersCount', None)
            tweet_data['user_following_count'] = getattr(user, 'followingCount', None)
            tweet_data['profile_image_url'] = getattr(user, 'profileImageUrl', None)
        
        # Hashtags
        tweet_data['hashtags'] = tweet.hashtags if hasattr(tweet, 'hashtags') else []
        
        # Media URLs
        media_urls = []
        if hasattr(tweet, 'media') and tweet.media:
            if hasattr(tweet.media, 'photos'):
                for photo in tweet.media.photos:
                    media_urls.append(photo.url if hasattr(photo, 'url') else str(photo))
            if hasattr(tweet.media, 'videos'):
                for video in tweet.media.videos:
                    if hasattr(video, 'thumbnailUrl'):
                        media_urls.append(video.thumbnailUrl)
        tweet_data['media_urls'] = media_urls
        
        return tweet_data
    
    except Exception as e:
        logger.warning(f"Error extracting metadata: {e}")
        # Return basic data on error
        return {
            'id': str(tweet.id),
            'url': tweet.url,
            'username': tweet.user.username,
            'text': tweet.rawContent,
            'timestamp': tweet.date,
            'source': 2,
        }


async def expand_network(api: API, storage: TweetStorage, seed_tweet_ids: Set[str], 
                        job: ScrapingJob, max_depth: int = 1) -> Dict:
    """
    Expand collection by following conversations, quoted tweets, and user networks
    
    Args:
        api: Twitter API instance
        storage: Storage instance
        seed_tweet_ids: Set of tweet IDs to expand from
        job: Job configuration
        max_depth: Maximum depth for network expansion
    
    Returns:
        Statistics dictionary
    """
    if max_depth < 1 or not seed_tweet_ids:
        return {"network_tweets": 0, "network_users": 0}
    
    logger.info(f"[{job.label}] Expanding network from {len(seed_tweet_ids)} seed tweets (depth={max_depth})...")
    
    stats = {"network_tweets": 0, "network_users": 0, "retweeters": 0}
    new_tweet_ids = set()
    processed_users = set()
    
    for tweet_id in list(seed_tweet_ids)[:100]:  # Limit to first 100 to avoid overwhelming
        try:
            # Get conversation thread (replies)
            reply_count = 0
            async for tweet in api.tweet_replies(tweet_id, limit=50):
                if tweet.id not in seed_tweet_ids and tweet.id not in new_tweet_ids:
                    new_tweet_ids.add(tweet.id)
                    tweet_data = extract_rich_metadata(tweet)
                    tweet_data['job_label'] = f"{job.label}_network"
                    tweet_data['job_keyword'] = job.keyword
                    storage.store_tweet(tweet_data)
                    stats["network_tweets"] += 1
                    reply_count += 1
            
            if reply_count > 0:
                logger.debug(f"[{job.label}] Found {reply_count} replies for tweet {tweet_id}")
            
            # Get users who retweeted (sample)
            retweeter_count = 0
            async for user in api.retweeters(tweet_id, limit=20):
                if user.id not in processed_users:
                    processed_users.add(user.id)
                    stats["retweeters"] += 1
                    
                    # Get recent tweets from these users (light sampling)
                    async for user_tweet in api.user_tweets(user.id, limit=10):
                        if user_tweet.id not in seed_tweet_ids and user_tweet.id not in new_tweet_ids:
                            new_tweet_ids.add(user_tweet.id)
                            tweet_data = extract_rich_metadata(user_tweet)
                            tweet_data['job_label'] = f"{job.label}_network"
                            tweet_data['job_keyword'] = job.keyword
                            storage.store_tweet(tweet_data)
                            stats["network_tweets"] += 1
                            retweeter_count += 1
            
            if retweeter_count > 0:
                logger.debug(f"[{job.label}] Found {retweeter_count} tweets from retweeters")
        
        except Exception as e:
            logger.warning(f"[{job.label}] Error expanding from tweet {tweet_id}: {e}")
    
    stats["network_users"] = len(processed_users)
    logger.info(f"[{job.label}] Network expansion complete: {stats['network_tweets']} tweets from {stats['network_users']} users")
    
    return stats


async def scrape_job(api: API, job: ScrapingJob, storage: TweetStorage) -> Dict:
    """
    Enhanced scraping with network expansion and smart pagination
    Store in SQLite database with resume capability
    """
    query = job.build_query()
    logger.info(f"Starting job: {job}")
    logger.info(f"Query: {query}")
    logger.info(f"Strategy: {job.strategy.value}")
    
    # Show search variants if using HASHTAG strategy with variants enabled
    if job.strategy == SearchStrategy.HASHTAG and job.additional_filters.get('use_variants', True):
        variants = job.build_comprehensive_variants(job.label)
        logger.info(f"Search variants ({len(variants)}): {', '.join(variants)}")
    
    # Only log language if it's a valid 2-letter code
    if job.language and job.language != 'all' and len(job.language) == 2:
        logger.info(f"Language: {job.language}")
    if job.enable_network_expansion:
        logger.info(f"Network expansion: enabled (depth={job.max_network_depth})")
    
    # Initialize pagination state manager
    pagination_mgr = PaginationStateManager("pagination_state.db")
    query_params = {
        "label": job.label,
        "strategy": job.strategy.value,
        "language": job.language,
        "dates": f"{job.start_date.date()}_to_{job.end_date.date()}"
    }
    query_hash = pagination_mgr.generate_query_hash(query, query_params)
    
    # Check for existing pagination state (resume capability)
    existing_state = await pagination_mgr.get_state(query_hash)
    if existing_state and not existing_state.get('completed'):
        logger.info(f"[{job.label}] Resuming from previous run - {existing_state['items_fetched']} tweets already collected")
    
    tweet_ids_seen = set()
    seed_tweet_ids = set()  # For network expansion
    
    stats = {
        "job": str(job),
        "query": query,
        "posts": 0,
        "replies": 0,
        "retweets": 0,
        "total": 0,
        "start_time": datetime.now().isoformat(),
        "end_time": None,
    }
    
    try:
        # Scrape main posts
        logger.info(f"[{job.label}] Searching posts...")
        async for tweet in api.search(query, limit=-1):
            if tweet.id not in tweet_ids_seen:
                tweet_ids_seen.add(tweet.id)
                
                # Check keyword filter if specified
                if job.keyword:
                    if job.keyword.lower() not in tweet.rawContent.lower():
                        continue
                
                # Extract rich metadata
                tweet_data = extract_rich_metadata(tweet)
                tweet_data['job_label'] = job.label
                tweet_data['job_keyword'] = job.keyword
                tweet_data['search_strategy'] = job.strategy.value
                if job.language:
                    tweet_data['search_language'] = job.language
                
                # Store in database
                storage.store_tweet(tweet_data)
                stats["posts"] += 1
                
                # Track for network expansion
                if job.enable_network_expansion:
                    seed_tweet_ids.add(tweet.id)
                
                # Log progress every 100 tweets
                if stats["posts"] % 100 == 0:
                    logger.info(f"[{job.label}] Stored {stats['posts']} posts")
                
                # Get replies for this tweet
                try:
                    reply_count = 0
                    reply_limit = MAX_REPLIES_PER_TWEET if SCRAPE_ALL_REPLIES else 100
                    async for reply in api.tweet_replies(tweet.id, limit=reply_limit):
                        if reply.id not in tweet_ids_seen:
                            tweet_ids_seen.add(reply.id)
                            
                            # Extract rich metadata for reply
                            reply_data = extract_rich_metadata(reply)
                            reply_data['job_label'] = job.label
                            reply_data['job_keyword'] = job.keyword
                            reply_data['in_reply_to_user_id'] = str(tweet.user.id) if hasattr(tweet.user, 'id') else None
                            
                            # Store reply
                            storage.store_tweet(reply_data)
                            stats["replies"] += 1
                            reply_count += 1
                    
                    if reply_count > 0:
                        logger.debug(f"[{job.label}] Stored {reply_count} replies for tweet {tweet.id}")
                
                except Exception as e:
                    logger.warning(f"[{job.label}] Error getting replies for {tweet.id}: {e}")
                
                # Track retweets
                if tweet.retweetedTweet:
                    stats["retweets"] += 1
                
                # Update pagination state every 100 tweets
                if stats["posts"] % 100 == 0:
                    await pagination_mgr.create_or_update_state(
                        query_hash=query_hash,
                        query_text=query,
                        items_fetched=stats["posts"],
                        completed=False
                    )
        
        # Mark query as completed
        await pagination_mgr.create_or_update_state(
            query_hash=query_hash,
            query_text=query,
            items_fetched=stats["posts"],
            completed=True
        )
        logger.info(f"[{job.label}] Query marked as completed in pagination state")
        
        # Network expansion phase
        if job.enable_network_expansion and seed_tweet_ids:
            logger.info(f"[{job.label}] Starting network expansion from {len(seed_tweet_ids)} tweets...")
            network_stats = await expand_network(
                api, storage, seed_tweet_ids, job, job.max_network_depth
            )
            stats.update(network_stats)
    
    except KeyboardInterrupt:
        logger.info(f"[{job.label}] Interrupted. Saving progress...")
        # Save pagination state on interruption
        await pagination_mgr.create_or_update_state(
            query_hash=query_hash,
            query_text=query,
            items_fetched=stats["posts"],
            completed=False
        )
        logger.info(f"[{job.label}] Progress saved. {stats['posts'] + stats['replies']} tweets stored. Can resume later.")
    except Exception as e:
        logger.error(f"[{job.label}] Error: {e}")
        # Save progress even on error
        try:
            await pagination_mgr.create_or_update_state(
                query_hash=query_hash,
                query_text=query,
                items_fetched=stats["posts"],
                completed=False
            )
        except:
            pass
    
    # Calculate stats
    stats["total"] = stats["posts"] + stats["replies"]
    stats["end_time"] = datetime.now().isoformat()
    
    logger.info(f"[{job.label}] Stored {stats['total']} tweets in database")
    return stats


async def scrape_jobs_concurrently(jobs: List[ScrapingJob], max_concurrent: int = 10):
    """
    Scrape multiple jobs concurrently
    All data stored in SQLite database
    """
    # Create storage
    storage = TweetStorage("tweets.db")
    
    # Create API instance (shared across jobs)
    api = API("accounts.db")
    
    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def scrape_with_semaphore(job):
        async with semaphore:
            return await scrape_job(api, job, storage)
    
    # Log start
    logger.info("="*80)
    logger.info(f"STARTING CONCURRENT SCRAPING: {len(jobs)} jobs")
    logger.info(f"Max concurrent: {max_concurrent}")
    logger.info(f"Database: tweets.db")
    logger.info("="*80)
    
    # Run jobs concurrently
    start_time = datetime.now()
    results = await asyncio.gather(*[scrape_with_semaphore(job) for job in jobs], return_exceptions=True)
    duration = datetime.now() - start_time
    
    # Calculate totals
    total_tweets = 0
    total_posts = 0
    total_replies = 0
    total_retweets = 0
    
    for result in results:
        if isinstance(result, dict):
            total_tweets += result.get("total", 0)
            total_posts += result.get("posts", 0)
            total_replies += result.get("replies", 0)
            total_retweets += result.get("retweets", 0)
        elif isinstance(result, Exception):
            logger.error(f"Job failed: {result}")
    
    # Get database stats
    db_stats = storage.get_stats()
    
    # Final stats
    logger.info("="*80)
    logger.info("SCRAPING COMPLETE")
    logger.info("="*80)
    logger.info(f"Jobs completed: {len(jobs)}")
    logger.info(f"New tweets: {total_tweets:,}")
    logger.info(f"  - Posts: {total_posts:,}")
    logger.info(f"  - Replies: {total_replies:,}")
    logger.info(f"  - Retweets: {total_retweets:,}")
    logger.info(f"Duration: {duration}")
    logger.info(f"Rate: {total_tweets / duration.total_seconds():.2f} tweets/sec")
    logger.info("")
    logger.info("DATABASE STATS:")
    logger.info(f"  Total tweets in DB: {db_stats['total_tweets']:,}")
    logger.info(f"  Database size: {db_stats['total_size_mb']:.2f} MB")
    logger.info(f"  Date range: {db_stats['earliest_tweet']} to {db_stats['latest_tweet']}")
    logger.info("")
    logger.info("Top hashtags:")
    for label, count in list(db_stats['by_label'].items())[:5]:
        logger.info(f"  {label}: {count:,} tweets")
    logger.info("="*80)


def load_jobs_from_json(filepath: str) -> List[ScrapingJob]:
    """Load scraping jobs from JSON file with enhanced parameters"""
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    jobs = []
    for item in data:
        job = ScrapingJob(
            label=item.get('label'),
            keyword=item.get('keyword'),
            start_datetime=item.get('start_datetime'),
            end_datetime=item.get('end_datetime'),
            weight=item.get('weight', 1.0),
            strategy=item.get('strategy', 'hashtag'),
            additional_filters=item.get('additional_filters'),
            language=item.get('language'),
            enable_network_expansion=item.get('enable_network_expansion', False),
            max_network_depth=item.get('max_network_depth', 1),
        )
        jobs.append(job)
    
    return jobs


def create_multilingual_jobs(base_jobs: List[ScrapingJob], 
                             languages: Optional[List[str]] = None) -> List[ScrapingJob]:
    """
    Create jobs for multiple languages
    
    Args:
        base_jobs: Base jobs to replicate
        languages: List of language codes (e.g., ['en', 'es', 'fr'])
                  If None, uses default set
    
    Returns:
        List of jobs with language variants
    """
    if languages is None:
        languages = ['en', 'es', 'fr', 'de', 'ja', 'ko', 'pt', 'ar', 'hi', 'zh']
    
    multilingual_jobs = []
    
    for job in base_jobs:
        # Skip if job already has language set
        if job.language:
            multilingual_jobs.append(job)
            continue
        
        # Create variant for each language
        for lang in languages:
            new_job = ScrapingJob(
                label=job.label,
                keyword=job.keyword,
                start_datetime=job.start_datetime,
                end_datetime=job.end_datetime,
                weight=job.weight / len(languages),  # Distribute weight
                strategy=job.strategy.value if isinstance(job.strategy, SearchStrategy) else job.strategy,
                additional_filters=job.additional_filters.copy() if job.additional_filters else {},
                language=lang,
                enable_network_expansion=job.enable_network_expansion,
                max_network_depth=job.max_network_depth,
            )
            multilingual_jobs.append(new_job)
    
    return multilingual_jobs


async def main():
    # Configure logging
    set_log_level("INFO")
    
    # Load jobs from x.json
    try:
        jobs = load_jobs_from_json("x.json")
        logger.info(f"Loaded {len(jobs)} jobs from x.json")
    except FileNotFoundError:
        logger.error("x.json not found! Please create x.json with scraping jobs.")
        logger.info("\nExpected format:")
        logger.info('[')
        logger.info('  {')
        logger.info('    "label": "#opentensor",')
        logger.info('    "keyword": null,')
        logger.info('    "start_datetime": null,')
        logger.info('    "end_datetime": null,')
        logger.info('    "weight": 2.87')
        logger.info('  }')
        logger.info(']')
        return
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in x.json: {e}")
        return
    
    if not jobs:
        logger.warning("No jobs found in x.json")
        return
    
    # Apply multi-language strategy based on configuration
    if ENABLE_MULTI_LANGUAGE:
        logger.info(f"Multi-language mode ENABLED: Creating jobs for {len(TOP_LANGUAGES)} languages")
        logger.info(f"Languages: {', '.join(TOP_LANGUAGES)}")
        jobs = create_multilingual_jobs(jobs, TOP_LANGUAGES)
        logger.info(f"Expanded to {len(jobs)} total jobs")
    else:
        logger.info("Multi-language mode DISABLED: Scraping in all languages (no filter)")
    
    # Show jobs
    logger.info("\nJobs to scrape:")
    for i, job in enumerate(jobs, 1):
        keyword_str = f" + keyword: {job.keyword}" if job.keyword else ""
        lang_str = f" [lang:{job.language}]" if job.language else ""
        strategy_str = f" ({job.strategy.value})" if job.strategy != SearchStrategy.HASHTAG else ""
        network_str = " [+network]" if job.enable_network_expansion else ""
        logger.info(f"  {i}. {job.label}{keyword_str}{lang_str}{strategy_str}{network_str} ({job.start_date.date()} to {job.end_date.date()})")
    
    # Start scraping (max 10 concurrent to avoid overwhelming the system)
    await scrape_jobs_concurrently(jobs, max_concurrent=10)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n\nStopping... (Ctrl+C)")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

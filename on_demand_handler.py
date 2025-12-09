#!/usr/bin/env python3
"""
On-Demand Scraping Handler for aggressive_scrape.py

This module provides on-demand scraping functionality that can be triggered
separately from the main scraping loop. It ensures 100% field validation
matching the XContent model that validators expect.

Usage:
    - Create on_demand_requests.json with request parameters
    - Script will process requests and output to on_demand_results/
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

# Add data-universe to path for imports BEFORE any imports from common
# Get the parent directory (data-universe) dynamically
current_dir = Path(__file__).resolve().parent
data_universe_dir = current_dir.parent
sys.path.insert(0, str(data_universe_dir))

# Now we can import from data-universe
from common.data import DataEntity, DataLabel, DataSource
from scraping.x.model import XContent

# Import from aggressive_scrape (in same directory)
sys.path.insert(0, str(current_dir))
from aggressive_scrape import extract_rich_metadata, TweetStorage, GlobalDeduplication

# Import twscrape after path setup
from twscrape import API
from twscrape.logger import set_log_level, logger


class OnDemandRequest:
    """Represents an on-demand scraping request"""
    
    def __init__(
        self,
        request_id: str,
        usernames: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
        url: Optional[str] = None,
        keyword_mode: str = "any",  # "any" or "all"
        start_datetime: Optional[str] = None,
        end_datetime: Optional[str] = None,
        limit: int = 100
    ):
        self.request_id = request_id
        self.usernames = usernames or []
        self.keywords = keywords or []
        self.url = url
        self.keyword_mode = keyword_mode
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime
        self.limit = limit
    
    def build_query(self) -> str:
        """Build Twitter search query from request parameters"""
        query_parts = []
        
        # Handle URL-based search (single tweet)
        if self.url:
            # For URL, we'll use tweet_details API directly
            return None
        
        # Add usernames with OR logic
        if self.usernames:
            username_queries = []
            for username in self.usernames:
                clean_username = username.removeprefix('@').strip()
                username_queries.append(f"from:{clean_username}")
            if username_queries:
                query_parts.append(f"({' OR '.join(username_queries)})")
        
        # Add keywords with specified logic
        if self.keywords:
            quoted_keywords = [f'"{keyword}"' for keyword in self.keywords]
            if self.keyword_mode == "all":
                # AND logic
                for keyword in quoted_keywords:
                    query_parts.append(keyword)
            else:  # "any"
                # OR logic
                query_parts.append(f"({' OR '.join(quoted_keywords)})")
        
        # Add date range if provided
        if self.start_datetime:
            try:
                start_dt = datetime.fromisoformat(self.start_datetime.replace('Z', '+00:00'))
                query_parts.append(f"since:{start_dt.strftime('%Y-%m-%d')}")
            except:
                pass
        
        if self.end_datetime:
            try:
                end_dt = datetime.fromisoformat(self.end_datetime.replace('Z', '+00:00'))
                query_parts.append(f"until:{end_dt.strftime('%Y-%m-%d')}")
            except:
                pass
        
        # If no specific criteria, add default
        if not query_parts:
            query_parts.append("e")  # Most common letter
        
        return " ".join(query_parts)


def validate_xcontent_fields(tweet_data: dict) -> tuple[bool, str]:
    """
    Validate that tweet data has all required fields for XContent model
    Returns: (is_valid, error_message)
    """
    # Required fields for XContent
    required_fields = {
        'username': str,
        'text': str,
        'url': str,
        'timestamp': datetime,
        'tweet_hashtags': list,
    }
    
    for field, field_type in required_fields.items():
        if field not in tweet_data:
            return False, f"Missing required field: {field}"
        
        if not isinstance(tweet_data[field], field_type):
            return False, f"Field '{field}' has wrong type. Expected {field_type.__name__}, got {type(tweet_data[field]).__name__}"
    
    # Validate tweet_hashtags format
    if not all(isinstance(tag, str) for tag in tweet_data['tweet_hashtags']):
        return False, "tweet_hashtags must be a list of strings"
    
    return True, "Valid"


def convert_to_xcontent(tweet_data: dict) -> XContent:
    """
    Convert tweet data to XContent model with 100% field validation
    """
    # Ensure timestamp is datetime object
    timestamp = tweet_data['timestamp']
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    
    # Ensure timezone
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    
    return XContent(
        # Required fields
        username=tweet_data['username'],
        text=tweet_data['text'],
        url=tweet_data['url'],
        timestamp=timestamp,
        tweet_hashtags=tweet_data.get('tweet_hashtags', []),
        
        # Optional media
        media=tweet_data.get('media_urls') if tweet_data.get('media_urls') else None,
        
        # Enhanced user fields
        user_id=tweet_data.get('user_id'),
        user_display_name=tweet_data.get('user_display_name'),
        user_verified=tweet_data.get('user_verified'),
        
        # Non-dynamic tweet metadata
        tweet_id=tweet_data.get('id'),
        is_reply=tweet_data.get('is_reply'),
        is_quote=tweet_data.get('is_quote'),
        
        # Additional metadata
        conversation_id=tweet_data.get('conversation_id'),
        in_reply_to_user_id=tweet_data.get('in_reply_to_user_id'),
        
        # Static tweet metadata
        language=tweet_data.get('language'),
        in_reply_to_username=None,  # Not available in twscrape
        quoted_tweet_id=tweet_data.get('quoted_tweet_id'),
        
        # Dynamic engagement metrics
        like_count=tweet_data.get('like_count'),
        retweet_count=tweet_data.get('retweet_count'),
        reply_count=tweet_data.get('reply_count'),
        quote_count=tweet_data.get('quote_count'),
        view_count=tweet_data.get('view_count'),
        bookmark_count=tweet_data.get('bookmark_count'),
        
        # User profile data
        user_blue_verified=tweet_data.get('user_blue_verified'),
        user_description=tweet_data.get('user_description'),
        user_location=tweet_data.get('user_location'),
        profile_image_url=tweet_data.get('profile_image_url'),
        cover_picture_url=None,  # Not available in twscrape
        user_followers_count=tweet_data.get('user_followers_count'),
        user_following_count=tweet_data.get('user_following_count'),
    )


async def process_on_demand_request(
    api: API,
    request: OnDemandRequest,
    storage: TweetStorage
) -> Dict:
    """
    Process a single on-demand scraping request
    
    Returns statistics about the scrape
    """
    logger.info(f"[OnDemand {request.request_id}] Processing request...")
    
    stats = {
        "request_id": request.request_id,
        "tweets_found": 0,
        "tweets_valid": 0,
        "tweets_stored": 0,
        "errors": [],
        "start_time": datetime.now().isoformat(),
    }
    
    try:
        # Handle URL-based request (single tweet)
        if request.url:
            logger.info(f"[OnDemand {request.request_id}] Fetching single tweet: {request.url}")
            
            # Extract tweet ID from URL
            tweet_id = None
            if '/status/' in request.url:
                try:
                    tweet_id = request.url.split('/status/')[1].split('?')[0].split('/')[0]
                    tweet_id = int(tweet_id)
                except:
                    stats['errors'].append("Invalid tweet URL format")
                    return stats
            
            if tweet_id:
                try:
                    tweet = await api.tweet_details(tweet_id)
                    if tweet:
                        stats['tweets_found'] = 1
                        
                        # Extract metadata
                        tweet_data = extract_rich_metadata(tweet)
                        
                        # Validate fields
                        is_valid, error_msg = validate_xcontent_fields(tweet_data)
                        if is_valid:
                            stats['tweets_valid'] = 1
                            
                            # Convert to XContent
                            x_content = convert_to_xcontent(tweet_data)
                            
                            # Convert to DataEntity
                            data_entity = XContent.to_data_entity(content=x_content)
                            
                            # Store
                            storage.store_tweet(tweet_data)
                            stats['tweets_stored'] = 1
                            
                            logger.info(f"[OnDemand {request.request_id}] ✅ Successfully stored tweet")
                        else:
                            stats['errors'].append(f"Validation failed: {error_msg}")
                            logger.error(f"[OnDemand {request.request_id}] ❌ Validation failed: {error_msg}")
                    else:
                        stats['errors'].append("Tweet not found")
                
                except Exception as e:
                    stats['errors'].append(f"Error fetching tweet: {str(e)}")
                    logger.error(f"[OnDemand {request.request_id}] Error: {e}")
        
        else:
            # Handle query-based request
            query = request.build_query()
            if not query:
                stats['errors'].append("Could not build valid query")
                return stats
            
            logger.info(f"[OnDemand {request.request_id}] Query: {query}")
            
            tweet_count = 0
            async for tweet in api.search(query, limit=request.limit):
                stats['tweets_found'] += 1
                
                # Extract metadata
                tweet_data = extract_rich_metadata(tweet)
                
                # Validate fields
                is_valid, error_msg = validate_xcontent_fields(tweet_data)
                
                if is_valid:
                    stats['tweets_valid'] += 1
                    
                    try:
                        # Convert to XContent for validation
                        x_content = convert_to_xcontent(tweet_data)
                        
                        # Store
                        storage.store_tweet(tweet_data)
                        stats['tweets_stored'] += 1
                        tweet_count += 1
                        
                        if tweet_count % 10 == 0:
                            logger.info(f"[OnDemand {request.request_id}] Stored {tweet_count} tweets...")
                    
                    except Exception as e:
                        stats['errors'].append(f"Error storing tweet {tweet.id}: {str(e)}")
                        logger.error(f"[OnDemand {request.request_id}] Error storing: {e}")
                else:
                    stats['errors'].append(f"Tweet {tweet.id}: {error_msg}")
                    logger.warning(f"[OnDemand {request.request_id}] Validation failed for {tweet.id}: {error_msg}")
            
            logger.info(f"[OnDemand {request.request_id}] ✅ Completed: {stats['tweets_stored']} tweets stored")
    
    except Exception as e:
        stats['errors'].append(f"Fatal error: {str(e)}")
        logger.error(f"[OnDemand {request.request_id}] Fatal error: {e}")
    
    stats['end_time'] = datetime.now().isoformat()
    return stats


async def monitor_on_demand_requests():
    """
    Monitor for on-demand requests and spawn workers to process them
    """
    set_log_level("INFO")
    
    # Create API and storage
    api = API("accounts.db")
    storage = TweetStorage()
    
    request_file = Path("on_demand_requests.json")
    results_dir = Path("on_demand_results")
    results_dir.mkdir(exist_ok=True)
    
    processed_requests = set()
    
    logger.info("🔥 ON-DEMAND SCRAPING: Started monitoring for requests...")
    
    while True:
        try:
            if request_file.exists():
                # Read requests
                with open(request_file, 'r') as f:
                    requests_data = json.load(f)
                
                # Process each request
                for req_data in requests_data:
                    request_id = req_data.get('request_id', 'unknown')
                    
                    # Skip if already processed
                    if request_id in processed_requests:
                        continue
                    
                    # Create request object
                    request = OnDemandRequest(
                        request_id=request_id,
                        usernames=req_data.get('usernames'),
                        keywords=req_data.get('keywords'),
                        url=req_data.get('url'),
                        keyword_mode=req_data.get('keyword_mode', 'any'),
                        start_datetime=req_data.get('start_datetime'),
                        end_datetime=req_data.get('end_datetime'),
                        limit=req_data.get('limit', 100)
                    )
                    
                    # Spawn worker to process (runs concurrently)
                    logger.info(f"🔥 ON-DEMAND: Spawning worker for request {request_id}")
                    
                    # Process request
                    stats = await process_on_demand_request(api, request, storage)
                    
                    # Save results
                    result_file = results_dir / f"{request_id}_result.json"
                    with open(result_file, 'w') as f:
                        json.dump(stats, f, indent=2)
                    
                    processed_requests.add(request_id)
                    logger.info(f"✅ ON-DEMAND: Completed request {request_id}")
        
        except Exception as e:
            logger.error(f"Error in on-demand monitor: {e}")
        
        # Wait before checking again
        await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(monitor_on_demand_requests())
    except KeyboardInterrupt:
        logger.info("\n\nStopping on-demand handler...")

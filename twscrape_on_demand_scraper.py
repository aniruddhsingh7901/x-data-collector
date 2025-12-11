#!/usr/bin/env python3
"""
TwScrape On-Demand Scraper for Miner Integration

This class implements the exact same interface as ApiDojoTwitterScraper
so it can be used as a drop-in replacement in miner.py

100% field validation compatible with XContent model and validators.
"""

import sys
from pathlib import Path
from typing import List, Optional
import datetime as dt

# Add data-universe to path
current_dir = Path(__file__).resolve().parent
data_universe_dir = current_dir.parent
sys.path.insert(0, str(data_universe_dir))
sys.path.insert(0, str(current_dir))

# Import from data-universe
from common.data import DataEntity, DataLabel, DataSource
from common.protocol import KeywordMode
from scraping.x.model import XContent

# Import from aggressive_scrape
from aggressive_scrape import extract_rich_metadata

# Import twscrape
from twscrape import API
from twscrape.logger import logger


class TwScrapeOnDemandScraper:
    """
    On-demand scraper using twscrape (free, no API keys needed)
    100% compatible with ApiDojoTwitterScraper interface for miner integration
    
    IMPORTANT: Uses separate account pool (accounts_ondemand.db) to avoid 
    interference with aggressive_scrape.py background scraping
    """
    
    def __init__(self, accounts_db_path: str = None):
        """
        Initialize scraper with dedicated on-demand accounts database
        
        Args:
            accounts_db_path: Path to accounts database. 
                            Defaults to 'accounts_ondemand.db' in x-data-collector/
        """
        if accounts_db_path is None:
            # Use dedicated on-demand account pool (separate from aggressive_scrape.py)
            current_dir = Path(__file__).resolve().parent
            accounts_db_path = str(current_dir / "accounts_ondemand.db")
        
        self.api = API(accounts_db_path)
        logger.info(f"TwScrape On-Demand initialized with account pool: {accounts_db_path}")
    
    async def on_demand_scrape(
        self,
        usernames: List[str] = None,
        keywords: List[str] = None,
        url: str = None,
        keyword_mode: KeywordMode = "all",
        start_datetime: dt.datetime = None,
        end_datetime: dt.datetime = None,
        limit: int = 100
    ) -> List[DataEntity]:
        """
        Scrapes Twitter/X data based on specific search criteria.
        
        100% COMPATIBLE with ApiDojoTwitterScraper.on_demand_scrape() interface
        
        Args:
            usernames: List of target usernames (without @, OR logic between them)
            keywords: List of keywords to search for
            url: Single tweet URL for direct tweet lookup
            keyword_mode: "any" (OR logic) or "all" (AND logic) for keyword matching
            start_datetime: Earliest datetime for content (UTC)
            end_datetime: Latest datetime for content (UTC)
            limit: Maximum number of items to return
        
        Returns:
            List of DataEntity objects matching the criteria (ready for validators)
        """
        
        logger.info(f"🔥 TwScrape On-Demand: usernames={usernames}, keywords={keywords}, url={url}, limit={limit}")
        
        data_entities = []
        
        try:
            # CASE 1: URL-based search (single tweet)
            if url:
                logger.info(f"TwScrape: Fetching single tweet from URL: {url}")
                
                # Extract tweet ID from URL
                tweet_id = self._extract_tweet_id_from_url(url)
                if not tweet_id:
                    logger.error(f"TwScrape: Invalid tweet URL: {url}")
                    return []
                
                try:
                    tweet = await self.api.tweet_details(tweet_id)
                    if tweet:
                        # Extract rich metadata using aggressive_scrape's function
                        tweet_data = extract_rich_metadata(tweet)
                        
                        # Convert to XContent
                        x_content = self._tweet_data_to_xcontent(tweet_data)
                        
                        # Convert to DataEntity
                        data_entity = XContent.to_data_entity(content=x_content)
                        data_entities.append(data_entity)
                        
                        logger.info(f"TwScrape: ✅ Successfully fetched tweet {tweet_id}")
                    else:
                        logger.warning(f"TwScrape: Tweet {tweet_id} not found")
                
                except Exception as e:
                    logger.error(f"TwScrape: Error fetching tweet {tweet_id}: {e}")
                
                return data_entities
            
            # CASE 2: Query-based search
            query = self._build_query(
                usernames=usernames,
                keywords=keywords,
                keyword_mode=keyword_mode,
                start_datetime=start_datetime,
                end_datetime=end_datetime
            )
            
            if not query:
                logger.error("TwScrape: Could not build valid query")
                return []
            
            logger.info(f"TwScrape: Query: {query}")
            logger.info(f"TwScrape: Limit: {limit}")
            
            # Search tweets
            tweet_count = 0
            async for tweet in self.api.search(query, limit=limit):
                try:
                    # Extract rich metadata using aggressive_scrape's function
                    tweet_data = extract_rich_metadata(tweet)
                    
                    # Convert to XContent (validates fields)
                    x_content = self._tweet_data_to_xcontent(tweet_data)
                    
                    # Convert to DataEntity
                    data_entity = XContent.to_data_entity(content=x_content)
                    data_entities.append(data_entity)
                    
                    tweet_count += 1
                    
                    if tweet_count % 10 == 0:
                        logger.info(f"TwScrape: Processed {tweet_count} tweets...")
                    
                    # Stop if we've reached the limit
                    if limit and tweet_count >= limit:
                        break
                
                except Exception as e:
                    logger.warning(f"TwScrape: Error processing tweet {tweet.id}: {e}")
                    continue
            
            logger.info(f"TwScrape: ✅ Completed - {len(data_entities)} tweets scraped")
        
        except Exception as e:
            logger.error(f"TwScrape: Fatal error in on_demand_scrape: {e}")
        
        return data_entities
    
    def _extract_tweet_id_from_url(self, url: str) -> Optional[int]:
        """Extract tweet ID from Twitter/X URL"""
        try:
            if '/status/' in url:
                tweet_id_str = url.split('/status/')[1].split('?')[0].split('/')[0]
                return int(tweet_id_str)
        except:
            pass
        return None
    
    def _build_query(
        self,
        usernames: List[str] = None,
        keywords: List[str] = None,
        keyword_mode: str = "any",
        start_datetime: dt.datetime = None,
        end_datetime: dt.datetime = None
    ) -> str:
        """Build Twitter search query from parameters"""
        query_parts = []
        
        # Add usernames with OR logic
        if usernames:
            username_queries = []
            for username in usernames:
                clean_username = username.removeprefix('@').strip()
                if clean_username:
                    username_queries.append(f"from:{clean_username}")
            
            if username_queries:
                query_parts.append(f"({' OR '.join(username_queries)})")
        
        # Add keywords with specified logic
        if keywords:
            quoted_keywords = [f'"{keyword}"' for keyword in keywords]
            if keyword_mode == "all":
                # AND logic - add each keyword separately
                query_parts.extend(quoted_keywords)
            else:  # "any"
                # OR logic
                query_parts.append(f"({' OR '.join(quoted_keywords)})")
        
        # Add date range
        if start_datetime:
            query_parts.append(f"since:{start_datetime.strftime('%Y-%m-%d')}")
        
        if end_datetime:
            query_parts.append(f"until:{end_datetime.strftime('%Y-%m-%d')}")
        
        # If no specific criteria, add default search term
        if not query_parts or (not usernames and not keywords):
            query_parts.append("e")  # Most common letter in English
        
        return " ".join(query_parts)
    
    def _tweet_data_to_xcontent(self, tweet_data: dict) -> XContent:
        """
        Convert tweet data dictionary to XContent model
        Ensures 100% field validation for validators
        """
        # Ensure timestamp is datetime object with timezone
        timestamp = tweet_data.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        elif isinstance(timestamp, dt.datetime) and timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
        
        # Build XContent with all fields
        return XContent(
            # ===== REQUIRED FIELDS =====
            username=tweet_data['username'],
            text=tweet_data['text'],
            url=tweet_data['url'],
            timestamp=timestamp,
            tweet_hashtags=tweet_data.get('tweet_hashtags', []),
            
            # ===== OPTIONAL BASIC FIELDS =====
            media=tweet_data.get('media'),  # Already correct field name from aggressive_scrape
            
            # ===== ENHANCED USER FIELDS =====
            user_id=tweet_data.get('user_id'),
            user_display_name=tweet_data.get('user_display_name'),  # Already correct field name
            user_verified=tweet_data.get('user_verified'),
            
            # ===== NON-DYNAMIC TWEET METADATA =====
            tweet_id=tweet_data.get('tweet_id'),  # Already correct field name
            is_reply=tweet_data.get('is_reply'),
            is_quote=tweet_data.get('is_quote'),
            
            # ===== ADDITIONAL METADATA =====
            conversation_id=tweet_data.get('conversation_id'),
            in_reply_to_user_id=tweet_data.get('in_reply_to_user_id'),
            
            # ===== STATIC TWEET METADATA =====
            language=tweet_data.get('language'),
            in_reply_to_username=None,  # Not available in twscrape
            quoted_tweet_id=tweet_data.get('quoted_tweet_id'),
            
            # ===== DYNAMIC ENGAGEMENT METRICS =====
            like_count=tweet_data.get('like_count'),
            retweet_count=tweet_data.get('retweet_count'),
            reply_count=tweet_data.get('reply_count'),
            quote_count=tweet_data.get('quote_count'),
            view_count=tweet_data.get('view_count'),
            bookmark_count=tweet_data.get('bookmark_count'),
            
            # ===== USER PROFILE DATA =====
            user_blue_verified=tweet_data.get('user_blue_verified'),
            user_description=tweet_data.get('user_description'),
            user_location=tweet_data.get('user_location'),
            profile_image_url=tweet_data.get('profile_image_url'),
            cover_picture_url=None,  # Not available in twscrape
            user_followers_count=tweet_data.get('user_followers_count'),
            user_following_count=tweet_data.get('user_following_count'),
        )


# For testing
async def test_on_demand():
    """Test the on-demand scraper"""
    scraper = TwScrapeOnDemandScraper()
    
    # Test URL-based scraping
    print("Testing URL-based scraping...")
    entities = await scraper.on_demand_scrape(
        url="https://x.com/elonmusk/status/1234567890",
        limit=1
    )
    print(f"URL scrape: {len(entities)} entities")
    
    # Test username scraping
    print("\nTesting username scraping...")
    entities = await scraper.on_demand_scrape(
        usernames=["elonmusk"],
        limit=5
    )
    print(f"Username scrape: {len(entities)} entities")
    
    # Test keyword scraping
    print("\nTesting keyword scraping...")
    entities = await scraper.on_demand_scrape(
        keywords=["bitcoin"],
        limit=5
    )
    print(f"Keyword scrape: {len(entities)} entities")
    
    # Test combined scraping
    print("\nTesting combined scraping...")
    entities = await scraper.on_demand_scrape(
        usernames=["elonmusk"],
        keywords=["ai"],
        keyword_mode="all",
        limit=5
    )
    print(f"Combined scrape: {len(entities)} entities")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_on_demand())

#!/usr/bin/env python3
"""
Verify that aggressive_scrape.py will process ALL valid jobs from x.json
This script analyzes x.json and shows which jobs will be processed/skipped
ENHANCED: Now includes database statistics to show how much data exists for each job
"""

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

def get_db_connection(db_path: str = "/root/data-universe/storage/miner/SqliteMinerStorage.sqlite"):
    """Create a connection to the SQLite database"""
    try:
        connection = sqlite3.connect(db_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection
    except Exception as e:
        print(f"⚠️  Warning: Could not connect to database: {e}")
        return None


def query_all_label_stats(connection) -> Dict[str, Dict]:
    """
    Query database statistics for ALL labels at once (much faster than individual queries)
    
    Args:
        connection: Database connection
    
    Returns:
        Dictionary mapping label -> stats
    """
    if not connection:
        return {}
    
    try:
        cursor = connection.cursor()
        
        # Query all labels with their stats in a single query - much faster!
        # source = 2 is X/Twitter
        cursor.execute("""
            SELECT 
                label,
                COUNT(*) as tweet_count,
                SUM(contentSizeBytes) as total_size,
                MIN(datetime) as oldest_date,
                MAX(datetime) as newest_date
            FROM DataEntity
            WHERE source = 2 AND label IS NOT NULL AND label != 'NULL'
            GROUP BY label
        """)
        
        label_stats = {}
        for row in cursor:
            label = row['label']
            label_stats[label] = {
                'tweet_count': row['tweet_count'],
                'total_size_mb': (row['total_size'] or 0) / (1024 * 1024),
                'oldest_date': row['oldest_date'],
                'newest_date': row['newest_date']
            }
        
        return label_stats
    
    except Exception as e:
        print(f"Warning: Error querying all label stats: {e}")
        return {}


def get_job_stats_from_cache(label: Optional[str], keyword: Optional[str], label_stats_cache: Dict) -> Dict:
    """
    Get stats for a job from the pre-loaded cache
    
    Args:
        label: Job label (e.g., "#bitcoin")
        keyword: Job keyword (not used for DB query)
        label_stats_cache: Pre-loaded dictionary of all label stats
    
    Returns:
        Dictionary with stats
    """
    if not label:
        return {
            'tweet_count': 0,
            'total_size_mb': 0,
            'oldest_date': None,
            'newest_date': None
        }
    
    # Normalize label (ensure it has # prefix for matching)
    db_label = label if label.startswith('#') or label.startswith('$') else f"#{label}"
    
    # Look up in cache
    return label_stats_cache.get(db_label, {
        'tweet_count': 0,
        'total_size_mb': 0,
        'oldest_date': None,
        'newest_date': None
    })


def get_total_db_stats(connection) -> Dict:
    """Get overall database statistics"""
    if not connection:
        return {
            'total_tweets': 0,
            'total_size_mb': 0,
            'unique_labels': 0
        }
    
    try:
        cursor = connection.cursor()
        
        # Total tweets and size for X/Twitter (source = 2)
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tweets,
                SUM(contentSizeBytes) as total_size
            FROM DataEntity
            WHERE source = 2
        """)
        row = cursor.fetchone()
        
        total_tweets = row['total_tweets'] if row else 0
        total_size = (row['total_size'] or 0) / (1024 * 1024) if row else 0
        
        # Count unique labels
        cursor.execute("""
            SELECT COUNT(DISTINCT label) as unique_labels
            FROM DataEntity
            WHERE source = 2 AND label IS NOT NULL AND label != 'NULL'
        """)
        row = cursor.fetchone()
        unique_labels = row['unique_labels'] if row else 0
        
        return {
            'total_tweets': total_tweets,
            'total_size_mb': total_size,
            'unique_labels': unique_labels
        }
    
    except Exception as e:
        print(f"Warning: Error getting total DB stats: {e}")
        return {
            'total_tweets': 0,
            'total_size_mb': 0,
            'unique_labels': 0
        }


def analyze_job(item, index, label_stats_cache=None):
    """Analyze a single job and determine if it will be processed"""
    label = item.get('label')
    keyword = item.get('keyword')
    
    # This matches the validation logic in aggressive_scrape.py
    is_valid = bool(label or keyword)
    
    # Get database statistics for this job from cache
    db_stats = get_job_stats_from_cache(label, keyword, label_stats_cache) if label_stats_cache else {
        'tweet_count': 0,
        'total_size_mb': 0,
        'oldest_date': None,
        'newest_date': None
    }
    
    return {
        'index': index,
        'label': label,
        'keyword': keyword,
        'is_valid': is_valid,
        'reason': 'VALID - will be processed' if is_valid else 'INVALID - both label and keyword are null',
        'has_label': bool(label),
        'has_keyword': bool(keyword),
        'strategy': item.get('strategy', 'hashtag'),
        'weight': item.get('weight', 1.0),
        'is_new': item.get('is_new', False),
        'enable_network_expansion': item.get('enable_network_expansion', False),
        'db_tweet_count': db_stats['tweet_count'],
        'db_size_mb': db_stats['total_size_mb'],
        'db_oldest_date': db_stats['oldest_date'],
        'db_newest_date': db_stats['newest_date'],
    }

def main():
    print("=" * 80)
    print("X.JSON JOB COVERAGE & DATABASE STATISTICS VERIFICATION")
    print("=" * 80)
    
    # Check if x.json exists
    if not Path('x.json').exists():
        print("\n❌ ERROR: x.json not found!")
        print("Please ensure x.json exists in the current directory")
        return
    
    # Load x.json
    try:
        with open('x.json', 'r') as f:
            jobs_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"\n❌ ERROR: Invalid JSON in x.json: {e}")
        return
    except Exception as e:
        print(f"\n❌ ERROR: Failed to read x.json: {e}")
        return
    
    print(f"\nTotal jobs in x.json: {len(jobs_data)}")
    
    # Try to connect to database
    db_connection = get_db_connection()
    if db_connection:
        print("✅ Connected to database: /root/data-universe/storage/miner/SqliteMinerStorage.sqlite")
    else:
        print("⚠️  Database connection failed - showing job validation only (no data statistics)")
    
    print("-" * 80)
    
    # Get overall database stats
    label_stats_cache = {}
    if db_connection:
        total_db_stats = get_total_db_stats(db_connection)
        print(f"\n📊 OVERALL DATABASE STATISTICS")
        print("-" * 80)
        print(f"Total X/Twitter tweets in DB:  {total_db_stats['total_tweets']:,}")
        print(f"Total data size:                {total_db_stats['total_size_mb']:.2f} MB")
        print(f"Unique labels in DB:            {total_db_stats['unique_labels']:,}")
        print("-" * 80)
        
        # Load ALL label stats into cache (single query - much faster!)
        print("\n⏳ Loading label statistics from database...")
        label_stats_cache = query_all_label_stats(db_connection)
        print(f"✅ Loaded stats for {len(label_stats_cache)} labels")
        print("-" * 80)
    
    # Analyze each job
    valid_jobs = []
    invalid_jobs = []
    
    print("\n⏳ Analyzing jobs...")
    for i, job_item in enumerate(jobs_data, 1):
        analysis = analyze_job(job_item, i, label_stats_cache)
        
        # Show progress for large job lists
        if i % 1000 == 0:
            print(f"   Processed {i}/{len(jobs_data)} jobs...")
        
        if analysis['is_valid']:
            valid_jobs.append(analysis)
        else:
            invalid_jobs.append(analysis)
    
    # Show valid jobs with database statistics
    print(f"\n✅ VALID JOBS (will be processed): {len(valid_jobs)}")
    print("-" * 80)
    if db_connection:
        print(f"{'#':>3} | {'Label':30s} | {'Keyword':20s} | {'Tweets':>10s} | {'Size (MB)':>10s} | {'Strategy':15s}")
        print("-" * 110)
    else:
        print(f"{'#':>3} | {'Label':30s} | {'Keyword':20s} | {'Strategy':15s}")
        print("-" * 80)
    
    for job in valid_jobs:
        label_str = job['label'] if job['has_label'] else "None"
        keyword_str = job['keyword'] if job['has_keyword'] else "None"
        strategy_str = job['strategy']
        
        if db_connection:
            tweets = f"{job['db_tweet_count']:,}" if job['db_tweet_count'] > 0 else "0"
            size = f"{job['db_size_mb']:.2f}" if job['db_size_mb'] > 0 else "0.00"
            print(f"{job['index']:3d} | {label_str:30s} | {keyword_str:20s} | {tweets:>10s} | {size:>10s} | {strategy_str:15s}")
        else:
            print(f"{job['index']:3d} | {label_str:30s} | {keyword_str:20s} | {strategy_str:15s}")
    
    # Show invalid jobs (if any)
    if invalid_jobs:
        print(f"\n❌ INVALID JOBS (will be skipped): {len(invalid_jobs)}")
        print("-" * 80)
        for job in invalid_jobs:
            print(f"  {job['index']:3d}. SKIPPED - {job['reason']}")
    else:
        print(f"\n✅ NO INVALID JOBS - All jobs will be processed!")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total jobs in x.json:     {len(jobs_data)}")
    print(f"Valid jobs (processing):  {len(valid_jobs)}")
    print(f"Invalid jobs (skipping):  {len(invalid_jobs)}")
    print(f"Coverage rate:            {len(valid_jobs)/len(jobs_data)*100:.1f}%")
    
    # Breakdown by type
    print("\n" + "-" * 80)
    print("BREAKDOWN BY TYPE")
    print("-" * 80)
    label_only = sum(1 for j in valid_jobs if j['has_label'] and not j['has_keyword'])
    keyword_only = sum(1 for j in valid_jobs if j['has_keyword'] and not j['has_label'])
    both = sum(1 for j in valid_jobs if j['has_label'] and j['has_keyword'])
    
    print(f"Jobs with label only:     {label_only}")
    print(f"Jobs with keyword only:   {keyword_only}")
    print(f"Jobs with both:           {both}")
    
    # Breakdown by strategy
    print("\n" + "-" * 80)
    print("BREAKDOWN BY STRATEGY")
    print("-" * 80)
    strategies = {}
    for job in valid_jobs:
        strategy = job['strategy']
        strategies[strategy] = strategies.get(strategy, 0) + 1
    
    for strategy, count in sorted(strategies.items()):
        print(f"{strategy:20s}: {count}")
    
    # Network expansion jobs
    network_jobs = sum(1 for j in valid_jobs if j['enable_network_expansion'])
    if network_jobs > 0:
        print("\n" + "-" * 80)
        print(f"Jobs with network expansion: {network_jobs}")
    
    # New jobs from gravity
    new_jobs = sum(1 for j in valid_jobs if j['is_new'])
    if new_jobs > 0:
        print(f"New jobs from gravity:       {new_jobs} (will be prioritized)")
    
    # Database coverage statistics
    if db_connection:
        print("\n" + "-" * 80)
        print("DATABASE COVERAGE BY JOB")
        print("-" * 80)
        
        jobs_with_data = [j for j in valid_jobs if j['db_tweet_count'] > 0]
        jobs_without_data = [j for j in valid_jobs if j['db_tweet_count'] == 0]
        
        print(f"Jobs with data in DB:        {len(jobs_with_data)}")
        print(f"Jobs without data in DB:     {len(jobs_without_data)}")
        print(f"Data coverage:               {len(jobs_with_data)/len(valid_jobs)*100:.1f}%")
        
        if jobs_with_data:
            total_tweets_for_jobs = sum(j['db_tweet_count'] for j in jobs_with_data)
            total_size_for_jobs = sum(j['db_size_mb'] for j in jobs_with_data)
            
            print(f"\nTotal tweets for x.json jobs: {total_tweets_for_jobs:,}")
            print(f"Total size for x.json jobs:   {total_size_for_jobs:.2f} MB")
            
            # Top 10 jobs by tweet count
            print("\n📈 TOP 10 JOBS BY TWEET COUNT:")
            print("-" * 80)
            top_jobs = sorted(jobs_with_data, key=lambda x: x['db_tweet_count'], reverse=True)[:10]
            for i, job in enumerate(top_jobs, 1):
                date_range = ""
                if job['db_oldest_date'] and job['db_newest_date']:
                    date_range = f" ({job['db_oldest_date'][:10]} to {job['db_newest_date'][:10]})"
                print(f"  {i:2d}. {job['label']:25s} - {job['db_tweet_count']:>8,} tweets, {job['db_size_mb']:>8.2f} MB{date_range}")
            
            # Jobs without data
            if jobs_without_data:
                print(f"\n⚠️  JOBS WITHOUT DATA ({len(jobs_without_data)}):")
                print("-" * 80)
                for job in jobs_without_data[:20]:  # Show first 20
                    print(f"  {job['index']:3d}. {job['label']}")
                if len(jobs_without_data) > 20:
                    print(f"  ... and {len(jobs_without_data) - 20} more")
    
    print("=" * 80)
    
    # Final verdict
    if len(valid_jobs) == len(jobs_data):
        print("\n✅ ALL JOBS WILL BE PROCESSED - 100% COVERAGE!")
    else:
        print(f"\n⚠️  {len(invalid_jobs)} job(s) will be skipped (null label AND null keyword)")
    
    print("\nValidation Rules:")
    print("  ✅ Job is VALID if it has:")
    print("     - A label (e.g., #bitcoin, #crypto, etc.)")
    print("     - OR a keyword (e.g., 'mining', 'trading', etc.)")
    print("     - OR both label and keyword")
    print("  ❌ Job is INVALID if:")
    print("     - BOTH label AND keyword are null/None")
    print("\n" + "=" * 80)
    
    # Close database connection
    if db_connection:
        db_connection.close()

if __name__ == "__main__":
    main()

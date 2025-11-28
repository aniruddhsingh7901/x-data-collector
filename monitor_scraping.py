#!/usr/bin/env python3
"""
Real-time Monitoring for Aggressive Scraping
Shows account status, request rates, and performance metrics
"""

import asyncio
import sys
from datetime import datetime
from twscrape import AccountsPool
from twscrape.logger import set_log_level

async def display_stats(pool: AccountsPool):
    """Display comprehensive statistics"""
    
    # Get account stats
    accounts_info = await pool.accounts_info()
    pool_stats = await pool.stats()
    aggressive_stats = await pool.get_aggressive_stats()
    
    # Clear screen
    print("\033[2J\033[H")  # ANSI escape codes
    
    print("="*80)
    print("AGGRESSIVE SCRAPING MONITOR".center(80))
    print("="*80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # Overall stats
    print(f"\n📊 OVERALL STATISTICS")
    print(f"   Total Accounts: {pool_stats.get('total', 0)}")
    print(f"   Active Accounts: {pool_stats.get('active', 0)}")
    print(f"   Inactive Accounts: {pool_stats.get('inactive', 0)}")
    print(f"   Accounts in Cooldown: {aggressive_stats.get('accounts_in_cooldown', 0)}")
    
    # Rate limiting stats
    print(f"\n⚡ RATE LIMITING")
    print(f"   Requests (last 15 min): {aggressive_stats.get('total_requests_15min', 0)}")
    print(f"   Estimated Capacity: {aggressive_stats.get('estimated_capacity_per_hour', 0):,} req/hour")
    print(f"   Daily Projection: {aggressive_stats.get('estimated_capacity_per_hour', 0) * 24:,} requests")
    
    # Calculate tweet projection (assuming 20 tweets per request)
    tweets_per_day = aggressive_stats.get('estimated_capacity_per_hour', 0) * 24 * 20
    print(f"   Tweet Projection: {tweets_per_day:,} tweets/day")
    
    # Locked queues
    locked_queues = {k: v for k, v in pool_stats.items() if k.startswith('locked_') and v > 0}
    if locked_queues:
        print(f"\n🔒 LOCKED QUEUES")
        for queue, count in sorted(locked_queues.items(), key=lambda x: x[1], reverse=True):
            queue_name = queue.replace('locked_', '')
            print(f"   {queue_name}: {count} accounts")
    
    # Account details (top 10 most active)
    print(f"\n👥 ACCOUNT STATUS (Top 10)")
    print(f"   {'Username':<20} {'Active':<8} {'Requests':<10} {'Last Used':<20}")
    print(f"   {'-'*20} {'-'*8} {'-'*10} {'-'*20}")
    
    active_accounts = [acc for acc in accounts_info if acc['active']][:10]
    for acc in active_accounts:
        last_used = acc['last_used'].strftime('%Y-%m-%d %H:%M:%S') if acc['last_used'] else 'Never'
        print(f"   {acc['username']:<20} {'✓' if acc['active'] else '✗':<8} {acc['total_req']:<10} {last_used:<20}")
    
    # Per-account request breakdown
    if aggressive_stats.get('requests_per_account'):
        print(f"\n📈 REQUEST BREAKDOWN (Last 15 min)")
        for username, queues in list(aggressive_stats['requests_per_account'].items())[:5]:
            total = sum(queues.values())
            print(f"   {username}: {total} requests")
            for queue, count in queues.items():
                print(f"      - {queue}: {count}")
    
    # Warnings
    warnings = []
    if pool_stats.get('active', 0) == 0:
        warnings.append("⚠️  No active accounts!")
    if aggressive_stats.get('accounts_in_cooldown', 0) == pool_stats.get('active', 0):
        warnings.append("⚠️  All accounts in cooldown!")
    if aggressive_stats.get('total_requests_15min', 0) == 0:
        warnings.append("⚠️  No requests in last 15 minutes")
    
    if warnings:
        print(f"\n⚠️  WARNINGS")
        for warning in warnings:
            print(f"   {warning}")
    
    print("\n" + "="*80)
    print("Press Ctrl+C to exit")
    print("="*80)

async def monitor_loop(refresh_interval: int = 5):
    """Main monitoring loop"""
    pool = AccountsPool("accounts.db")
    
    try:
        while True:
            await display_stats(pool)
            await asyncio.sleep(refresh_interval)
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")

async def main():
    refresh_interval = 5  # seconds
    
    if len(sys.argv) > 1:
        try:
            refresh_interval = int(sys.argv[1])
        except ValueError:
            print("Invalid refresh interval. Using default: 5 seconds")
    
    print(f"Starting monitor (refresh every {refresh_interval} seconds)...")
    await monitor_loop(refresh_interval)

if __name__ == "__main__":
    set_log_level("ERROR")  # Suppress logs in monitor
    asyncio.run(main())

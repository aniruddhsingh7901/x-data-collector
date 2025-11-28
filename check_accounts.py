#!/usr/bin/env python3
"""Check loaded accounts"""
import asyncio
from twscrape import AccountsPool

async def main():
    pool = AccountsPool("accounts.db")
    
    # Get all accounts
    accounts = await pool.get_all()
    
    print(f"\n{'='*60}")
    print(f"LOADED ACCOUNTS: {len(accounts)}")
    print(f"{'='*60}\n")
    
    # Count active/inactive
    active = sum(1 for acc in accounts if acc.active)
    inactive = len(accounts) - active
    
    print(f"Active: {active}")
    print(f"Inactive: {inactive}\n")
    
    # Show first 10 accounts
    print(f"{'Username':<20} {'Active':<8} {'Proxy':<30}")
    print(f"{'-'*20} {'-'*8} {'-'*30}")
    
    for acc in accounts[:10]:
        proxy_display = acc.proxy[:30] + "..." if acc.proxy and len(acc.proxy) > 30 else acc.proxy or "None"
        print(f"{acc.username:<20} {'✓' if acc.active else '✗':<8} {proxy_display:<30}")
    
    if len(accounts) > 10:
        print(f"... and {len(accounts) - 10} more accounts\n")
    
    print(f"\n{'='*60}")
    print(f"Ready to start scraping!")
    print(f"Run: python aggressive_scrape.py")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    asyncio.run(main())

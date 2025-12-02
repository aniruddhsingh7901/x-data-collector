#!/usr/bin/env python3
"""
Job Monitor Service
Monitors gravity/total.json for new jobs and updates x.json with prioritization
"""

import asyncio
import json
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class JobMonitor:
    """Monitors gravity/total.json and updates x.json with new jobs"""
    
    def __init__(self, gravity_file: str = "gravity/total.json", 
                 output_file: str = "x.json"):
        self.gravity_file = Path(gravity_file)
        self.output_file = Path(output_file)
        self.known_jobs: Set[str] = set()
        self.load_existing_jobs()
    
    def generate_job_hash(self, job: Dict) -> str:
        """Generate unique hash for a job based on its key parameters"""
        params = job.get('params', {})
        key_parts = [
            params.get('platform', ''),
            params.get('label', ''),
            params.get('keyword', ''),
            params.get('post_start_datetime', ''),
            params.get('post_end_datetime', '')
        ]
        key = '|'.join(str(p) for p in key_parts)
        return hashlib.md5(key.encode()).hexdigest()
    
    def load_existing_jobs(self):
        """Load existing jobs from x.json to track what we already have"""
        try:
            if self.output_file.exists():
                with open(self.output_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        logger.warning(f"{self.output_file} is empty, initializing with empty array")
                        existing_jobs = []
                    else:
                        existing_jobs = json.loads(content)
                    
                    for job in existing_jobs:
                        job_hash = self.generate_job_hash({'params': job})
                        self.known_jobs.add(job_hash)
                logger.info(f"Loaded {len(self.known_jobs)} existing jobs from {self.output_file}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {self.output_file}: {e}")
            logger.info(f"Reinitializing {self.output_file} with empty array")
            with open(self.output_file, 'w') as f:
                json.dump([], f)
            self.known_jobs = set()
        except Exception as e:
            logger.warning(f"Could not load existing jobs: {e}")
            self.known_jobs = set()
    
    def convert_gravity_to_x_format(self, gravity_job: Dict) -> Dict:
        """Copy gravity/total.json jobs exactly as they are for X platform"""
        params = gravity_job.get('params', {})
        
        # Only process X/Twitter jobs
        if params.get('platform') != 'x':
            return None
        
        # Return the job exactly as it is in total.json
        return gravity_job
    
    def detect_new_jobs(self) -> List[Dict]:
        """Detect new jobs in gravity/total.json that aren't in x.json"""
        if not self.gravity_file.exists():
            logger.warning(f"{self.gravity_file} not found")
            return []
        
        try:
            with open(self.gravity_file, 'r') as f:
                gravity_jobs = json.load(f)
            
            new_jobs = []
            for gravity_job in gravity_jobs:
                job_hash = self.generate_job_hash(gravity_job)
                
                # Check if this is a new job
                if job_hash not in self.known_jobs:
                    # Convert to x.json format
                    x_job = self.convert_gravity_to_x_format(gravity_job)
                    if x_job:  # Only if it's an X/Twitter job
                        new_jobs.append(x_job)
                        self.known_jobs.add(job_hash)
                        params = x_job.get('params', {})
                        logger.info(f"New job detected: {params.get('label')} (keyword: {params.get('keyword')})")
            
            return new_jobs
        
        except Exception as e:
            logger.error(f"Error detecting new jobs: {e}")
            return []
    
    def update_x_json(self, new_jobs: List[Dict]):
        """Add new jobs to x.json with high priority"""
        if not new_jobs:
            return
        
        try:
            # Load existing jobs
            existing_jobs = []
            if self.output_file.exists():
                with open(self.output_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        existing_jobs = json.loads(content)
                    else:
                        existing_jobs = []
            
            # Mark existing jobs as not new
            for job in existing_jobs:
                job['is_new'] = False
            
            # Prepend new jobs (they'll be processed first)
            # Sort new jobs by weight (descending) for additional prioritization
            new_jobs_sorted = sorted(new_jobs, key=lambda x: x.get('gravity_weight', 1.0), reverse=True)
            updated_jobs = new_jobs_sorted + existing_jobs
            
            # Write back to file
            with open(self.output_file, 'w') as f:
                json.dump(updated_jobs, f, indent=2)
            
            logger.info(f"✓ Added {len(new_jobs)} new jobs to {self.output_file} (total: {len(updated_jobs)})")
            
            # Log the new jobs
            for job in new_jobs_sorted:
                params = job.get('params', {})
                logger.info(f"  → {params.get('label')} (weight: {job.get('weight', 1.0)}, keyword: {params.get('keyword')})")
        
        except Exception as e:
            logger.error(f"Error updating x.json: {e}")
    
    def run_check(self):
        """Perform a single check for new jobs"""
        logger.info("Checking for new jobs...")
        new_jobs = self.detect_new_jobs()
        if new_jobs:
            self.update_x_json(new_jobs)
        else:
            logger.info("No new jobs detected")
    
    def start_monitoring(self, check_interval: int = 60):
        """Start continuous monitoring with periodic checks"""
        logger.info("="*80)
        logger.info("JOB MONITOR STARTED")
        logger.info(f"Monitoring: {self.gravity_file}")
        logger.info(f"Output: {self.output_file}")
        logger.info(f"Check interval: {check_interval} seconds")
        logger.info("="*80)
        
        # Initial check
        self.run_check()
        
        # Continuous monitoring
        while True:
            try:
                time.sleep(check_interval)
                self.run_check()
            except KeyboardInterrupt:
                logger.info("\nMonitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(check_interval)


class GravityFileHandler(FileSystemEventHandler):
    """Handle file system events for gravity/total.json"""
    
    def __init__(self, monitor: JobMonitor):
        self.monitor = monitor
        self.last_check = 0
        self.debounce_seconds = 5  # Avoid multiple rapid checks
    
    def on_modified(self, event):
        if event.src_path.endswith('total.json'):
            current_time = time.time()
            if current_time - self.last_check > self.debounce_seconds:
                logger.info(f"Detected change in {event.src_path}")
                self.monitor.run_check()
                self.last_check = current_time


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Monitor gravity/total.json for new jobs')
    parser.add_argument('--gravity-file', default='gravity/total.json',
                       help='Path to gravity/total.json')
    parser.add_argument('--output-file', default='x.json',
                       help='Path to output x.json')
    parser.add_argument('--check-interval', type=int, default=60,
                       help='Check interval in seconds (default: 60)')
    parser.add_argument('--once', action='store_true',
                       help='Run once and exit (no continuous monitoring)')
    parser.add_argument('--use-watchdog', action='store_true',
                       help='Use file system events instead of polling')
    
    args = parser.parse_args()
    
    # Create monitor
    monitor = JobMonitor(args.gravity_file, args.output_file)
    
    if args.once:
        # Single check mode
        monitor.run_check()
    elif args.use_watchdog:
        # File system event monitoring
        logger.info("Using file system event monitoring (watchdog)")
        event_handler = GravityFileHandler(monitor)
        observer = Observer()
        observer.schedule(event_handler, path=str(Path(args.gravity_file).parent), recursive=False)
        observer.start()
        
        try:
            # Also do periodic checks as backup
            monitor.start_monitoring(args.check_interval)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
    else:
        # Polling mode (default)
        monitor.start_monitoring(args.check_interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nStopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

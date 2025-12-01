module.exports = {
  apps: [
    {
      name: 'job-monitor',
      script: 'job_monitor.py',
      interpreter: 'python3',
      args: '--check-interval 60',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        PYTHONUNBUFFERED: '1'
      },
      error_file: 'logs/job-monitor-error.log',
      out_file: 'logs/job-monitor-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      merge_logs: true,
      kill_timeout: 5000
    },
    {
      name: 'x-scraper',
      script: 'aggressive_scrape.py',
      interpreter: 'python3',
      autorestart: true,
      watch: ['x.json'],  // Restart when x.json changes
      ignore_watch: ['node_modules', 'logs', '*.db'],
      max_memory_restart: '2G',
      env: {
        PYTHONUNBUFFERED: '1'
      },
      error_file: 'logs/x-scraper-error.log',
      out_file: 'logs/x-scraper-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      merge_logs: true,
      kill_timeout: 30000,  // Give scraper time to save state
      restart_delay: 5000   // Wait 5s before restarting
    }
  ]
};

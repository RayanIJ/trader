"""
Market-aware scheduler for running trading cycles.
"""
import time
import logging
import signal
from typing import Callable, Optional
from datetime import datetime

from src.config.market_calendar import is_market_open, next_market_open, get_market_status
from src.config.settings import settings

logger = logging.getLogger(__name__)

class MarketScheduler:
    """
    Runs a trading function periodically when the market is open.
    Handles waiting for market open and graceful shutdown.
    """
    def __init__(self, trading_job: Callable):
        self.trading_job = trading_job
        self.running = False
        
        # Handle shutdown signals
        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

    def _shutdown_handler(self, signum, frame):
        """Handle interrupt signals."""
        logger.info(f"Signal {signum} received. Shutting down scheduler...")
        self.running = False

    def run(self):
        """Start the scheduler loop."""
        self.running = True
        logger.info("Market Scheduler started.")
        
        while self.running:
            try:
                # 1. Check market status
                if not is_market_open():
                    next_open = next_market_open()
                    wait_seconds = (next_open - datetime.now(next_open.tzinfo)).total_seconds()
                    
                    status = get_market_status()
                    logger.info(f"Market is CLOSED. Next open: {status['next_open']}")
                    logger.info(f"Sleeping for {int(wait_seconds)} seconds...")
                    
                    # Sleep in chunks to allow interruption
                    self._sleep_interruptible(wait_seconds)
                    continue

                # 2. Market is OPEN - Run Trading Cycle
                logger.info("Market is OPEN. Starting trading cycle...")
                self.trading_job()
                
                # 3. Wait for next cycle
                logger.info(f"Cycle complete. Waiting {settings.trading_interval_seconds}s...")
                self._sleep_interruptible(settings.trading_interval_seconds)

            except Exception as e:
                logger.error(f"Scheduler error: {str(e)}", exc_info=True)
                # Sleep briefly on error to avoid busy loop
                time.sleep(60)

        logger.info("Scheduler stopped.")

    def _sleep_interruptible(self, seconds: float):
        """Sleep for `seconds` but check `self.running` frequently."""
        chunk_size = 1.0
        slept = 0.0
        while slept < seconds and self.running:
            time.sleep(min(chunk_size, seconds - slept))
            slept += chunk_size

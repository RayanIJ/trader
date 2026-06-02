"""
Sentiment cache for SOXL/SOXS trading.
Caches market sentiment to reduce API token usage.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class SentimentCache:
    """Caches semiconductor sentiment to avoid repeated web searches."""
    
    def __init__(self, cache_file: str = "sentiment_cache.json", refresh_minutes: int = 30):
        self.cache_file = Path(cache_file)
        self.refresh_minutes = refresh_minutes
        self._cache: Dict = self._load_cache()
    
    def _load_cache(self) -> Dict:
        """Load cache from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load sentiment cache: {e}")
        return {}
    
    def _save_cache(self):
        """Save cache to disk."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save sentiment cache: {e}")
    
    def is_stale(self) -> bool:
        """Check if cache needs refresh."""
        if not self._cache or 'timestamp' not in self._cache:
            return True
        
        cached_time = datetime.fromisoformat(self._cache['timestamp'])
        age_minutes = (datetime.now() - cached_time).total_seconds() / 60
        
        is_stale = age_minutes > self.refresh_minutes
        if is_stale:
            logger.info(f"Sentiment cache is stale ({age_minutes:.1f} min old, max {self.refresh_minutes} min)")
        else:
            logger.info(f"Using cached sentiment ({age_minutes:.1f} min old)")
        
        return is_stale
    
    def get_sentiment(self) -> Optional[str]:
        """Get cached sentiment if not stale."""
        if self.is_stale():
            return None
        return self._cache.get('sentiment')
    
    def get_direction(self) -> Optional[str]:
        """Get cached direction (BULLISH/BEARISH/NEUTRAL)."""
        if self.is_stale():
            return None
        return self._cache.get('direction')
    
    def update(self, sentiment: str, direction: str):
        """Update cache with new sentiment."""
        self._cache = {
            'timestamp': datetime.now().isoformat(),
            'sentiment': sentiment,
            'direction': direction
        }
        self._save_cache()
        logger.info(f"Sentiment cache updated: {direction}")
    
    def get_cache_info(self) -> str:
        """Get human-readable cache status."""
        if not self._cache or 'timestamp' not in self._cache:
            return "No cached sentiment"
        
        cached_time = datetime.fromisoformat(self._cache['timestamp'])
        age_minutes = (datetime.now() - cached_time).total_seconds() / 60
        direction = self._cache.get('direction', 'UNKNOWN')
        
        return f"{direction} (cached {age_minutes:.0f}m ago, refreshes every {self.refresh_minutes}m)"

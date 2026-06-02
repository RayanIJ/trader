import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class CycleLogger:
    """Logs details of each trading cycle to a JSON history file."""
    
    def __init__(self, log_dir: str = "trades"):
        self.log_dir = log_dir
        self.history_file = os.path.join(log_dir, "execution_history.json")
        self._ensure_log_dir()

    def _ensure_log_dir(self):
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
            
    def log_cycle(self, 
                  cycle_id: str, 
                  portfolio_snapshot: Dict[str, Any], 
                  ai_context: Dict[str, str], 
                  recommendation: Dict[str, Any], 
                  actions_taken: List[str]):
        """
        Append a new cycle record to the history file.
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "cycle_id": cycle_id,
            "portfolio": portfolio_snapshot,
            "ai_context": ai_context, # Contains 'user_prompt', 'system_prompt', 'response_raw'
            "recommendation": recommendation,
            "actions_taken": actions_taken
        }
        
        history = self.load_history()
        history.append(record)
        
        # Keep only last 100 cycles to avoid infinite growth for now
        if len(history) > 100:
            history = history[-100:]
            
        try:
            with open(self.history_file, 'w') as f:
                json.dump(history, f, indent=2, default=str)
            logger.info(f"Cycle {cycle_id} logged successfully.")
        except Exception as e:
            logger.error(f"Failed to log cycle history: {e}")

    def load_history(self) -> List[Dict[str, Any]]:
        """Load the full history."""
        if not os.path.exists(self.history_file):
            return []
        
        try:
            with open(self.history_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
            return []

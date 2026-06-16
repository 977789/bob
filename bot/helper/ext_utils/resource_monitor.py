"""
Global resource monitoring and management utilities.
Provides system-wide CPU and memory optimization functions.
"""

import asyncio
import gc
import os
import time
from typing import Dict, Optional, Tuple

from bot import LOGGER

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    LOGGER.warning("psutil not available, resource monitoring will be limited")


class ResourceMonitor:
    """Global resource monitoring and management class."""

    def __init__(self):
        self._last_cleanup = 0
        self._cleanup_interval = 300  # 5 minutes
        self._memory_threshold_mb = 400  # Alert threshold
        self._critical_memory_mb = 200  # Critical threshold

    def get_memory_info(self) -> Dict[str, float]:
        """Get current memory usage information."""
        if not PSUTIL_AVAILABLE:
            return {"available_mb": 0, "used_mb": 0, "percent": 0}

        try:
            memory = psutil.virtual_memory()
            process = psutil.Process()
            process_memory = process.memory_info()

            return {
                "available_mb": memory.available / (1024 * 1024),
                "used_mb": process_memory.rss / (1024 * 1024),
                "percent": memory.percent,
                "total_mb": memory.total / (1024 * 1024),
            }
        except Exception as e:
            LOGGER.debug(f"Error getting memory info: {e}")
            return {"available_mb": 0, "used_mb": 0, "percent": 0}

    def get_cpu_info(self) -> Dict[str, float]:
        """Get current CPU usage information."""
        if not PSUTIL_AVAILABLE:
            return {"percent": 0, "count": 1}

        try:
            return {
                "percent": psutil.cpu_percent(interval=0.1),
                "count": psutil.cpu_count(),
                "load_avg": os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0),
            }
        except Exception as e:
            LOGGER.debug(f"Error getting CPU info: {e}")
            return {"percent": 0, "count": 1}

    def is_memory_critical(self) -> bool:
        """Check if memory usage is at critical levels."""
        memory_info = self.get_memory_info()
        return memory_info["available_mb"] < self._critical_memory_mb

    def is_memory_high(self) -> bool:
        """Check if memory usage is high."""
        memory_info = self.get_memory_info()
        return memory_info["available_mb"] < self._memory_threshold_mb

    def is_cpu_high(self) -> bool:
        """Check if CPU usage is high."""
        cpu_info = self.get_cpu_info()
        return cpu_info["percent"] > 80  # 80% threshold

    def force_cleanup(self, aggressive: bool = False):
        """Force garbage collection and cleanup."""
        try:
            # Standard cleanup
            gc.collect()

            if aggressive:
                # More aggressive cleanup
                gc.collect()
                gc.collect()
                time.sleep(0.1)  # Brief pause for cleanup to take effect

            self._last_cleanup = time.time()
            LOGGER.debug(
                f"Resource cleanup performed ({'aggressive' if aggressive else 'standard'})"
            )

        except Exception as e:
            LOGGER.debug(f"Error during cleanup: {e}")

    def should_cleanup(self) -> bool:
        """Check if it's time for periodic cleanup."""
        return (time.time() - self._last_cleanup) > self._cleanup_interval

    def periodic_cleanup_if_needed(self):
        """Perform cleanup if it's been long enough."""
        if self.should_cleanup():
            self.force_cleanup()

    def get_resource_status(self) -> Dict[str, any]:
        """Get comprehensive resource status."""
        memory_info = self.get_memory_info()
        cpu_info = self.get_cpu_info()

        return {
            "memory": memory_info,
            "cpu": cpu_info,
            "memory_critical": self.is_memory_critical(),
            "memory_high": self.is_memory_high(),
            "cpu_high": self.is_cpu_high(),
            "should_cleanup": self.should_cleanup(),
        }

    def log_resource_status(self, context: str = ""):
        """Log current resource status."""
        status = self.get_resource_status()
        memory = status["memory"]
        cpu = status["cpu"]

        context_str = f" ({context})" if context else ""
        LOGGER.info(
            f"Resource Status{context_str}: "
            f"Memory: {memory['used_mb']:.1f}MB used, {memory['available_mb']:.1f}MB available "
            f"({memory['percent']:.1f}%), CPU: {cpu['percent']:.1f}%"
        )

        if status["memory_critical"]:
            LOGGER.warning("CRITICAL: Memory usage is critically low!")
        elif status["memory_high"]:
            LOGGER.warning("WARNING: Memory usage is high")

        if status["cpu_high"]:
            LOGGER.warning("WARNING: CPU usage is high")

    async def wait_for_resources(self, max_wait: int = 30) -> bool:
        """Wait for resources to become available."""
        start_time = time.time()

        while (time.time() - start_time) < max_wait:
            if not (self.is_memory_critical() or self.is_cpu_high()):
                return True

            LOGGER.info("Waiting for resources to become available...")
            self.force_cleanup(aggressive=True)
            await asyncio.sleep(2)

        LOGGER.warning(f"Resource wait timeout after {max_wait}s")
        return False

    def set_process_priority(self, pid: Optional[int] = None):
        """Set process priority to reduce system impact."""
        if not PSUTIL_AVAILABLE:
            return False

        try:
            if pid:
                process = psutil.Process(pid)
            else:
                process = psutil.Process()

            # Set lower priority
            process.nice(10)

            # Set CPU affinity to first core if possible
            try:
                cpu_count = psutil.cpu_count()
                if cpu_count > 1:
                    process.cpu_affinity([0])
            except (psutil.AccessDenied, AttributeError):
                pass

            return True

        except Exception as e:
            LOGGER.debug(f"Error setting process priority: {e}")
            return False


# Global resource monitor instance
resource_monitor = ResourceMonitor()


def get_optimal_thread_count() -> int:
    """Get optimal thread count based on current system resources."""
    if not PSUTIL_AVAILABLE:
        return 1

    try:
        cpu_count = psutil.cpu_count()
        memory_info = resource_monitor.get_memory_info()

        # Conservative thread count based on available resources
        if memory_info["available_mb"] < 200:  # Very low memory
            return 1
        elif memory_info["available_mb"] < 400:  # Low memory
            return min(2, cpu_count // 4 or 1)
        else:  # Normal memory
            return min(4, cpu_count // 2 or 1)

    except Exception:
        return 1


def should_skip_resource_intensive_task(task_name: str = "") -> bool:
    """Determine if resource-intensive tasks should be skipped."""
    status = resource_monitor.get_resource_status()

    if status["memory_critical"]:
        LOGGER.warning(
            f"Skipping resource-intensive task '{task_name}' due to critical memory"
        )
        return True

    if status["cpu_high"] and status["memory_high"]:
        LOGGER.warning(
            f"Skipping resource-intensive task '{task_name}' due to high resource usage"
        )
        return True

    return False

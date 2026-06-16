# HyperDL Status Checker Module

from ... import LOGGER
from .hyperdl_utils import HyperTGDownload


def check_hyperdl_status():
    """Check and log HyperDL availability status"""
    try:
        if HyperTGDownload.is_available():
            status_info = HyperTGDownload.get_status_info()
            LOGGER.info(f"✅ HyperDL Status: {status_info['reason']}")
            LOGGER.info(f"   Helper Bots: {status_info['helper_count']}")
            LOGGER.info(f"   Max Parts: {status_info['config_threads'] or 'Auto'}")
            LOGGER.info("   HyperDL is ready for high-speed downloads!")
            return True
        else:
            status_info = HyperTGDownload.get_status_info()
            LOGGER.warning(f"❌ HyperDL Status: {status_info['reason']}")
            LOGGER.warning("   HyperDL will be disabled for this session")
            LOGGER.info("")
            LOGGER.info("📋 To enable HyperDL (High-Speed Downloads):")
            for req in get_hyperdl_requirements():
                LOGGER.info(f"   • {req}")
            LOGGER.info("")
            return False
    except Exception as e:
        LOGGER.error(f"❌ Error checking HyperDL status: {e}")
        return False


def log_hyperdl_requirements():
    """Log HyperDL setup requirements"""
    LOGGER.info("HyperDL Requirements:")
    LOGGER.info("  • HELPER_TOKENS: Bot tokens for parallel downloads")
    LOGGER.info("  • HYPER_THREADS: Max concurrent parts (optional)")
    LOGGER.info("  • HYPER_SESSION_TIMEOUT: Session timeout in seconds (optional)")
    LOGGER.info("  • Multiple bot tokens increase download speed")


def should_use_hyperdl(user_requested=True):
    """
    Determine if HyperDL should be used based on availability and user preference

    Args:
        user_requested (bool): Whether the user specifically requested HyperDL

    Returns:
        tuple: (should_use, reason)
    """
    if not user_requested:
        return False, "Not requested by user"

    try:
        if not HyperTGDownload.is_available():
            status_info = HyperTGDownload.get_status_info()
            return False, f"HyperDL unavailable: {status_info['reason']}"

        status_info = HyperTGDownload.get_status_info()
        return True, f"Ready: {status_info['reason']}"
    except Exception as e:
        return False, f"Error checking HyperDL: {e}"


def get_hyperdl_requirements():
    """Get a list of requirements for HyperDL to work"""
    return [
        "HELPER_TOKENS: Add bot tokens separated by spaces",
        "Example: HELPER_TOKENS='bot1_token bot2_token bot3_token'",
        "More helper bots = faster downloads",
        "Each bot should be created via @BotFather",
        "Optional: HYPER_THREADS to control max parts",
        "Optional: HYPER_SESSION_TIMEOUT for session timeout",
    ]

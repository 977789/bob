class DirectDownloadLinkException(Exception):
    """Not method found for extracting direct download link from the http link"""

    pass


class NotSupportedExtractionArchive(Exception):
    """The archive format use is trying to extract is not supported"""

    pass


class RssShutdownException(Exception):
    """This exception should be raised when shutdown is called to stop the montior"""

    pass


class TgLinkException(Exception):
    """No Access granted for this chat"""

    pass


# Added for stream utils compatibility
class InvalidHash(Exception):
    """Invalid or mismatched hash for a requested media/link"""

    message = "Invalid hash!"


class FIleNotFound(Exception):
    """Media/file not found for the requested message or path"""

    # Note: Name kept for compatibility with upstream reference (typo intentional)
    message = "File not found!"

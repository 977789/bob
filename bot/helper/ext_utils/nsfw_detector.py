import re
from urllib.parse import urlparse, unquote
from typing import Optional, Tuple

from ... import LOGGER


class NSFWDetector:
    """
    Anti-NSFW content detector for filtering adult content
    Uses intelligent context-aware detection to minimize false positives
    """

    # High-confidence NSFW keywords (always block)
    HIGH_CONFIDENCE_KEYWORDS = {
        # Explicit adult content terms
        "porn",
        "porno",
        "pornhub",
        "xvideos",
        "xhamster",
        "redtube",
        "youporn",
        "tube8",
        "spankbang",
        "xnxx",
        "beeg",
        "tnaflix",
        "sexvid",
        "onlyfans",
        "chaturbate",
        "livejasmin",
        "cam4",
        "bongacams",
        "stripchat",
        "camsoda",
        "myfreecams",
        "manyvids",
        "clips4sale",
        "modelhub",
        # Clear sexual terms
        "masturbate",
        "masturbation",
        "orgasm",
        "ejaculation",
        "gangbang",
        "threesome",
        "foursome",
        "orgy",
        "swinger",
        "camgirl",
        "blowjob",
        "rimming",
        "fisting",
        "pegging",
        # Explicit anatomy
        "penis",
        "vagina",
        "pussy",
        "cock",
        "dick",
        "clit",
        "labia",
        "testicle",
        "scrotum",
        "butthole",
        "asshole",
        "foreskin",
        # Adult services
        "escort",
        "prostitute",
        "hooker",
        "whore",
        "slut",
        # Clear fetish terms
        "bdsm",
        "bondage",
        "domination",
        "submission",
        "mistress",
        "dildo",
        "vibrator",
        "sex toy",
        "anal sex",
        "oral sex",
        # Adult content labels
        "nsfw",
        "uncensored",
        "erotic",
        "naked",
        # Regional variants
        "sexo",
        "porno",
        "adulto",
        "erotico",
        "desnudo",
        "caliente",
        "follar",
        "coger",
        "joder",
        "puta",
        "zorra",
        "perra",
        # Clear profanity
        "fucking",
        "fucked",
        "fucker",
        "bitch",
        "cunt",
        "twat",
        "faggot",
        "nigger",
        "nigga",
    }

    # Context-dependent keywords (only block if combined with other indicators)
    CONTEXT_KEYWORDS = {
        "gay",
        "lesbian",
        "straight",
        "bi",
        "lgbt",
        "lgbtq",
        "trans",
        # Body parts (medical/innocent in most contexts)
        "breast",
        "boobs",
        "tits",
        "nipple",
        "chest",
    }

    # Adult content indicators (help determine context)
    ADULT_INDICATORS = set()

    # Known safe words that might appear with suspicious words
    SAFE_CONTEXT_WORDS = {
        "movie",
        "film",
        "cinema",
        "series",
        "episode",
        "season",
        "show",
        "tv",
        "documentary",
        "anime",
        "cartoon",
        "game",
        "video game",
        "book",
        "novel",
        "music",
        "song",
        "album",
        "artist",
        "band",
        "actor",
        "actress",
        "director",
        "trailer",
        "review",
        "news",
        "interview",
        "behind scenes",
        "making of",
        "comedy",
        "drama",
        "action",
        "adventure",
        "thriller",
        "horror",
        "sci-fi",
        "fantasy",
        "romance",
        "musical",
        "western",
        "war",
        "crime",
        "mystery",
        "family",
        "kids",
        "children",
        "education",
        "learning",
        "tutorial",
        "cooking",
        "recipe",
        "travel",
        "nature",
        "wildlife",
        "sports",
        "fitness",
        "health",
        "medical",
        "science",
        "technology",
        "history",
        "culture",
    }

    # Domains known for hosting adult content
    NSFW_DOMAINS = {
        "pornhub.com",
        "xvideos.com",
        "xhamster.com",
        "redtube.com",
        "youporn.com",
        "tube8.com",
        "spankbang.com",
        "xnxx.com",
        "beeg.com",
        "tnaflix.com",
        "chaturbate.com",
        "livejasmin.com",
        "cam4.com",
        "bongacams.com",
        "stripchat.com",
        "camsoda.com",
        "myfreecams.com",
        "flirt4free.com",
        "onlyfans.com",
        "manyvids.com",
        "clips4sale.com",
        "modelhub.com",
        "adultfriendfinder.com",
        "ashleymadison.com",
        "sexvid.xxx",
        "pornmd.com",
        "sex.com",
        "redtube.com.br",
        "youjizz.com",
        "drtuber.com",
        "keezmovies.com",
        "extremetube.com",
        "sunporno.com",
    }

    @classmethod
    def is_nsfw_content(
        cls, url: str, filename: str = ""
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if the given URL or filename contains NSFW content using intelligent detection

        Args:
            url (str): The URL to check
            filename (str): The filename to check (optional)

        Returns:
            Tuple[bool, Optional[str]]: (is_nsfw, reason)
        """
        try:
            # Check URL for NSFW patterns
            if url:
                is_nsfw_url, url_reason = cls._check_url(url)
                if is_nsfw_url:
                    return True, url_reason

            # Check filename for NSFW patterns
            if filename:
                is_nsfw_file, file_reason = cls._check_filename(filename)
                if is_nsfw_file:
                    return True, file_reason

            return False, None

        except Exception as e:
            LOGGER.error(f"Error in NSFW detection: {e}")
            return False, None

    @classmethod
    def _check_url(cls, url: str) -> Tuple[bool, Optional[str]]:
        """Check URL for NSFW content - only domain-based blocking"""
        if not url:
            return False, None

        # Check domain only (highest confidence)
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()

            # Remove www. prefix if present
            if domain.startswith("www."):
                domain = domain[4:]

            if domain in cls.NSFW_DOMAINS:
                return True, f"Known adult content domain: {domain}"

        except Exception:
            pass

        # No keyword or pattern checking for URLs - only domain-based blocking
        return False, None

    @classmethod
    def _check_filename(cls, filename: str) -> Tuple[bool, Optional[str]]:
        """Check filename for NSFW content with intelligent analysis"""
        if not filename:
            return False, None

        # Convert to lowercase for case-insensitive matching
        filename_lower = filename.lower()

        # Remove common separators and replace with spaces for better keyword matching
        cleaned_filename = re.sub(r"[._\-\[\](){}]", " ", filename_lower)

        # Check for high-confidence keywords first
        for keyword in cls.HIGH_CONFIDENCE_KEYWORDS:
            # Use word boundaries to avoid false positives
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, cleaned_filename):
                return True, f"Explicit adult keyword '{keyword}' found in filename"

        # Context-based analysis for ambiguous content
        return cls._analyze_context(cleaned_filename, "filename")

    @classmethod
    def _analyze_context(
        cls, content: str, content_type: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Analyze content context to determine if it's likely NSFW
        Uses scoring system and context clues to minimize false positives
        """
        content_words = set(re.findall(r"\b\w+\b", content.lower()))

        # Check for safe context words
        safe_words_found = content_words.intersection(cls.SAFE_CONTEXT_WORDS)
        if safe_words_found:
            # If safe context words are found, be more lenient
            LOGGER.info(f"Safe context detected in {content_type}: {safe_words_found}")

            # Only block if we have multiple strong adult indicators
            adult_indicators_found = content_words.intersection(cls.ADULT_INDICATORS)
            context_keywords_found = content_words.intersection(cls.CONTEXT_KEYWORDS)

            # Need at least 2 adult indicators + 2 context keywords to block when safe words present
            if len(adult_indicators_found) >= 2 and len(context_keywords_found) >= 2:
                return (
                    True,
                    f"Multiple adult indicators despite safe context in {content_type}",
                )

            return False, None

        # No safe context, use standard analysis
        adult_indicators_found = content_words.intersection(cls.ADULT_INDICATORS)
        context_keywords_found = content_words.intersection(cls.CONTEXT_KEYWORDS)

        # Scoring system
        score = 0
        score += len(adult_indicators_found) * 2  # Adult indicators worth 2 points each
        score += len(context_keywords_found) * 1  # Context keywords worth 1 point each

        # Additional scoring for specific combinations
        suspicious_combinations = [
            ("teen", "amateur"),
            ("young", "amateur"),
            ("private", "show"),
            ("cam", "girl"),
            ("web", "cam"),
            ("live", "show"),
            ("big", "tits"),
            ("huge", "boobs"),
            ("hot", "teen"),
            ("sexy", "amateur"),
        ]

        for combo in suspicious_combinations:
            if all(word in content_words for word in combo):
                score += 3

        # Threshold for blocking (reduced to be less aggressive)
        if score >= 4:  # Increased threshold from 3 to 4
            return (
                True,
                f"Suspicious content pattern detected in {content_type} (score: {score})",
            )

        return False, None

    @classmethod
    def get_content_category(cls, url: str, filename: str = "") -> str:
        """
        Get a category description for the detected content

        Args:
            url (str): The URL to categorize
            filename (str): The filename to categorize (optional)

        Returns:
            str: Category description
        """
        is_nsfw, reason = cls.is_nsfw_content(url, filename)

        if not is_nsfw:
            return "Safe Content"

        # Categorize based on the type of NSFW content detected
        url_lower = url.lower() if url else ""
        filename_lower = filename.lower() if filename else ""
        content = f"{url_lower} {filename_lower}"

        # Check for known adult domains
        for domain in cls.NSFW_DOMAINS:
            if domain in content:
                return "Known Adult Website"

        # Check for explicit keywords
        explicit_terms = ["porn", "xxx", "explicit", "nsfw", "adult"]
        if any(term in content for term in explicit_terms):
            return "Explicit Adult Content"
        elif any(term in content for term in ["cam", "webcam", "live", "chat"]):
            return "Live Adult Streaming"
        elif any(term in content for term in ["escort", "massage", "dating"]):
            return "Adult Services"
        elif any(term in content for term in ["fetish", "bdsm", "kinky"]):
            return "Adult Fetish Content"
        else:
            return "Potentially Adult Content"

    @classmethod
    def should_block_content(cls, url: str, filename: str = "") -> bool:
        """
        Simple boolean check if content should be blocked

        Args:
            url (str): The URL to check
            filename (str): The filename to check (optional)

        Returns:
            bool: True if content should be blocked
        """
        is_nsfw, _ = cls.is_nsfw_content(url, filename)
        return is_nsfw

    @classmethod
    def get_detection_stats(cls) -> dict:
        """Get statistics about the detection system"""
        return {
            "high_confidence_keywords": len(cls.HIGH_CONFIDENCE_KEYWORDS),
            "context_keywords": len(cls.CONTEXT_KEYWORDS),
            "adult_indicators": len(cls.ADULT_INDICATORS),
            "safe_context_words": len(cls.SAFE_CONTEXT_WORDS),
            "blocked_domains": len(cls.NSFW_DOMAINS),
        }

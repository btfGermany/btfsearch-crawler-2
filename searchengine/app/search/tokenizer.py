"""Query tokenization and normalization."""

import re
import unicodedata
from typing import List, Set

import structlog

logger = structlog.get_logger()

# Stopwords for multiple languages
STOPWORDS = {
    "en": {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
        "to", "was", "will", "with", "the", "this", "these", "those",
        "i", "you", "we", "they", "what", "which", "who", "when", "where",
        "how", "why", "all", "would", "there", "their", "or", "but"
    },
    "de": {
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer",
        "eines", "einem", "einen", "und", "oder", "aber", "als", "am",
        "an", "auf", "aus", "bei", "bis", "durch", "für", "gegen", "in",
        "mit", "nach", "seit", "über", "um", "von", "vor", "zu", "zur",
        "ich", "du", "er", "sie", "es", "wir", "ihr", "sie", "nicht"
    },
    "fr": {
        "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou",
        "mais", "que", "qui", "dans", "sur", "avec", "pour", "par",
        "sans", "sous", "entre", "vers", "chez", "il", "elle", "on",
        "nous", "vous", "ils", "elles", "ce", "cette", "ces", "ne", "pas"
    },
    "es": {
        "el", "la", "los", "las", "un", "una", "y", "o", "pero", "que",
        "de", "del", "en", "con", "por", "para", "sin", "sobre", "entre",
        "hacia", "hasta", "desde", "durante", "mediante", "yo", "tu",
        "él", "ella", "nosotros", "vosotros", "ellos", "ellas", "no"
    }
}


class QueryTokenizer:
    """Tokenizer for search queries with multi-language support."""
    
    def __init__(self, default_lang: str = "en", enable_stemming: bool = False):
        """Initialize tokenizer.
        
        Args:
            default_lang: Default language for stopwords
            enable_stemming: Enable word stemming
        """
        self.default_lang = default_lang
        self.enable_stemming = enable_stemming
        self.stopwords = STOPWORDS.get(default_lang, STOPWORDS["en"])
    
    def normalize(self, query: str, lang: str = None) -> str:
        """Normalize a search query.
        
        Args:
            query: Raw query string
            lang: Language code for stopwords
        
        Returns:
            Normalized query string
        """
        if not query:
            return ""
        
        # Unicode normalization
        query = unicodedata.normalize('NFKD', query)
        
        # Convert to lowercase
        query = query.lower()
        
        # Remove special characters but keep spaces and basic punctuation
        query = re.sub(r'[^\w\s\-\+\"\'\.]', ' ', query)
        
        # Handle quoted phrases
        quoted_phrases = re.findall(r'"([^"]*)"', query)
        query = re.sub(r'"[^"]*"', ' QUOTED_PHRASE ', query)
        
        # Tokenize
        tokens = query.split()
        
        # Get appropriate stopwords
        stopwords = STOPWORDS.get(lang or self.default_lang, self.stopwords)
        
        # Process tokens
        processed_tokens = []
        phrase_index = 0
        
        for token in tokens:
            if token == "QUOTED_PHRASE":
                # Restore quoted phrase
                if phrase_index < len(quoted_phrases):
                    processed_tokens.append(f'"{quoted_phrases[phrase_index]}"')
                    phrase_index += 1
            elif token not in stopwords and len(token) > 1:
                # Apply stemming if enabled
                if self.enable_stemming:
                    token = self._stem(token, lang or self.default_lang)
                processed_tokens.append(token)
        
        return ' '.join(processed_tokens)
    
    def tokenize(self, text: str, lang: str = None) -> List[str]:
        """Tokenize text into words.
        
        Args:
            text: Text to tokenize
            lang: Language code
        
        Returns:
            List of tokens
        """
        if not text:
            return []
        
        # Normalize
        text = unicodedata.normalize('NFKD', text)
        text = text.lower()
        
        # Split on non-word characters
        tokens = re.findall(r'\w+', text)
        
        # Filter stopwords
        stopwords = STOPWORDS.get(lang or self.default_lang, self.stopwords)
        tokens = [t for t in tokens if t not in stopwords and len(t) > 1]
        
        # Apply stemming if enabled
        if self.enable_stemming:
            tokens = [self._stem(t, lang or self.default_lang) for t in tokens]
        
        return tokens
    
    def _stem(self, word: str, lang: str) -> str:
        """Simple stemming implementation.
        
        Args:
            word: Word to stem
            lang: Language code
        
        Returns:
            Stemmed word
        """
        # Very basic stemming rules (production would use NLTK or similar)
        if lang == "en":
            # Remove common English suffixes
            suffixes = ["ing", "ed", "es", "s", "ly", "er", "est", "tion", "ment"]
            for suffix in suffixes:
                if word.endswith(suffix) and len(word) > len(suffix) + 2:
                    return word[:-len(suffix)]
        
        elif lang == "de":
            # Remove common German suffixes
            suffixes = ["ung", "heit", "keit", "schaft", "en", "er", "est", "e"]
            for suffix in suffixes:
                if word.endswith(suffix) and len(word) > len(suffix) + 2:
                    return word[:-len(suffix)]
        
        elif lang == "fr":
            # Remove common French suffixes
            suffixes = ["tion", "ment", "eur", "euse", "er", "ir", "re", "s", "e"]
            for suffix in suffixes:
                if word.endswith(suffix) and len(word) > len(suffix) + 2:
                    return word[:-len(suffix)]
        
        elif lang == "es":
            # Remove common Spanish suffixes
            suffixes = ["ción", "mente", "ador", "adora", "ar", "er", "ir", "s", "es"]
            for suffix in suffixes:
                if word.endswith(suffix) and len(word) > len(suffix) + 2:
                    return word[:-len(suffix)]
        
        return word
    
    def extract_phrases(self, query: str) -> tuple[List[str], str]:
        """Extract quoted phrases from query.
        
        Args:
            query: Search query
        
        Returns:
            Tuple of (phrases, query_without_phrases)
        """
        phrases = re.findall(r'"([^"]*)"', query)
        clean_query = re.sub(r'"[^"]*"', '', query).strip()
        return phrases, clean_query
    
    def expand_query(self, query: str, synonyms: dict = None) -> str:
        """Expand query with synonyms.
        
        Args:
            query: Original query
            synonyms: Dictionary of word -> [synonyms]
        
        Returns:
            Expanded query
        """
        if not synonyms:
            return query
        
        tokens = self.tokenize(query)
        expanded = []
        
        for token in tokens:
            expanded.append(token)
            if token in synonyms:
                # Add synonyms with OR operator
                syn_list = synonyms[token][:3]  # Limit synonyms
                if syn_list:
                    expanded.append(f"({' OR '.join(syn_list)})")
        
        return ' '.join(expanded)
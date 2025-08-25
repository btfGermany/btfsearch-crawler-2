"""Autocomplete index using trie data structure."""

import json
from collections import defaultdict
from typing import Dict, List, Optional, Set

import structlog

logger = structlog.get_logger()


class TrieNode:
    """Node in the trie structure."""
    
    def __init__(self):
        self.children: Dict[str, TrieNode] = {}
        self.is_end: bool = False
        self.frequency: int = 0
        self.suggestions: List[str] = []


class AutocompleteIndex:
    """Autocomplete index using trie for prefix search."""
    
    def __init__(self, max_suggestions_per_node: int = 5):
        """Initialize autocomplete index.
        
        Args:
            max_suggestions_per_node: Maximum suggestions to store per node
        """
        self.root = TrieNode()
        self.max_suggestions = max_suggestions_per_node
        self.total_terms = 0
    
    def insert(self, term: str, frequency: int = 1) -> None:
        """Insert a term into the trie.
        
        Args:
            term: Term to insert
            frequency: Term frequency/weight
        """
        if not term:
            return
        
        term = term.lower().strip()
        node = self.root
        
        for char in term:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        
        node.is_end = True
        node.frequency += frequency
        self.total_terms += 1
        
        # Update suggestions along the path
        self._update_suggestions(term, frequency)
    
    def _update_suggestions(self, term: str, frequency: int) -> None:
        """Update suggestions for all prefixes of the term.
        
        Args:
            term: Complete term
            frequency: Term frequency
        """
        for i in range(1, len(term) + 1):
            prefix = term[:i]
            node = self._find_node(prefix)
            
            if node:
                # Add or update suggestion
                suggestions = node.suggestions
                
                # Check if term already exists
                exists = False
                for j, (sug, freq) in enumerate(suggestions):
                    if sug == term:
                        suggestions[j] = (term, suggestions[j][1] + frequency)
                        exists = True
                        break
                
                if not exists:
                    suggestions.append((term, frequency))
                
                # Sort by frequency and limit
                suggestions.sort(key=lambda x: x[1], reverse=True)
                node.suggestions = suggestions[:self.max_suggestions]
    
    def _find_node(self, prefix: str) -> Optional[TrieNode]:
        """Find node for a given prefix.
        
        Args:
            prefix: Prefix to search
        
        Returns:
            TrieNode if found, None otherwise
        """
        node = self.root
        for char in prefix.lower():
            if char not in node.children:
                return None
            node = node.children[char]
        return node
    
    async def suggest(self, prefix: str, limit: int = 10) -> List[str]:
        """Get autocomplete suggestions for a prefix.
        
        Args:
            prefix: Search prefix
            limit: Maximum suggestions
        
        Returns:
            List of suggestions
        """
        if not prefix:
            return []
        
        prefix = prefix.lower().strip()
        node = self._find_node(prefix)
        
        if not node:
            return []
        
        # Get suggestions from node
        suggestions = []
        
        # First add cached suggestions
        for term, _ in node.suggestions[:limit]:
            suggestions.append(term)
        
        # If we need more, do DFS
        if len(suggestions) < limit:
            additional = self._dfs_suggestions(node, prefix, limit - len(suggestions))
            for term in additional:
                if term not in suggestions:
                    suggestions.append(term)
        
        return suggestions[:limit]
    
    def _dfs_suggestions(
        self,
        node: TrieNode,
        prefix: str,
        limit: int
    ) -> List[str]:
        """DFS to find suggestions from a node.
        
        Args:
            node: Starting node
            prefix: Current prefix
            limit: Maximum suggestions
        
        Returns:
            List of suggestions
        """
        suggestions = []
        
        def dfs(current_node: TrieNode, current_word: str):
            if len(suggestions) >= limit:
                return
            
            if current_node.is_end:
                suggestions.append(current_word)
            
            for char, child in sorted(
                current_node.children.items(),
                key=lambda x: -x[1].frequency if x[1].is_end else 0
            ):
                if len(suggestions) >= limit:
                    break
                dfs(child, current_word + char)
        
        dfs(node, prefix)
        return suggestions
    
    async def build_from_queries(self, queries: List[Dict[str, any]]) -> None:
        """Build index from query logs.
        
        Args:
            queries: List of query dictionaries with 'query' and 'count' fields
        """
        logger.info("Building autocomplete index", total_queries=len(queries))
        
        for query_data in queries:
            query = query_data.get("query", "")
            count = query_data.get("count", 1)
            
            if query:
                self.insert(query, count)
        
        logger.info("Autocomplete index built", total_terms=self.total_terms)
    
    async def build_from_titles(self, titles: List[str]) -> None:
        """Build index from document titles.
        
        Args:
            titles: List of document titles
        """
        logger.info("Building autocomplete from titles", total_titles=len(titles))
        
        # Extract important terms from titles
        term_freq = defaultdict(int)
        
        for title in titles:
            if not title:
                continue
            
            # Insert full title with lower weight
            self.insert(title, 1)
            
            # Insert individual words with higher weight
            words = title.lower().split()
            for word in words:
                if len(word) > 2:  # Skip very short words
                    term_freq[word] += 1
        
        # Insert high-frequency words
        for word, freq in term_freq.items():
            if freq > 1:  # Only common words
                self.insert(word, freq * 2)
        
        logger.info("Autocomplete index from titles built", total_terms=self.total_terms)
    
    async def save(self, filepath: str) -> None:
        """Save index to file.
        
        Args:
            filepath: Path to save file
        """
        try:
            data = self._serialize()
            with open(filepath, 'w') as f:
                json.dump(data, f)
            logger.info("Autocomplete index saved", path=filepath)
        except Exception as e:
            logger.error("Failed to save autocomplete index", error=str(e))
    
    async def load(self, filepath: str) -> None:
        """Load index from file.
        
        Args:
            filepath: Path to load file
        """
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            self._deserialize(data)
            logger.info("Autocomplete index loaded", path=filepath)
        except Exception as e:
            logger.error("Failed to load autocomplete index", error=str(e))
    
    def _serialize(self) -> Dict:
        """Serialize trie to dictionary.
        
        Returns:
            Serialized trie data
        """
        def serialize_node(node: TrieNode) -> Dict:
            return {
                "is_end": node.is_end,
                "frequency": node.frequency,
                "suggestions": node.suggestions,
                "children": {
                    char: serialize_node(child)
                    for char, child in node.children.items()
                }
            }
        
        return {
            "root": serialize_node(self.root),
            "total_terms": self.total_terms,
            "max_suggestions": self.max_suggestions
        }
    
    def _deserialize(self, data: Dict) -> None:
        """Deserialize dictionary to trie.
        
        Args:
            data: Serialized trie data
        """
        def deserialize_node(node_data: Dict) -> TrieNode:
            node = TrieNode()
            node.is_end = node_data.get("is_end", False)
            node.frequency = node_data.get("frequency", 0)
            node.suggestions = node_data.get("suggestions", [])
            
            for char, child_data in node_data.get("children", {}).items():
                node.children[char] = deserialize_node(child_data)
            
            return node
        
        self.root = deserialize_node(data["root"])
        self.total_terms = data.get("total_terms", 0)
        self.max_suggestions = data.get("max_suggestions", 5)